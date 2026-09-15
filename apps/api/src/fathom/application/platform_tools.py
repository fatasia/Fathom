from __future__ import annotations

import csv
import io
import json
import sqlite3
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import sqlglot
import yaml
from fathom.adapters.storage.database import (
    EventRecord,
    MetricObservationRecord,
    ObjectInstanceRecord,
    SqlTemplateRecord,
    SqlTemplateVersionRecord,
)
from fathom.config import Settings
from fathom.domains.semantics.models import DomainContract
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session, sessionmaker
from sqlglot import exp


class SqlTemplateInput(BaseModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_.-]+$")
    label: str = Field(min_length=2, max_length=160)
    description: str = ""
    dialect: str = "sqlite"
    sql_text: str = Field(min_length=8)
    parameters: list[str] = Field(default_factory=list)
    published: bool = False


class SqlPreviewRequest(BaseModel):
    parameters: dict[str, Any] = Field(default_factory=dict)
    limit: int = Field(default=100, ge=1, le=500)


class RestoreRequest(BaseModel):
    confirmation: str


class SemanticImportRequest(BaseModel):
    content: str
    apply: bool = False


class SqlTemplateService:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def list(self) -> list[dict[str, Any]]:
        with self._session_factory() as session:
            records = session.scalars(
                select(SqlTemplateRecord).order_by(SqlTemplateRecord.key)
            ).all()
            return [self._serialize(record) for record in records]

    def save(self, payload: SqlTemplateInput) -> dict[str, Any]:
        validation = self.validate(payload.sql_text, payload.dialect, payload.parameters)
        if not validation["safe"]:
            raise ValueError("; ".join(validation["errors"]))
        with self._session_factory() as session:
            record = session.get(SqlTemplateRecord, payload.key)
            values = payload.model_dump()
            values["updated_at"] = datetime.now(UTC)
            if record is None:
                record = SqlTemplateRecord(**values)
                session.add(record)
            else:
                for key, value in values.items():
                    setattr(record, key, value)
            session.flush()
            version = (
                session.scalar(
                    select(func.max(SqlTemplateVersionRecord.version)).where(
                        SqlTemplateVersionRecord.template_key == payload.key
                    )
                )
                or 0
            ) + 1
            session.add(
                SqlTemplateVersionRecord(
                    template_key=payload.key,
                    version=version,
                    snapshot=self._serialize(record),
                    created_at=datetime.now(UTC),
                )
            )
            session.commit()
            session.refresh(record)
            return self._serialize(record)

    def versions(self, template_key: str) -> list[dict[str, Any]]:
        with self._session_factory() as session:
            records = session.scalars(
                select(SqlTemplateVersionRecord)
                .where(SqlTemplateVersionRecord.template_key == template_key)
                .order_by(SqlTemplateVersionRecord.version.desc())
            ).all()
            return [
                {
                    "version": record.version,
                    "created_at": record.created_at.isoformat(),
                    "snapshot": record.snapshot,
                }
                for record in records
            ]

    def restore_version(self, template_key: str, version: int) -> dict[str, Any]:
        with self._session_factory() as session:
            record = session.scalar(
                select(SqlTemplateVersionRecord).where(
                    SqlTemplateVersionRecord.template_key == template_key,
                    SqlTemplateVersionRecord.version == version,
                )
            )
            if record is None:
                raise LookupError(f"{template_key}@{version}")
            payload = SqlTemplateInput.model_validate(record.snapshot)
        return self.save(payload)

    def delete(self, template_key: str) -> None:
        with self._session_factory() as session:
            record = session.get(SqlTemplateRecord, template_key)
            if record is None:
                raise LookupError(template_key)
            session.delete(record)
            session.execute(
                delete(SqlTemplateVersionRecord).where(
                    SqlTemplateVersionRecord.template_key == template_key
                )
            )
            session.commit()

    def preview(
        self,
        template_key: str,
        parameters: dict[str, Any],
        limit: int = 100,
    ) -> dict[str, Any]:
        limit = min(max(limit, 1), 500)
        with self._session_factory() as session:
            record = session.get(SqlTemplateRecord, template_key)
            if record is None:
                raise LookupError(template_key)
            validation = self.validate(record.sql_text, record.dialect, record.parameters)
            if not validation["safe"]:
                raise ValueError("; ".join(validation["errors"]))
            missing = [name for name in record.parameters if name not in parameters]
            if missing:
                raise ValueError(f"缺少参数：{', '.join(missing)}")
            if record.dialect != "sqlite":
                raise ValueError("内置预览当前执行 SQLite 模板；其他方言由对应数据源连接器执行")
            sql = record.sql_text.strip().rstrip(";")
            statement = text(f"SELECT * FROM ({sql}) AS __fathom_preview LIMIT :__fathom_limit")
            result = session.execute(statement, {**parameters, "__fathom_limit": limit})
            columns = list(result.keys())
            rows = [dict(row._mapping) for row in result.fetchall()]
            return {
                "template_key": template_key,
                "columns": columns,
                "rows": rows,
                "row_count": len(rows),
                "limit": limit,
                "executed_at": datetime.now(UTC).isoformat(),
            }

    @staticmethod
    def validate(sql_text: str, dialect: str, parameters: list[str]) -> dict[str, Any]:
        errors: list[str] = []
        try:
            statements = sqlglot.parse(sql_text, read=dialect)
        except sqlglot.errors.ParseError as error:
            return {"valid": False, "safe": False, "errors": [str(error)], "tables": []}
        if len(statements) != 1:
            errors.append("模板必须只包含一条 SQL 语句")
        expression = statements[0]
        forbidden = tuple(
            node_type
            for node_type in [
                getattr(exp, "Insert", None),
                getattr(exp, "Update", None),
                getattr(exp, "Delete", None),
                getattr(exp, "Drop", None),
                getattr(exp, "Create", None),
                getattr(exp, "Alter", None),
                getattr(exp, "Command", None),
            ]
            if node_type is not None
        )
        if forbidden and any(expression.find(node_type) for node_type in forbidden):
            errors.append("FATHOM SQL 模板只允许只读 SELECT/CTE")
        normalized = sql_text.casefold()
        missing_parameters = [
            name for name in parameters if f":{name.casefold()}" not in normalized
        ]
        if missing_parameters:
            errors.append(f"声明但未使用的参数：{', '.join(missing_parameters)}")
        tables = sorted({table.name for table in expression.find_all(exp.Table)})
        return {
            "valid": not errors,
            "safe": not errors,
            "errors": errors,
            "tables": tables,
            "normalized_sql": expression.sql(dialect=dialect, pretty=True),
        }

    @staticmethod
    def _serialize(record: SqlTemplateRecord) -> dict[str, Any]:
        return {
            "key": record.key,
            "label": record.label,
            "description": record.description,
            "dialect": record.dialect,
            "sql_text": record.sql_text,
            "parameters": record.parameters,
            "published": record.published,
            "updated_at": record.updated_at.isoformat(),
        }


