#!/usr/bin/env python3
"""Deactivate a tracked product — removes it from price monitoring."""
import sys, json, pathlib, sqlite3
from datetime import datetime

WS = pathlib.Path(__file__).parent


def unfollow(product_id: int) -> str:
    product_id = int(product_id)
    removed_title = None

    # 1. Update tracker_state.json
    state_path = WS / "tracker_state.json"
    if state_path.exists():
        state = json.loads(state_path.read_text())
        for p in state["products"]:
            if p["id"] == product_id:
                p["active"] = False
                removed_title = p["title"]
        state_path.write_text(json.dumps(state, indent=2))
        print(f"[tracker_state.json] set active=False for product {product_id}")

    # 2. Update SQLite DB
    db_path = WS / "price_tracker.db"
    if db_path.exists():
        con = sqlite3.connect(str(db_path))
        rows = con.execute("UPDATE products SET active = 0 WHERE id = ?", (product_id,)).rowcount
        con.commit()
        con.close()
        print(f"[price_tracker.db] updated {rows} row(s) for product {product_id}")

    title = removed_title or f"product {product_id}"
    print(f"Done — '{title}' is no longer tracked.")
    return title


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 unfollow_product.py <product_id>")
        sys.exit(1)
    unfollow(sys.argv[1])
