from __future__ import annotations

import asyncio
import importlib.util
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request as UrlRequest
from urllib.request import urlopen

from fathom.adapters.storage.database import DataSourceRecord
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker


class DataSourceInput(BaseModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_.-]+$")
    name: str = Field(min_length=2, max_length=160)
    connector_type: str
    configuration: dict[str, Any] = Field(default_factory=dict)
    secret_reference: str | None = None
    enabled: bool = True


CONNECTOR_TYPES = [
    {"key": "sqlite", "label": "SQLite", "category": "database", "bundled": True},
    {"key": "duckdb", "label": "DuckDB", "category": "database", "bundled": True},
    {
        "key": "postgresql",
        "label": "PostgreSQL",
        "category": "database",
        "bundled": False,
        "driver": "psycopg",
        "extra": "connectors-sql",
    },
    {
        "key": "mysql",
        "label": "MySQL",
        "category": "database",
        "bundled": False,
        "driver": "pymysql",
        "extra": "connectors-sql",
    },
    {
        "key": "sqlserver",
        "label": "SQL Server",
        "category": "database",
        "bundled": False,
        "driver": "pyodbc",
        "extra": "connectors-sql",
    },
    {
        "key": "oracle",
        "label": "Oracle",
        "category": "database",
        "bundled": False,
        "driver": "oracledb",
        "extra": "connectors-sql",
    },
    {"key": "file", "label": "CSV / JSON / Parquet", "category": "file", "bundled": True},
    {"key": "rest", "label": "REST API", "category": "api", "bundled": True},
    {
        "key": "opcua",
        "label": "OPC UA",
        "category": "ot",
        "bundled": False,
        "driver": "asyncua",
        "extra": "connectors-industrial",
    },
    {
        "key": "mqtt",
        "label": "MQTT",
        "category": "ot",
        "bundled": False,
        "driver": "paho.mqtt.client",
        "extra": "connectors-industrial",
    },
    {
        "key": "historian",
        "label": "Industrial Historian",
        "category": "ot",
        "bundled": False,
        "driver": None,
        "extra": "vendor-plugin",
    },
    {
        "key": "tdengine",
        "label": "TDengine",
        "category": "timeseries",
        "bundled": False,
        "driver": "taosws",
        "extra": "connectors-industrial",
    },
    {
        "key": "redis",
        "label": "Redis / KV",
        "category": "kv",
        "bundled": False,
        "driver": "redis",
        "extra": "connectors-context",
    },
    {
        "key": "elasticsearch",
        "label": "Elasticsearch",
        "category": "text",
        "bundled": False,
        "driver": "elasticsearch",
        "extra": "connectors-context",
    },
    {
        "key": "neo4j",
        "label": "Neo4j",
        "category": "graph",
        "bundled": False,
        "driver": "neo4j",
        "extra": "connectors-context",
    },
    {
        "key": "qdrant",
        "label": "Qdrant",
        "category": "vector",
        "bundled": False,
        "driver": "qdrant_client",
        "extra": "connectors-context",
    },
]


def connector_catalog() -> list[dict[str, Any]]:
    catalog = []
    for definition in CONNECTOR_TYPES:
        item = dict(definition)
        driver = item.get("driver")
        try:
            driver_available = bool(driver and importlib.util.find_spec(driver))
        except (ImportError, ModuleNotFoundError):
            driver_available = False
        item["driver_available"] = bool(item["bundled"] or driver_available)
        item["operations"] = ["test", "discover", "scaffold"]
        item["install_hint"] = (
            None if item["driver_available"] else f"pip install fathom[{item['extra']}]"
        )
        catalog.append(item)
    return catalog