class BackupService:
    def __init__(self, app_settings: Settings) -> None:
        self._settings = app_settings
        self._backup_directory = app_settings.backup_directory.resolve()
        self._backup_directory.mkdir(parents=True, exist_ok=True)

    def create(self, reason: str = "manual") -> dict[str, Any]:
        database_path = self._database_path()
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        backup_name = f"fathom-{timestamp}.zip"
        target = (self._backup_directory / backup_name).resolve()
        self._assert_in_backup_directory(target)
        with tempfile.TemporaryDirectory(prefix="fathom-backup-") as temp_directory:
            snapshot = Path(temp_directory) / "fathom.db"
            source = sqlite3.connect(database_path)
            destination = sqlite3.connect(snapshot)
            try:
                source.backup(destination)
            finally:
                destination.close()
                source.close()
            manifest = {
                "format": "fathom-backup/v1",
                "created_at": datetime.now(UTC).isoformat(),
                "reason": reason,
                "storage_profile": self._settings.storage_profile,
            }
            with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.write(snapshot, "database/fathom.db")
                archive.writestr(
                    "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2)
                )
                for semantic_file in self._settings.semantic_directory.glob("**/*.yaml"):
                    archive.write(
                        semantic_file,
                        "semantic/"
                        + semantic_file.relative_to(self._settings.semantic_directory).as_posix(),
                    )
        return self.describe(target)

    def list(self) -> list[dict[str, Any]]:
        return [
            self.describe(path)
            for path in sorted(self._backup_directory.glob("*.zip"), reverse=True)
        ]

    def resolve(self, name: str) -> Path:
        if Path(name).name != name:
            raise ValueError("Invalid backup name")
        path = (self._backup_directory / name).resolve()
        self._assert_in_backup_directory(path)
        if not path.is_file():
            raise FileNotFoundError(name)
        return path

    def restore(self, name: str, confirmation: str) -> dict[str, Any]:
        if confirmation != "RESTORE":
            raise ValueError("恢复操作需要 confirmation=RESTORE")
        backup = self.resolve(name)
        protective = self.create(reason=f"before-restore:{name}")
        with tempfile.TemporaryDirectory(prefix="fathom-restore-") as temp_directory:
            with zipfile.ZipFile(backup) as archive:
                if "database/fathom.db" not in archive.namelist():
                    raise ValueError("备份缺少 database/fathom.db")
                archive.extract("database/fathom.db", temp_directory)
            snapshot_path = Path(temp_directory) / "database" / "fathom.db"
            snapshot = sqlite3.connect(snapshot_path)
            target = sqlite3.connect(self._database_path())
            try:
                snapshot.backup(target)
            finally:
                target.close()
                snapshot.close()
        return {"restored": name, "protective_backup": protective["name"]}

    def describe(self, path: Path) -> dict[str, Any]:
        stat = path.stat()
        return {
            "name": path.name,
            "size_bytes": stat.st_size,
            "updated_at": datetime.fromtimestamp(stat.st_mtime, UTC).isoformat(),
        }

    def _database_path(self) -> Path:
        if not self._settings.database_url.startswith("sqlite:///"):
            raise RuntimeError("Lite backup currently requires SQLite")
        return Path(self._settings.database_url.removeprefix("sqlite:///")).resolve()

    def _assert_in_backup_directory(self, path: Path) -> None:
        if path.parent != self._backup_directory:
            raise ValueError("Backup path escapes configured directory")


