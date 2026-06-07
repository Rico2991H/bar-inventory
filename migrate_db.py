"""Add missing columns to the existing database without wiping data."""
import sqlite3

conn = sqlite3.connect("inventory.db")
cur = conn.cursor()

# --- order table ---
cur.execute("PRAGMA table_info([order])")
order_cols = [row[1] for row in cur.fetchall()]
print("order columns:", order_cols)

if "rating" not in order_cols:
    cur.execute("ALTER TABLE [order] ADD COLUMN rating INTEGER")
    print("  + added: rating")
if "rating_note" not in order_cols:
    cur.execute("ALTER TABLE [order] ADD COLUMN rating_note TEXT")
    print("  + added: rating_note")

# --- verify other tables exist ---
cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [r[0] for r in cur.fetchall()]
print("All tables:", tables)

conn.commit()
conn.close()
print("Migration complete.")
