"""One-shot migration: widen big-JSON TEXT columns to LONGTEXT on MySQL.

Real LLM output can exceed MySQL TEXT's 64KB limit, causing
(1406, "Data too long for column 'result_json'") on consultation persist.
SQLAlchemy's create_all only creates missing tables — it never alters existing
columns — so run this once against the live MySQL database after deploying the
entities.py change.

Usage (from project root, with the same env that runs the app):
    python -m scripts.widen_longtext_columns
Safe to run multiple times (ALTER ... MODIFY is idempotent for type widening).
SQLite databases are skipped (TEXT there is already unlimited).
"""
from __future__ import annotations

from sqlalchemy import text

from app.core.database import engine

# table -> list of (column, not_null) to widen to LONGTEXT.
# not_null preserves the ORM's nullability so MODIFY doesn't silently drop it.
TARGETS = {
    "consultations": [("result_json", True), ("sources_json", True), ("summary", True)],
    "agent_runs": [("trace_json", True)],
    "evaluation_runs": [("summary_json", True)],
    "evaluation_results": [("response_json", True), ("failures_json", True)],
}


def main() -> None:
    if engine.dialect.name != "mysql":
        print(f"Dialect is {engine.dialect.name!r}, not mysql — nothing to do.")
        return

    with engine.begin() as conn:
        for table, columns in TARGETS.items():
            for column, not_null in columns:
                null_clause = "NOT NULL" if not_null else "NULL"
                sql = f"ALTER TABLE `{table}` MODIFY `{column}` LONGTEXT {null_clause}"
                try:
                    conn.execute(text(sql))
                    print(f"OK   {table}.{column} -> LONGTEXT {null_clause}")
                except Exception as exc:  # noqa: BLE001 - report and continue
                    print(f"SKIP {table}.{column}: {exc}")

    print("Done.")


if __name__ == "__main__":
    main()