def inspect_import(filename: str, content: bytes) -> dict[str, Any]:
    suffix = Path(filename).suffix.casefold()
    if len(content) > 20 * 1024 * 1024:
        raise ValueError("预检文件不能超过 20 MB")
    if suffix == ".csv":
        text = content.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
        rows = [row for _, row in zip(range(20), reader, strict=False)]
        return {"format": "csv", "columns": reader.fieldnames or [], "rows": rows}
    if suffix in {".json", ".jsonl"}:
        text = content.decode("utf-8-sig")
        if suffix == ".jsonl":
            parsed = [json.loads(line) for line in text.splitlines()[:20] if line.strip()]
        else:
            parsed = json.loads(text)
        rows = parsed if isinstance(parsed, list) else [parsed]
        return {
            "format": suffix.removeprefix("."),
            "columns": sorted({key for row in rows[:20] if isinstance(row, dict) for key in row}),
            "rows": rows[:20],
        }
    if suffix in {".yaml", ".yml"}:
        parsed = yaml.safe_load(content.decode("utf-8-sig"))
        if isinstance(parsed, dict) and ("semantic_models" in parsed or "metrics" in parsed):
            candidate = convert_dbt_semantic_layer(parsed)
            return {
                "format": "dbt-semantic-layer-yaml",
                "semantic_models": len(parsed.get("semantic_models", [])),
                "metrics": len(parsed.get("metrics", [])),
                "candidate_contract": candidate,
                "next_step": "review_candidate_contract",
            }
        contract = DomainContract.model_validate(parsed)
        return {
            "format": "fathom-semantic-yaml",
            "domain": contract.domain,
            "version": contract.version,
            "assets": len(contract.assets),
            "relations": len(contract.relations),
        }
    raise ValueError("支持 CSV、JSON、JSONL、YAML 导入预检")


