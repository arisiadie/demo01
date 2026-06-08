from __future__ import annotations

import pathlib
import sys

from sqlalchemy import inspect, text


ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.database import engine


def main() -> None:
    inspector = inspect(engine)
    tables = sorted(inspector.get_table_names())
    print("tables", len(tables), tables)
    with engine.connect() as conn:
        print("database", conn.execute(text("SELECT DATABASE()")).scalar())
        print({table: conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar() for table in tables})
    foreign_keys = {
        table: [
            (fk["constrained_columns"], fk["referred_table"], fk["referred_columns"])
            for fk in inspector.get_foreign_keys(table)
        ]
        for table in tables
    }
    print({table: rows for table, rows in foreign_keys.items() if rows})


if __name__ == "__main__":
    main()
