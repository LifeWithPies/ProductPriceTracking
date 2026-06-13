"""
Price check runner — called by the scheduler every 12 hours.
Scrapes all active products, detects price drops and back-in-stock events,
and sends email notifications.
"""
import json
import time
import random
import logging
from db import (
    get_active_products, get_latest_price,
    add_price_history, get_price_history_30d
)
from scraper import scrape, classify
from notifier import notify_price_drop, notify_back_in_stock

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger(__name__)


def run_price_check():
    products = get_active_products()
    log.info(f"Price check starting — {len(products)} active products")

    for product in products:
        try:
            _check_product(product)
        except Exception as e:
            log.error(f"Error checking product {product['id']} ({product['url']}): {e}")

        # Rate limiting: random 3–8 second delay between scrapes
        time.sleep(random.uniform(3, 8))

    log.info("Price check complete")


def _check_product(product: dict):
    pid = product["id"]
    url = product["url"]
    retailer_type = product["retailer_type"]
    variant_info = json.loads(product["variant_info"]) if product.get("variant_info") else {}

    log.info(f"Scraping product {pid}: {product['title']}")
    result = scrape(url, retailer_type, variant_info)

    new_price   = result["price"]
    new_in_stock = result["in_stock"]

    # Persist to history
    add_price_history(pid, new_price, new_in_stock, result.get("raw"))

    # Get previous state
    prev = get_latest_price(pid)  # this returns the row BEFORE the one we just inserted
    # Re-query to get the second-to-last entry
    from db import get_conn
    conn = get_conn()
    rows = conn.execute(
        "SELECT price, in_stock FROM price_history WHERE product_id = ? ORDER BY scraped_at DESC LIMIT 2",
        (pid,)
    ).fetchall()
    conn.close()

    if len(rows) < 2:
        log.info(f"  First record — baseline stored. In stock: {new_in_stock}, Price: {new_price}")
        return

    current_row  = dict(rows[0])
    previous_row = dict(rows[1])

    prev_price    = previous_row["price"]
    prev_in_stock = bool(previous_row["in_stock"])

    # Back-in-stock detection
    if not prev_in_stock and new_in_stock:
        log.info(f"  BACK IN STOCK! {product['title']}")
        product["last_price"] = new_price
        notify_back_in_stock(product)
        return

    # Skip if out of stock
    if not new_in_stock:
        log.info(f"  Out of stock — skipping drop detection")
        return

    # Price drop detection
    if prev_price is not None and new_price is not None and new_price < prev_price:
        pct = round((prev_price - new_price) / prev_price * 100, 1)
        log.info(f"  PRICE DROP: {prev_price} → {new_price} ({pct}% off)")
        history = get_price_history_30d(pid)
        notify_price_drop(product, prev_price, new_price, history)
    else:
        log.info(f"  No change. Price: {new_price}, In stock: {new_in_stock}")


if __name__ == "__main__":
    run_price_check()
