"""Authoritative ORM <-> SQL DDL column-level diff.

Compares every column declared on the SQLAlchemy ORM (Base.metadata, the single
source of truth) against the columns declared in sql/init_oralcare_agentic_rag.sql.
Run ad hoc during phase-2 to find drift; the permanent guard lives in the test suite.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.database import Base
from app.models import entities  # noqa: F401  (register tables on Base.metadata)

SQL_PATH = Path(__file__).resolve().parents[1] / "sql" / "init_oralcare_agentic_rag.sql"


def sql_table_columns(sql: str) -> dict[str, set[str]]:
    tables: dict[str, set[str]] = {}
    for m in re.finditer(
        r"CREATE TABLE IF NOT EXISTS `([^`]+)` \((.*?)\) ENGINE=",
        sql,
        flags=re.S,
    ):
        name, body = m.group(1), m.group(2)
        cols = set(re.findall(r"^\s*`([^`]+)`\s+(?!.*FOREIGN KEY)", body, flags=re.M))
        # exclude key/constraint lines that also start with backtick-less keywords
        cols = {
            c
            for c in cols
            if c not in {"PRIMARY", "UNIQUE", "KEY", "CONSTRAINT", "FOREIGN"}
        }
        tables[name] = cols
    return tables


def main() -> int:
    sql = SQL_PATH.read_text(encoding="utf-8")
    sql_tables = sql_table_columns(sql)

    orm_tables = {
        t.name: {c.name for c in t.columns} for t in Base.metadata.sorted_tables
    }

    problems = 0

    missing_tables = sorted(set(orm_tables) - set(sql_tables))
    if missing_tables:
        problems += 1
        print(f"[TABLE MISSING IN SQL] {missing_tables}")

    extra_tables = sorted(set(sql_tables) - set(orm_tables))
    if extra_tables:
        print(f"[TABLE ONLY IN SQL (not ORM)] {extra_tables}")

    for table in sorted(orm_tables):
        if table not in sql_tables:
            continue
        orm_cols = orm_tables[table]
        sql_cols = sql_tables[table]
        missing = sorted(orm_cols - sql_cols)
        extra = sorted(sql_cols - orm_cols)
        if missing:
            problems += 1
            print(f"[COLUMN MISSING IN SQL] {table}: {missing}")
        if extra:
            print(f"[COLUMN ONLY IN SQL]    {table}: {extra}")

    if problems == 0:
        print(f"OK: all {len(orm_tables)} ORM tables fully covered by SQL (column-level).")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