class DataSourceService:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def list(self) -> list[dict[str, Any]]:
        with self._session_factory() as session:
            records = session.scalars(
                select(DataSourceRecord).order_by(DataSourceRecord.name)
            ).all()
            return [self._serialize(record) for record in records]

    def save(self, payload: DataSourceInput) -> dict[str, Any]:
        if payload.connector_type not in {item["key"] for item in CONNECTOR_TYPES}:
            raise ValueError(f"Unsupported connector type: {payload.connector_type}")
        if self._contains_secret(payload.configuration):
            raise ValueError("敏感值不能写入普通配置，请使用 secret_reference")
        with self._session_factory() as session:
            record = session.get(DataSourceRecord, payload.key)
            values = payload.model_dump()
            if record is None:
                record = DataSourceRecord(**values)
                session.add(record)
            else:
                for key, value in values.items():
                    setattr(record, key, value)
                record.status = "untested"
            session.commit()
            session.refresh(record)
            return self._serialize(record)

    def test(self, key: str) -> dict[str, Any]:
        with self._session_factory() as session:
            record = session.get(DataSourceRecord, key)
            if record is None:
                raise LookupError(key)
            result = self._test_record(record)
            record.status = result["status"]
            record.last_tested_at = datetime.now(UTC)
            session.commit()
            return result

    def discover(self, key: str) -> dict[str, Any]:
        with self._session_factory() as session:
            record = session.get(DataSourceRecord, key)
            if record is None:
                raise LookupError(key)
            if record.connector_type == "sqlite":
                path = self._required_path(record.configuration)
                connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
                try:
                    tables = connection.execute(
                        "SELECT name FROM sqlite_master "
                        "WHERE type='table' AND name NOT LIKE 'sqlite_%' "
                        "ORDER BY name"
                    ).fetchall()
                    schemas = []
                    for (table_name,) in tables:
                        escaped = table_name.replace('"', '""')
                        columns = connection.execute(f'PRAGMA table_info("{escaped}")').fetchall()
                        foreign_keys = connection.execute(
                            f'PRAGMA foreign_key_list("{escaped}")'
                        ).fetchall()
                        schemas.append(
                            {
                                "name": table_name,
                                "columns": [
                                    {
                                        "name": column[1],
                                        "type": column[2],
                                        "nullable": not bool(column[3]),
                                        "primary_key": bool(column[5]),
                                    }
                                    for column in columns
                                ],
                                "foreign_keys": [
                                    {
                                        "column": foreign_key[3],
                                        "target_table": foreign_key[2],
                                        "target_column": foreign_key[4],
                                    }
                                    for foreign_key in foreign_keys
                                ],
                            }
                        )
                    return {"source": key, "tables": schemas}
                finally:
                    connection.close()
            if record.connector_type == "duckdb":
                import duckdb

                path = self._required_path(record.configuration)
                connection = duckdb.connect(str(path), read_only=True)
                try:
                    tables = connection.execute("SHOW TABLES").fetchall()
                    schemas = []
                    for (table_name,) in tables:
                        escaped = table_name.replace('"', '""')
                        columns = connection.execute(
                            f'DESCRIBE SELECT * FROM "{escaped}"'
                        ).fetchall()
                        schemas.append(
                            {
                                "name": table_name,
                                "columns": [
                                    {"name": column[0], "type": column[1]} for column in columns
                                ],
                            }
                        )
                    return {"source": key, "tables": schemas}
                finally:
                    connection.close()
            if record.connector_type == "file":
                return self._discover_file(key, record.configuration)
            if record.connector_type == "rest":
                return self._discover_rest(key, record)
            if record.connector_type in {"postgresql", "mysql", "sqlserver", "oracle"}:
                return self._discover_sqlalchemy(key, record)
            if record.connector_type == "tdengine":
                return self._discover_tdengine(key, record)
            if record.connector_type == "redis":
                return self._discover_redis(key, record)
            if record.connector_type == "elasticsearch":
                return self._discover_elasticsearch(key, record)
            if record.connector_type == "neo4j":
                return self._discover_neo4j(key, record)
            if record.connector_type == "qdrant":
                return self._discover_qdrant(key, record)
            if record.connector_type == "mqtt":
                return self._discover_mqtt(key, record)
            if record.connector_type == "opcua":
                return self._discover_opcua(key, record)
            raise ValueError("该连接器需要安装对应驱动插件后才能发现 Schema")

    def scaffold(self, key: str) -> dict[str, Any]:
        discovered = self.discover(key)
        objects = []
        attributes = []
        relations = []
        for table in discovered["tables"]:
            table_name = table["name"]
            objects.append(
                {
                    "key": table_name,
                    "kind": "object",
                    "label": table_name.replace("_", " ").title(),
                    "source": f"{key}.{table_name}",
                    "confidence": 0.82,
                    "status": "candidate",
                }
            )
            for column in table.get("columns", []):
                attributes.append(
                    {
                        "key": f"{table_name}.{column['name']}",
                        "kind": "attribute",
                        "label": column["name"].replace("_", " ").title(),
                        "object": table_name,
                        "source_type": column["type"],
                        "identity_candidate": column.get("primary_key", False),
                        "confidence": 0.78,
                        "status": "candidate",
                    }
                )
            for foreign_key in table.get("foreign_keys", []):
                relations.append(
                    {
                        "key": f"{table_name}_to_{foreign_key['target_table']}",
                        "kind": "relation",
                        "source_object": table_name,
                        "target_object": foreign_key["target_table"],
                        "source_column": foreign_key["column"],
                        "target_column": foreign_key["target_column"],
                        "confidence": 0.96,
                        "status": "candidate",
                    }
                )
        return {
            "source": key,
            "objects": objects,
            "attributes": attributes,
            "relations": relations,
            "next_step": "review_and_publish",
        }

    def _test_record(self, record: DataSourceRecord) -> dict[str, Any]:
        try:
            if record.connector_type == "sqlite":
                path = self._required_path(record.configuration)
                connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
                connection.execute("SELECT 1").fetchone()
                connection.close()
                return {"status": "online", "message": "SQLite 连接成功"}
            if record.connector_type == "duckdb":
                import duckdb

                path = self._required_path(record.configuration)
                connection = duckdb.connect(str(path), read_only=True)
                connection.execute("SELECT 1").fetchone()
                connection.close()
                return {"status": "online", "message": "DuckDB 连接成功"}
            if record.connector_type == "file":
                path = self._required_path(record.configuration)
                return {"status": "online", "message": f"文件可读取：{path.name}"}
            if record.connector_type == "rest":
                return self._test_rest(record)
            if record.connector_type in {"postgresql", "mysql", "sqlserver", "oracle"}:
                return self._test_sqlalchemy(record)
            if record.connector_type == "tdengine":
                return self._test_tdengine(record)
            if record.connector_type == "opcua":
                return self._test_opcua(record)
            if record.connector_type == "mqtt":
                return self._test_mqtt(record)
            if record.connector_type == "redis":
                return self._test_redis(record)
            if record.connector_type == "elasticsearch":
                return self._test_elasticsearch(record)
            if record.connector_type == "neo4j":
                return self._test_neo4j(record)
            if record.connector_type == "qdrant":
                return self._test_qdrant(record)
            if record.connector_type == "historian":
                return {
                    "status": "driver_required",
                    "message": "已提供 REST/ODBC 通用入口；专有协议需安装厂商插件",
                }
            secret_status = self._secret_status(record.secret_reference)
            return {
                "status": "driver_required",
                "message": (
                    f"连接配置有效；需安装 {record.connector_type} 驱动插件。{secret_status}"
                ),
            }
        except (OSError, sqlite3.Error, RuntimeError, ValueError) as error:
            return {"status": "offline", "message": str(error)}

    def _test_rest(self, record: DataSourceRecord) -> dict[str, Any]:
        endpoint = str(record.configuration.get("endpoint", ""))
        parsed = urlparse(endpoint)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("REST 配置需要有效的 http(s) endpoint")
        headers = {
            str(key): str(value) for key, value in record.configuration.get("headers", {}).items()
        }
        secret = self._resolve_secret(record.secret_reference)
        if secret:
            headers.setdefault("Authorization", f"Bearer {secret}")
        request = UrlRequest(endpoint, headers=headers, method="GET")
        try:
            timeout = float(record.configuration.get("timeout", 8))
            with urlopen(request, timeout=timeout) as response:
                return {"status": "online", "message": f"REST 连接成功 · HTTP {response.status}"}
        except HTTPError as error:
            raise RuntimeError(f"REST 返回 HTTP {error.code}") from error
        except URLError as error:
            raise RuntimeError(f"REST 连接失败：{error.reason}") from error

    def _discover_rest(self, key: str, record: DataSourceRecord) -> dict[str, Any]:
        import json

        endpoint = str(record.configuration.get("endpoint", ""))
        parsed = urlparse(endpoint)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("REST 配置需要有效的 http(s) endpoint")
        headers = {
            str(header): str(value)
            for header, value in record.configuration.get("headers", {}).items()
        }
        secret = self._resolve_secret(record.secret_reference)
        if secret:
            headers.setdefault("Authorization", f"Bearer {secret}")
        request = UrlRequest(endpoint, headers=headers, method="GET")
        try:
            with urlopen(
                request, timeout=float(record.configuration.get("timeout", 8))
            ) as response:
                size_limit = 2 * 1024 * 1024
                content = response.read(size_limit + 1)
                if len(content) > size_limit:
                    raise ValueError("REST Schema 发现响应超过 2MB")
                payload = json.loads(content)
        except (HTTPError, URLError, json.JSONDecodeError) as error:
            raise ValueError(f"REST Schema 发现失败：{error}") from error
        item_path = str(record.configuration.get("items_path", "")).strip()
        selected = payload
        if item_path:
            for part in item_path.split("."):
                if not isinstance(selected, dict) or part not in selected:
                    raise ValueError(f"REST items_path 不存在：{item_path}")
                selected = selected[part]
        rows = selected if isinstance(selected, list) else [selected]
        samples = [row for row in rows[:20] if isinstance(row, dict)]
        columns = []
        for name in sorted({name for row in samples for name in row}):
            value = next((row[name] for row in samples if row.get(name) is not None), None)
            columns.append({"name": name, "type": self._json_type(value)})
        return {
            "source": key,
            "tables": [
                {
                    "name": str(record.configuration.get("resource_name", "api_resource")),
                    "columns": columns,
                    "sample_count": len(samples),
                }
            ],
        }

    @staticmethod
    def _json_type(value: Any) -> str:
        if value is None:
            return "NULL"
        if isinstance(value, bool):
            return "BOOLEAN"
        if isinstance(value, int):
            return "BIGINT"
        if isinstance(value, float):
            return "DOUBLE"
        if isinstance(value, (dict, list)):
            return "JSON"
        return "VARCHAR"

    def _test_sqlalchemy(self, record: DataSourceRecord) -> dict[str, Any]:
        from sqlalchemy import create_engine, text

        url = self._sqlalchemy_url(record)
        engine = create_engine(url, pool_pre_ping=True)
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            return {"status": "online", "message": f"{record.connector_type} 连接成功"}
        finally:
            engine.dispose()

    def _discover_sqlalchemy(self, key: str, record: DataSourceRecord) -> dict[str, Any]:
        from sqlalchemy import create_engine, inspect

        engine = create_engine(self._sqlalchemy_url(record), pool_pre_ping=True)
        try:
            inspector = inspect(engine)
            schema = record.configuration.get("schema")
            tables = []
            for table_name in inspector.get_table_names(schema=schema):
                tables.append(
                    {
                        "name": table_name,
                        "columns": [
                            {
                                "name": column["name"],
                                "type": str(column["type"]),
                                "nullable": column.get("nullable", True),
                            }
                            for column in inspector.get_columns(table_name, schema=schema)
                        ],
                        "foreign_keys": inspector.get_foreign_keys(table_name, schema=schema),
                    }
                )
            return {"source": key, "tables": tables}
        finally:
            engine.dispose()

    def _sqlalchemy_url(self, record: DataSourceRecord):
        from sqlalchemy import URL

        definitions = {
            "postgresql": ("postgresql+psycopg", 5432),
            "mysql": ("mysql+pymysql", 3306),
            "sqlserver": ("mssql+pyodbc", 1433),
            "oracle": ("oracle+oracledb", 1521),
        }
        driver, default_port = definitions[record.connector_type]
        configuration = record.configuration
        if not configuration.get("host") or not configuration.get("database"):
            raise ValueError("数据库配置需要 host 和 database")
        query = dict(configuration.get("query", {}))
        if record.connector_type == "sqlserver":
            query.setdefault("driver", "ODBC Driver 18 for SQL Server")
        return URL.create(
            drivername=driver,
            username=configuration.get("username"),
            password=self._resolve_secret(record.secret_reference),
            host=str(configuration["host"]),
            port=int(configuration.get("port", default_port)),
            database=str(configuration["database"]),
            query={str(key): str(value) for key, value in query.items()},
        )

    def _test_tdengine(self, record: DataSourceRecord) -> dict[str, Any]:
        try:
            import taosws
        except ImportError as error:
            raise RuntimeError(
                "未安装 TDengine WebSocket 驱动：fathom[connectors-industrial]"
            ) from error
        url = str(record.configuration.get("endpoint", ""))
        if urlparse(url).scheme not in {"ws", "wss"}:
            raise ValueError("TDengine endpoint 必须使用 ws:// 或 wss://")
        database = record.configuration.get("database")
        if database and urlparse(url).path in {"", "/"}:
            url = f"{url.rstrip('/')}/{database}"
        secret = self._resolve_secret(record.secret_reference)
        connection = (
            taosws.connect(url=url, bearer_token=secret) if secret else taosws.connect(url=url)
        )
        try:
            cursor = connection.cursor()
            cursor.execute("SELECT SERVER_VERSION()")
            version = cursor.fetchone()[0]
            return {"status": "online", "message": f"TDengine 连接成功 · {version}"}
        finally:
            connection.close()

    def _discover_tdengine(self, key: str, record: DataSourceRecord) -> dict[str, Any]:
        try:
            import taosws
        except ImportError as error:
            raise ValueError("未安装 TDengine WebSocket 驱动") from error
        url = str(record.configuration.get("endpoint", ""))
        database = record.configuration.get("database")
        if database and urlparse(url).path in {"", "/"}:
            url = f"{url.rstrip('/')}/{database}"
        secret = self._resolve_secret(record.secret_reference)
        connection = (
            taosws.connect(url=url, bearer_token=secret) if secret else taosws.connect(url=url)
        )
        try:
            cursor = connection.cursor()
            cursor.execute("SHOW TABLES")
            return {"source": key, "tables": [{"name": row[0]} for row in cursor.fetchall()]}
        finally:
            connection.close()

    def _test_redis(self, record: DataSourceRecord) -> dict[str, Any]:
        import redis

        configuration = record.configuration
        client = redis.Redis(
            host=str(configuration.get("host", "127.0.0.1")),
            port=int(configuration.get("port", 6379)),
            db=int(configuration.get("database", 0)),
            username=configuration.get("username"),
            password=self._resolve_secret(record.secret_reference),
            socket_timeout=float(configuration.get("timeout", 5)),
            ssl=bool(configuration.get("ssl", False)),
            decode_responses=True,
        )
        try:
            client.ping()
            return {"status": "online", "message": "Redis 连接成功"}
        except redis.RedisError as error:
            raise RuntimeError(f"Redis 连接失败：{error}") from error
        finally:
            client.close()

    def _discover_redis(self, key: str, record: DataSourceRecord) -> dict[str, Any]:
        import redis

        configuration = record.configuration
        client = redis.Redis(
            host=str(configuration.get("host", "127.0.0.1")),
            port=int(configuration.get("port", 6379)),
            db=int(configuration.get("database", 0)),
            username=configuration.get("username"),
            password=self._resolve_secret(record.secret_reference),
            socket_timeout=float(configuration.get("timeout", 5)),
            ssl=bool(configuration.get("ssl", False)),
            decode_responses=True,
        )
        try:
            limit = min(int(configuration.get("scan_limit", 100)), 1000)
            rows = []
            for item in client.scan_iter(match=str(configuration.get("pattern", "*")), count=100):
                rows.append({"name": item, "type": client.type(item)})
                if len(rows) >= limit:
                    break
            return {"source": key, "tables": rows, "kind": "keyspace"}
        except redis.RedisError as error:
            raise ValueError(f"Redis 发现失败：{error}") from error
        finally:
            client.close()

    def _elasticsearch_client(self, record: DataSourceRecord):
        from elasticsearch import Elasticsearch

        endpoint = str(record.configuration.get("endpoint", ""))
        if urlparse(endpoint).scheme not in {"http", "https"}:
            raise ValueError("Elasticsearch 需要 http(s) endpoint")
        secret = self._resolve_secret(record.secret_reference)
        options: dict[str, Any] = {"request_timeout": float(record.configuration.get("timeout", 8))}
        if secret:
            if record.configuration.get("username"):
                options["basic_auth"] = (record.configuration["username"], secret)
            else:
                options["api_key"] = secret
        return Elasticsearch(endpoint, **options)

    def _test_elasticsearch(self, record: DataSourceRecord) -> dict[str, Any]:
        client = self._elasticsearch_client(record)
        try:
            info = client.info()
            version = info.get("version", {}).get("number", "unknown")
            return {"status": "online", "message": f"Elasticsearch 连接成功 · {version}"}
        except Exception as error:
            raise RuntimeError(f"Elasticsearch 连接失败：{error}") from error
        finally:
            client.close()

    def _discover_elasticsearch(self, key: str, record: DataSourceRecord) -> dict[str, Any]:
        client = self._elasticsearch_client(record)
        try:
            mappings = client.indices.get_mapping(index=record.configuration.get("index", "*"))
            tables = []
            for index_name, mapping in mappings.items():
                properties = mapping.get("mappings", {}).get("properties", {})
                tables.append(
                    {
                        "name": index_name,
                        "columns": [
                            {"name": name, "type": definition.get("type", "object")}
                            for name, definition in properties.items()
                        ],
                    }
                )
            return {"source": key, "tables": tables}
        except Exception as error:
            raise ValueError(f"Elasticsearch 发现失败：{error}") from error
        finally:
            client.close()

    def _neo4j_driver(self, record: DataSourceRecord):
        from neo4j import GraphDatabase

        uri = str(record.configuration.get("uri", record.configuration.get("endpoint", "")))
        if urlparse(uri).scheme not in {"neo4j", "neo4j+s", "bolt", "bolt+s"}:
            raise ValueError("Neo4j 需要 neo4j:// 或 bolt:// URI")
        username = str(record.configuration.get("username", "neo4j"))
        password = self._resolve_secret(record.secret_reference)
        return GraphDatabase.driver(uri, auth=(username, password) if password else None)

    def _test_neo4j(self, record: DataSourceRecord) -> dict[str, Any]:
        driver = self._neo4j_driver(record)
        try:
            driver.verify_connectivity()
            return {"status": "online", "message": "Neo4j 连接成功"}
        except Exception as error:
            raise RuntimeError(f"Neo4j 连接失败：{error}") from error
        finally:
            driver.close()

    def _discover_neo4j(self, key: str, record: DataSourceRecord) -> dict[str, Any]:
        driver = self._neo4j_driver(record)
        database = record.configuration.get("database")
        try:
            records, _, _ = driver.execute_query(
                "CALL db.labels() YIELD label RETURN label ORDER BY label",
                database_=database,
            )
            relations, _, _ = driver.execute_query(
                "CALL db.relationshipTypes() YIELD relationshipType "
                "RETURN relationshipType ORDER BY relationshipType",
                database_=database,
            )
            return {
                "source": key,
                "tables": [{"name": item["label"], "kind": "node_label"} for item in records],
                "relations": [item["relationshipType"] for item in relations],
            }
        except Exception as error:
            raise ValueError(f"Neo4j 发现失败：{error}") from error
        finally:
            driver.close()

    def _qdrant_client(self, record: DataSourceRecord):
        from qdrant_client import QdrantClient

        endpoint = str(record.configuration.get("endpoint", ""))
        if not endpoint:
            raise ValueError("Qdrant 需要 endpoint")
        return QdrantClient(
            url=endpoint,
            api_key=self._resolve_secret(record.secret_reference),
            timeout=float(record.configuration.get("timeout", 8)),
        )

    def _test_qdrant(self, record: DataSourceRecord) -> dict[str, Any]:
        client = self._qdrant_client(record)
        try:
            collections = client.get_collections().collections
            return {"status": "online", "message": f"Qdrant 连接成功 · {len(collections)} 个集合"}
        except Exception as error:
            raise RuntimeError(f"Qdrant 连接失败：{error}") from error
        finally:
            client.close()

    def _discover_qdrant(self, key: str, record: DataSourceRecord) -> dict[str, Any]:
        client = self._qdrant_client(record)
        try:
            tables = []
            for collection in client.get_collections().collections:
                info = client.get_collection(collection.name)
                tables.append(
                    {
                        "name": collection.name,
                        "kind": "vector_collection",
                        "points_count": info.points_count,
                        "vectors": str(info.config.params.vectors),
                    }
                )
            return {"source": key, "tables": tables}
        except Exception as error:
            raise ValueError(f"Qdrant 发现失败：{error}") from error
        finally:
            client.close()

    def _test_mqtt(self, record: DataSourceRecord) -> dict[str, Any]:
        import threading

        import paho.mqtt.client as mqtt

        configuration = record.configuration
        connected = threading.Event()
        failure: list[str] = []
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        username = configuration.get("username")
        secret = self._resolve_secret(record.secret_reference)
        if username:
            client.username_pw_set(str(username), secret)
        if configuration.get("tls"):
            client.tls_set()

        def on_connect(client, userdata, flags, reason_code, properties):
            if reason_code == 0:
                connected.set()
            else:
                failure.append(str(reason_code))
                connected.set()

        client.on_connect = on_connect
        try:
            client.connect(
                str(configuration.get("host", "127.0.0.1")),
                int(configuration.get("port", 1883)),
                keepalive=int(configuration.get("keepalive", 30)),
            )
            client.loop_start()
            if not connected.wait(float(configuration.get("timeout", 8))):
                raise RuntimeError("MQTT 连接超时")
            if failure:
                raise RuntimeError(f"MQTT Broker 拒绝连接：{failure[0]}")
            return {"status": "online", "message": "MQTT Broker 连接成功"}
        except Exception as error:
            raise RuntimeError(f"MQTT 连接失败：{error}") from error
        finally:
            client.loop_stop()
            client.disconnect()

    @staticmethod
    def _discover_mqtt(key: str, record: DataSourceRecord) -> dict[str, Any]:
        topics = record.configuration.get("topics", [])
        if not isinstance(topics, list) or not topics:
            raise ValueError("MQTT Schema 发现需要在配置中声明 topics")
        tables = []
        for topic in topics:
            if isinstance(topic, str):
                tables.append({"name": topic, "columns": [{"name": "payload", "type": "json"}]})
            elif isinstance(topic, dict) and topic.get("name"):
                schema = topic.get("schema", {})
                tables.append(
                    {
                        "name": str(topic["name"]),
                        "columns": [
                            {"name": str(name), "type": str(data_type)}
                            for name, data_type in schema.items()
                        ],
                    }
                )
        return {"source": key, "tables": tables, "kind": "mqtt_topics"}

    def _test_opcua(self, record: DataSourceRecord) -> dict[str, Any]:
        async def probe() -> str:
            from asyncua import Client

            endpoint = str(record.configuration.get("endpoint", ""))
            if urlparse(endpoint).scheme not in {"opc.tcp", "https"}:
                raise ValueError("OPC UA 需要 opc.tcp:// endpoint")
            client = Client(endpoint, timeout=float(record.configuration.get("timeout", 8)))
            if record.configuration.get("username"):
                client.set_user(str(record.configuration["username"]))
                secret = self._resolve_secret(record.secret_reference)
                if secret:
                    client.set_password(secret)
            await client.connect()
            try:
                return str(await client.nodes.server_state.read_value())
            finally:
                await client.disconnect()

        try:
            state = asyncio.run(probe())
            return {"status": "online", "message": f"OPC UA 连接成功 · {state}"}
        except Exception as error:
            raise RuntimeError(f"OPC UA 连接失败：{error}") from error

    def _discover_opcua(self, key: str, record: DataSourceRecord) -> dict[str, Any]:
        async def browse() -> list[dict[str, Any]]:
            from asyncua import Client

            endpoint = str(record.configuration.get("endpoint", ""))
            client = Client(endpoint, timeout=float(record.configuration.get("timeout", 8)))
            if record.configuration.get("username"):
                client.set_user(str(record.configuration["username"]))
                secret = self._resolve_secret(record.secret_reference)
                if secret:
                    client.set_password(secret)
            await client.connect()
            try:
                configured = record.configuration.get("node_ids", [])
                nodes = (
                    [client.get_node(node_id) for node_id in configured]
                    if configured
                    else await client.nodes.objects.get_children()
                )
                tables = []
                for node in nodes[: int(record.configuration.get("browse_limit", 100))]:
                    tables.append(
                        {
                            "name": (await node.read_display_name()).Text,
                            "node_id": node.nodeid.to_string(),
                            "kind": str(await node.read_node_class()),
                        }
                    )
                return tables
            finally:
                await client.disconnect()

        try:
            return {"source": key, "tables": asyncio.run(browse()), "kind": "opcua_nodes"}
        except Exception as error:
            raise ValueError(f"OPC UA 发现失败：{error}") from error

    @staticmethod
    def _discover_file(key: str, configuration: dict[str, Any]) -> dict[str, Any]:
        import duckdb

        path = DataSourceService._required_path(configuration)
        suffix = path.suffix.casefold()
        connection = duckdb.connect(":memory:")
        try:
            if suffix in {".csv", ".tsv"}:
                relation = connection.from_csv_auto(str(path))
            elif suffix in {".json", ".jsonl", ".ndjson"}:
                relation = connection.read_json(str(path))
            elif suffix == ".parquet":
                relation = connection.read_parquet(str(path))
            else:
                raise ValueError("文件发现仅支持 CSV、TSV、JSON、JSONL、Parquet")
            return {
                "source": key,
                "tables": [
                    {
                        "name": path.stem,
                        "columns": [
                            {"name": name, "type": str(data_type)}
                            for name, data_type in zip(
                                relation.columns, relation.types, strict=True
                            )
                        ],
                    }
                ],
            }
        finally:
            connection.close()

    @staticmethod
    def _required_path(configuration: dict[str, Any]) -> Path:
        raw_path = configuration.get("path")
        if not raw_path:
            raise ValueError("连接配置缺少 path")
        path = Path(str(raw_path)).expanduser().resolve()
        if not path.is_file():
            raise ValueError(f"文件不存在：{path}")
        return path

    @staticmethod
    def _secret_status(reference: str | None) -> str:
        if not reference:
            return "尚未配置凭证引用"
        if not reference.startswith("env://"):
            return "凭证引用格式应为 env://VARIABLE"
        variable = reference.removeprefix("env://")
        return "凭证可用" if os.getenv(variable) else f"环境变量 {variable} 尚未设置"

    @staticmethod
    def _resolve_secret(reference: str | None) -> str | None:
        if not reference:
            return None
        if not reference.startswith("env://"):
            raise ValueError("数据源凭证仅接受 env://VARIABLE 引用")
        variable = reference.removeprefix("env://")
        value = os.getenv(variable)
        if not value:
            raise ValueError(f"环境变量 {variable} 尚未设置")
        return value

    @classmethod
    def _contains_secret(cls, value: Any, key: str = "") -> bool:
        secret_keys = {"password", "token", "secret", "api_key", "apikey", "authorization"}
        if key.casefold() in secret_keys:
            return True
        if isinstance(value, dict):
            return any(
                cls._contains_secret(child, str(child_key)) for child_key, child in value.items()
            )
        if isinstance(value, list):
            return any(cls._contains_secret(child) for child in value)
        if isinstance(value, str) and key.casefold() in {"url", "endpoint"}:
            return urlparse(value).password is not None
        return False

    @staticmethod
    def _serialize(record: DataSourceRecord) -> dict[str, Any]:
        return {
            "key": record.key,
            "name": record.name,
            "connector_type": record.connector_type,
            "configuration": record.configuration,
            "secret_reference": record.secret_reference,
            "enabled": record.enabled,
            "status": record.status,
            "last_tested_at": record.last_tested_at.isoformat() if record.last_tested_at else None,
        }
