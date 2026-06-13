#!/usr/bin/env python3
"""
Price check runner for GitHub Actions.
Source of truth: tracker_state.json (no SQLite dependency).
Run order: price_check_gh.py → gen_dashboard4.py → git commit
"""
import json
import logging
import pathlib
import random
import time
from datetime import datetime, timezone

from scraper import scrape, classify
from notifier import notify_price_drop, notify_back_in_stock

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

WS = pathlib.Path(__file__).parent
STATE_PATH = WS / "tracker_state.json"


def load_state() -> dict:
    return json.loads(STATE_PATH.read_text())


def save_state(state: dict):
    STATE_PATH.write_text(json.dumps(state, indent=2, ensure_ascii=False))


def run():
    state = load_state()
    active_products = [p for p in state["products"] if p.get("active", True)]
    log.info(f"Price check starting — {len(active_products)} active products")

    for product in active_products:
        pid          = product["id"]
        url          = product["url"]
        retailer     = product.get("retailer_type", classify(url))
        variant_info = product.get("variant", {})

        log.info(f"Scraping product {pid}: {product['title'][:50]}")
        try:
            result = scrape(url, retailer, variant_info)
        except Exception as e:
            log.error(f"  Scrape failed: {e}")
            continue

        new_price = result["price"]
        in_stock  = result["in_stock"]
        now       = datetime.now(timezone.utc).isoformat()

        # Previous history for this product (sorted oldest→newest)
        prev_entries = sorted(
            [e for e in state["price_history"] if e["product_id"] == pid],
            key=lambda x: x["scraped_at"],
        )

        # Append new entry
        new_entry = {
            "id":          len(state["price_history"]) + 1,
            "product_id":  pid,
            "price":       new_price,
            "in_stock":    in_stock,
            "scraped_at":  now,
            "raw_payload": json.dumps(result.get("raw", {})),
        }
        state["price_history"].append(new_entry)

        # ---- Price drop detection ----
        priced = [e for e in prev_entries if e.get("price") is not None]
        if priced and new_price is not None:
            prev_price = priced[-1]["price"]
            if new_price < prev_price:
                pct = round((prev_price - new_price) / prev_price * 100, 1)
                log.info(f"  Price drop! {prev_price} → {new_price} ({pct}% off)")
                history_30d = [
                    {"date": e["scraped_at"][:10], "price": e["price"]}
                    for e in priced[-30:]
                ]
                try:
                    notify_price_drop(product, prev_price, new_price, history_30d)
                except Exception as e:
                    log.error(f"  Notification failed: {e}")

        # ---- Back-in-stock detection ----
        if in_stock and prev_entries:
            was_out = not prev_entries[-1].get("in_stock", True)
            if was_out:
                log.info(f"  Back in stock!")
                product["last_price"] = new_price
                try:
                    notify_back_in_stock(product)
                except Exception as e:
                    log.error(f"  Notification failed: {e}")

        log.info(f"  Done — price={new_price}, in_stock={in_stock}")
        time.sleep(random.uniform(3, 7))

    save_state(state)
    log.info("tracker_state.json updated.")


if __name__ == "__main__":
    run()
