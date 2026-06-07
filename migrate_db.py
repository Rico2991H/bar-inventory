"""Add any missing columns to the existing database without wiping data.

Model-driven: reflects every SQLModel table and ALTERs each existing table
to add columns the model defines but the DB is missing. New tables are created
by the backend's create_db() on startup; this script only patches drift in
tables that already exist (SQLite never auto-adds columns to existing tables).

Run while the backend is stopped:
    python migrate_db.py
"""
import sqlite3

# Import the models so their tables register on SQLModel.metadata
from sqlmodel import SQLModel
from sqlalchemy.dialects import sqlite as sqlite_dialect
import backend.models.product  # noqa: F401  (registers all tables)

DB_PATH = "inventory.db"


def sqlite_type(column) -> str:
    """Render a SQLAlchemy column type as its SQLite column definition."""
    try:
        return column.type.compile(dialect=sqlite_dialect.dialect())
    except Exception:
        return "TEXT"


def main():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    existing_tables = {
        r[0] for r in cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }

    added_total = 0
    for table_name, table in SQLModel.metadata.tables.items():
        if table_name not in existing_tables:
            # New table — backend create_db() will create it on startup.
            print(f"{table_name}: not in DB yet (created on backend startup)")
            continue

        db_cols = {
            row[1] for row in cur.execute(
                f'PRAGMA table_info("{table_name}")'
            ).fetchall()
        }
        for col in table.columns:
            if col.name in db_cols:
                continue
            # Added columns must be nullable / have no NOT NULL without default.
            coltype = sqlite_type(col)
            cur.execute(
                f'ALTER TABLE "{table_name}" ADD COLUMN "{col.name}" {coltype}'
            )
            print(f"  + {table_name}.{col.name} ({coltype})")
            added_total += 1

    conn.commit()
    conn.close()
    if added_total:
        print(f"\nMigration complete — added {added_total} column(s).")
    else:
        print("\nMigration complete — schema already up to date.")


if __name__ == "__main__":
    main()
