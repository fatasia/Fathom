from __future__ import annotations

import argparse
import os
from datetime import UTC, datetime, timedelta

import psycopg


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create isolated PostgreSQL facts for the FATHOM semantic runtime demo."
    )
    parser.add_argument("--host", default=os.getenv("FATHOM_DEMO_PG_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("FATHOM_DEMO_PG_PORT", "5432")))
    parser.add_argument("--user", default=os.getenv("FATHOM_DEMO_PG_USER", "postgres"))
    parser.add_argument("--database", default=os.getenv("FATHOM_DEMO_PG_DATABASE", "postgres"))
    parser.add_argument("--schema", default="fathom_p0p3_demo")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    password = os.getenv("FATHOM_DEMO_PG_PASSWORD")
    if not password:
        raise SystemExit("Set FATHOM_DEMO_PG_PASSWORD; credentials are never stored in files.")
    if not args.schema.replace("_", "").isalnum() or not args.schema[0].isalpha():
        raise SystemExit("--schema must be a safe SQL identifier")
    today = datetime.now(UTC).replace(hour=8, minute=0, second=0, microsecond=0)
    yesterday = today - timedelta(days=1)
    previous = today - timedelta(days=2)
    values = {
        "order_fulfillment_rate": (93.6, 87.4),
        "oee": (84.7, 78.2),
        "actual_output": (936.0, 874.0),
        "planned_output": (1000.0, 1000.0),
        "downtime_minutes": (42.0, 96.0),
    }
    rows = [
        (metric, "line_01", observed_at, value, "day", "line_01")
        for metric, pair in values.items()
        for observed_at, value in ((previous, pair[0]), (yesterday, pair[1]))
    ]
    with psycopg.connect(
        host=args.host,
        port=args.port,
        user=args.user,
        password=password,
        dbname=args.database,
    ) as connection:
        with connection.cursor() as cursor:
            cursor.execute(f'CREATE SCHEMA IF NOT EXISTS "{args.schema}"')
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS "{args.schema}".metric_observations (
                    metric_key text NOT NULL,
                    object_id text NOT NULL,
                    observed_at timestamptz NOT NULL,
                    value double precision NOT NULL,
                    shift text NOT NULL,
                    production_line text NOT NULL,
                    PRIMARY KEY (metric_key, object_id, observed_at, shift)
                )
                """
            )
            cursor.executemany(
                f"""
                INSERT INTO "{args.schema}".metric_observations
                    (metric_key, object_id, observed_at, value, shift, production_line)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (metric_key, object_id, observed_at, shift)
                DO UPDATE SET
                    value = EXCLUDED.value,
                    production_line = EXCLUDED.production_line
                """,
                rows,
            )
        connection.commit()
        count = connection.execute(
            f'SELECT count(*) FROM "{args.schema}".metric_observations'
        ).fetchone()[0]
    print(
        f"Seeded {count} rows in {args.database}.{args.schema}.metric_observations "
        f"at {args.host}:{args.port}"
    )


if __name__ == "__main__":
    main()