def convert_dbt_semantic_layer(document: dict[str, Any]) -> dict[str, Any]:
    """Convert dbt/MetricFlow semantics into a reviewable FATHOM semantic candidate."""
    semantic_models = document.get("semantic_models", [])
    metrics = document.get("metrics", [])
    if not isinstance(semantic_models, list) or not isinstance(metrics, list):
        raise ValueError("dbt semantic_models 与 metrics 必须是列表")
    owner = str(document.get("meta", {}).get("owner", "unassigned"))
    domain = str(document.get("meta", {}).get("domain", "dbt_import"))
    assets: list[dict[str, Any]] = []

    for model in semantic_models:
        if not isinstance(model, dict) or not model.get("name"):
            raise ValueError("每个 dbt semantic_model 都需要 name")
        model_name = str(model["name"])
        assets.append(
            {
                "key": model_name,
                "kind": "object",
                "label": str(model.get("label", model_name.replace("_", " ").title())),
                "description": str(model.get("description", "")),
                "domain": domain,
                "owner": owner,
                "source": str(model.get("model", "")),
                "metadata": {"dbt_semantic_model": model_name, "status": "candidate"},
            }
        )
        for collection, subtype in (("entities", "entity"), ("dimensions", "dimension")):
            for field in model.get(collection, []):
                if not isinstance(field, dict) or not field.get("name"):
                    continue
                field_name = str(field["name"])
                assets.append(
                    {
                        "key": f"{model_name}.{field_name}",
                        "kind": "attribute",
                        "label": str(field.get("label", field_name.replace("_", " ").title())),
                        "description": str(field.get("description", "")),
                        "domain": domain,
                        "owner": owner,
                        "source": str(field.get("expr", field_name)),
                        "metadata": {
                            "dbt_type": subtype,
                            "object": model_name,
                            "type": field.get("type"),
                            "status": "candidate",
                        },
                    }
                )
        for measure in model.get("measures", []):
            if not isinstance(measure, dict) or not measure.get("name"):
                continue
            measure_name = str(measure["name"])
            expression = str(measure.get("expr", measure_name))
            aggregation = str(measure.get("agg", "sum"))
            assets.append(
                {
                    "key": measure_name,
                    "kind": "metric",
                    "label": str(measure.get("label", measure_name.replace("_", " ").title())),
                    "description": str(measure.get("description", "")),
                    "domain": domain,
                    "owner": owner,
                    "expression": f"{aggregation}({expression})",
                    "metadata": {"dbt_measure": measure_name, "status": "candidate"},
                }
            )

    for metric in metrics:
        if not isinstance(metric, dict) or not metric.get("name"):
            continue
        metric_name = str(metric["name"])
        params = metric.get("type_params", {})
        expression = str(
            params.get("expr") or params.get("measure") or metric.get("type", "derived")
        )
        assets.append(
            {
                "key": metric_name,
                "kind": "metric",
                "label": str(metric.get("label", metric_name.replace("_", " ").title())),
                "description": str(metric.get("description", "")),
                "domain": domain,
                "owner": owner,
                "expression": expression,
                "metadata": {
                    "dbt_metric_type": metric.get("type"),
                    "type_params": params,
                    "status": "candidate",
                },
            }
        )

    return {
        "name": f"dbt_{domain}",
        "label": f"dbt 导入 · {domain}",
        "version": "candidate-1",
        "domain": domain,
        "owner": owner,
        "assets": assets,
        "relations": [],
    }


def export_dataset_csv(
    session_factory: sessionmaker[Session], dataset: str, limit: int = 100_000
) -> bytes:
    definitions = {
        "objects": (
            ObjectInstanceRecord,
            [
                "object_id",
                "object_type",
                "label",
                "source_key",
                "attributes",
                "state",
                "updated_at",
            ],
        ),
        "metrics": (
            MetricObservationRecord,
            ["id", "metric_key", "object_id", "observed_at", "value", "dimensions"],
        ),
        "events": (
            EventRecord,
            ["id", "event_type", "object_id", "occurred_at", "duration_minutes", "payload"],
        ),
    }
    if dataset not in definitions:
        raise ValueError("可导出的数据集：objects、metrics、events")
    model, columns = definitions[dataset]
    limit = min(max(limit, 1), 100_000)
    with session_factory() as session:
        records = session.scalars(select(model).limit(limit)).all()
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=columns)
    writer.writeheader()
    for record in records:
        row = {}
        for column in columns:
            value = getattr(record, column)
            if isinstance(value, (dict, list)):
                value = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
            elif isinstance(value, datetime):
                value = value.isoformat()
            row[column] = value
        writer.writerow(row)
    return output.getvalue().encode("utf-8-sig")
