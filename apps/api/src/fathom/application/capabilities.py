from __future__ import annotations

from typing import Any

from fathom.config import Settings


def detect_capabilities(app_settings: Settings) -> dict[str, Any]:
    capabilities: dict[str, Any] = {
        "storage_profile": app_settings.storage_profile,
        "sqlite": app_settings.database_url.startswith("sqlite"),
        "duckdb": {"enabled": app_settings.enable_duckdb, "available": False},
        "sqlite_vec": {"enabled": app_settings.enable_vector_search, "available": False},
    }
    if app_settings.enable_duckdb:
        try:
            import duckdb

            connection = duckdb.connect(":memory:")
            connection.execute(f"SET memory_limit='{app_settings.duckdb_memory_limit}'")
            connection.execute(f"SET threads={app_settings.duckdb_threads}")
            capabilities["duckdb"].update(
                available=True,
                version=duckdb.__version__,
                memory_limit=app_settings.duckdb_memory_limit,
                threads=app_settings.duckdb_threads,
            )
            connection.close()
        except (ImportError, RuntimeError) as error:
            capabilities["duckdb"]["reason"] = str(error)
    try:
        import sqlite_vec

        capabilities["sqlite_vec"].update(
            available=True,
            version=getattr(sqlite_vec, "__version__", "embedded-extension"),
        )
    except ImportError as error:
        capabilities["sqlite_vec"]["reason"] = str(error)
    return capabilities
