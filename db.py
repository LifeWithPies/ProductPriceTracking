"""SQLite database setup and helpers."""
import sqlite3
import os
from dotenv import load_dotenv

load_dotenv()
DB_PATH = os.getenv("DB_PATH", "./price_tracker.db")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS products (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            url         TEXT NOT NULL,
            retailer_type TEXT NOT NULL,
            title       TEXT,
            image_url   TEXT,
            currency    TEXT DEFAULT 'USD',
            added_at    TEXT NOT NULL,
            active      BOOLEAN DEFAULT 1,
            variant_info TEXT  -- JSON: {size, width, color}
        );

        CREATE TABLE IF NOT EXISTS price_history (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id  INTEGER NOT NULL REFERENCES products(id),
            price       REAL,           -- NULL = out of stock
            in_stock    BOOLEAN DEFAULT 1,
            scraped_at  TEXT NOT NULL,  -- ISO 8601 UTC
            raw_payload TEXT            -- JSON blob
        );
    """)
    conn.commit()
    conn.close()
    print(f"DB initialized at {DB_PATH}")


def add_product(url, retailer_type, title, image_url, currency, variant_info=None):
    from datetime import datetime, timezone
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        """INSERT INTO products (url, retailer_type, title, image_url, currency, added_at, active, variant_info)
           VALUES (?, ?, ?, ?, ?, ?, 1, ?)""",
        (url, retailer_type, title, image_url, currency,
         datetime.now(timezone.utc).isoformat(),
         variant_info)
    )
    product_id = c.lastrowid
    conn.commit()
    conn.close()
    return product_id


def add_price_history(product_id, price, in_stock, raw_payload=None):
    import json
    from datetime import datetime, timezone
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        """INSERT INTO price_history (product_id, price, in_stock, scraped_at, raw_payload)
           VALUES (?, ?, ?, ?, ?)""",
        (product_id, price, int(in_stock),
         datetime.now(timezone.utc).isoformat(),
         json.dumps(raw_payload) if raw_payload else None)
    )
    conn.commit()
    conn.close()


def get_active_products():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM products WHERE active = 1").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_latest_price(product_id):
    conn = get_conn()
    row = conn.execute(
        "SELECT price, in_stock FROM price_history WHERE product_id = ? ORDER BY scraped_at DESC LIMIT 1",
        (product_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_price_history_30d(product_id):
    conn = get_conn()
    rows = conn.execute(
        """SELECT price, scraped_at FROM price_history
           WHERE product_id = ? AND scraped_at >= datetime('now', '-30 days')
           ORDER BY scraped_at ASC""",
        (product_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


if __name__ == "__main__":
    init_db()
