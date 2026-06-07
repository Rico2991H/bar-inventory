from sqlmodel import SQLModel, create_engine, Session

DATABASE_URL = "sqlite:///./inventory.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})


def _add_missing_columns() -> None:
    """SQLite ALTER TABLE to add any columns that exist in the model but not yet in the DB.
    Safe to run on every startup — skips columns that already exist."""
    import sqlite3
    migrations = {
        "order": [
            ("rating",      "INTEGER"),
            ("rating_note", "TEXT"),
        ],
        "simulationclock": [
            ("sim_start_real", "TEXT"),
        ],
    }
    db_path = DATABASE_URL.replace("sqlite:///", "")
    try:
        conn = sqlite3.connect(db_path)
        cur  = conn.cursor()
        for table, columns in migrations.items():
            cur.execute(f"PRAGMA table_info([{table}])")
            existing = {row[1] for row in cur.fetchall()}
            for col_name, col_type in columns:
                if col_name not in existing:
                    cur.execute(f"ALTER TABLE [{table}] ADD COLUMN {col_name} {col_type}")
        conn.commit()
        conn.close()
    except Exception:
        pass  # DB might not exist yet on first run — create_all handles that


def create_db():
    SQLModel.metadata.create_all(engine)
    _add_missing_columns()


def get_session():
    with Session(engine) as session:
        yield session