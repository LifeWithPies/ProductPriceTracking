"""
Scraper layer — supports generic/Shopify via Playwright + Chrome automation.
For Tecovas (and similar JS-rendered Shopify-like stores), uses Claude in Chrome
via the cowork browser bridge when running inside Cowork. Otherwise falls back
to a headless Playwright approach.

Returns a standardised dict:
  title, price, currency, image_url, in_stock, size_stock (dict), raw
"""

import json
import re
import time
import random
from urllib.parse import urlparse


# ---------------------------------------------------------------------------
# Retailer classification
# ---------------------------------------------------------------------------
RETAILER_PATTERNS = {
    "amazon": ["amazon.com", "amazon.co.uk", "amazon.ca", "amazon.de", "amzn.to"],
    "etsy": ["etsy.com"],
}


def classify(url: str) -> str:
    host = urlparse(url).netloc.lower()
    for retailer, patterns in RETAILER_PATTERNS.items():
        if any(p in host for p in patterns):
            return retailer
    # Shopify detection happens at scrape time via meta tag
    return "generic"


# ---------------------------------------------------------------------------
# Tecovas / generic Shopify scraper (driven by saved page data)
# ---------------------------------------------------------------------------


def scrape_tecovas(
    url: str, target_size: str = "7.5", target_width: str = "D-Average"
) -> dict:
    """
    Uses playwright (or falls back to static data we already gathered via Chrome)
    to scrape Tecovas product pages.

    Called by the scheduler with the saved URL + variant params.
    """
    try:
        return _scrape_via_playwright(url, target_size, target_width)
    except Exception as e:
        raise RuntimeError(f"Scrape failed: {e}") from e


def _scrape_via_playwright(url: str, target_size: str, target_width: str) -> dict:
    """Playwright headless scrape — selects the requested size/width variant."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            locale="en-US",
        )
        page = ctx.new_page()
        page.goto(url, wait_until="networkidle", timeout=60_000)
        time.sleep(random.uniform(2, 4))

        # --- title ---
        title = page.title()

        # --- price ---
        price_text = page.locator("[class*='price']").first.inner_text()
        price = _parse_price(price_text)

        # --- image ---
        try:
            img_el = page.locator("img").first
            image_url = img_el.get_attribute("src")
        except Exception:
            image_url = None

        # Dismiss any marketing overlay before interacting with the page
        try:
            page.keyboard.press("Escape")
            time.sleep(0.5)
        except Exception:
            pass
        try:
            close_sel = (
                "[role='dialog'] button[aria-label*='close' i],"
                "[role='dialog'] button[aria-label*='dismiss' i],"
                ".bx-close, [class*='popup'] button[class*='close']"
            )
            overlay_close = page.locator(close_sel).first
            if overlay_close.count():
                overlay_close.click(timeout=3_000)
                time.sleep(0.5)
        except Exception:
            pass

        # --- click target size ---
        size_btn = page.locator(
            f"button[aria-label*='{target_size}'], label[aria-label*='{target_size}']"
        ).first
        size_btn.click()
        time.sleep(random.uniform(1, 2))

        # --- read width stock ---
        width_btn = page.locator(f"button[aria-label*='{target_width}']").first
        width_label = width_btn.get_attribute("aria-label") if width_btn.count() else ""
        in_stock = "Out of stock" not in (width_label or "")

        raw = {
            "url": url,
            "title": title,
            "price_text": price_text,
            "size": target_size,
            "width": target_width,
            "width_aria_label": width_label,
        }

        browser.close()

    return {
        "title": title,
        "price": price if in_stock else None,
        "currency": "USD",
        "image_url": image_url,
        "in_stock": in_stock,
        "raw": raw,
    }


def _parse_price(text: str) -> float | None:
    """Extract float from price strings like '$185', 'Price:$185.00'."""
    m = re.search(r"[\d,]+\.?\d*", text.replace(",", ""))
    return float(m.group()) if m else None


# ---------------------------------------------------------------------------
# Generic HTTP scraper (Shopify / Quince / httpx + BeautifulSoup)
# ---------------------------------------------------------------------------


def scrape_generic_http(url: str, variant_info: dict = None) -> dict:
    """
    httpx + BeautifulSoup scraper for Shopify/generic stores.
    Tries application/ld+json first, falls back to Open Graph meta tags.
    Works without a browser — ideal for GitHub Actions.
    """
    import httpx
    from bs4 import BeautifulSoup

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }
    r = httpx.get(url, headers=headers, follow_redirects=True, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    # ---- LD+JSON ----
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
            items = data if isinstance(data, list) else [data]
            product = next(
                (
                    d
                    for d in items
                    if d.get("@type") in ("Product", "https://schema.org/Product")
                ),
                None,
            )
            if product:
                offers = product.get("offers", {})
                if isinstance(offers, list):
                    offers = offers[0]
                raw_price = offers.get("price") or offers.get("lowPrice")
                price = (
                    float(raw_price) if raw_price not in (None, "", "0", 0) else None
                )
                in_stock = "InStock" in offers.get("availability", "")
                img = product.get("image")
                if isinstance(img, list):
                    img = img[0] if img else None
                return {
                    "title": product.get("name", ""),
                    "price": price,
                    "currency": offers.get("priceCurrency", "USD"),
                    "image_url": img,
                    "in_stock": in_stock,
                    "raw": product,
                }
        except Exception:
            pass

    # ---- Open Graph fallback ----
    def og(prop):
        t = soup.find("meta", property=prop) or soup.find("meta", attrs={"name": prop})
        return t["content"] if t and t.get("content") else None

    price_str = og("product:price:amount")
    avail_str = og("product:availability") or ""
    price = float(price_str) if price_str else None
    in_stock = "in stock" in avail_str.lower() if avail_str else True

    # ---- itemprop / data-price fallback ----
    if price is None:
        el = soup.find(attrs={"itemprop": "price"})
        if el:
            raw = el.get("content") or el.get_text()
            price = _parse_price(raw)

    if price is None:
        el = soup.find(attrs={"data-price": True})
        if el:
            try:
                cents = float(el["data-price"])
                price = cents / 100 if cents > 1000 else cents
            except (ValueError, TypeError):
                pass

    # ---- page-text regex fallback (look in <script> for price JSON) ----
    if price is None:
        for script in soup.find_all("script"):
            text = script.string or ""
            m = re.search(r'"price"\s*:\s*"?([\d.]+)"?', text)
            if m:
                candidate = float(m.group(1))
                if 1 < candidate < 10_000:
                    price = candidate
                    break

    return {
        "title": og("og:title") or "",
        "price": price,
        "currency": og("product:price:currency") or "USD",
        "image_url": og("og:image"),
        "in_stock": in_stock,
        "raw": {},
    }


# ---------------------------------------------------------------------------
# Shopify variant API scraper
# ---------------------------------------------------------------------------


def scrape_shopify_variant(url: str, variant_info: dict | None = None) -> dict:
    """
    Shopify /products/<handle>.json scraper for variant-specific price + stock.
    No auth required. Stock logic:
      inventory_management=shopify + inventory_policy=deny + qty<=0 → OOS
      inventory_management=None → always available (unmanaged)
      inventory_policy=continue → always purchasable regardless of qty
    """
    import httpx
    from urllib.parse import parse_qs

    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    variant_id_str = (qs.get("variant") or [""])[0]
    if not variant_id_str and variant_info:
        variant_id_str = str(variant_info.get("variant_id", ""))
    variant_id = int(variant_id_str) if variant_id_str else None

    handle = parsed.path.rstrip("/").split("/")[-1]
    api_url = f"{parsed.scheme}://{parsed.netloc}/products/{handle}.json"

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        )
    }
    r = httpx.get(api_url, headers=headers, follow_redirects=True, timeout=30)
    r.raise_for_status()
    product = r.json()["product"]
    variants = product["variants"]

    variant = (
        next((v for v in variants if v["id"] == variant_id), None)
        if variant_id
        else variants[0]
    )
    if not variant:
        raise ValueError(f"Variant {variant_id} not found at {api_url}")

    price = float(variant["price"]) if variant.get("price") else None
    mgmt = variant.get("inventory_management")
    policy = variant.get("inventory_policy", "deny")
    qty = variant.get("inventory_quantity") or 0

    if mgmt is None:
        in_stock = True  # unmanaged inventory = always available
    elif policy == "continue":
        in_stock = True  # Shopify "oversell" setting — always purchasable
    else:
        in_stock = qty > 0

    return {
        "title": product.get("title", ""),
        "price": price,
        "currency": "USD",
        "image_url": None,
        "in_stock": in_stock,
        "raw": {
            "variant_id": variant_id,
            "inventory_quantity": qty,
            "inventory_policy": policy,
            "inventory_management": mgmt,
        },
    }


# ---------------------------------------------------------------------------
# Generic scraper entry point
# ---------------------------------------------------------------------------


def scrape(url: str, retailer_type: str, variant_info: dict | None = None) -> dict:
    """Dispatch to the right scraper."""
    variant_info = variant_info or {}
    host = urlparse(url).netloc.lower()

    if "tecovas" in host:
        return scrape_tecovas(
            url,
            target_size=variant_info.get("size", "7.5"),
            target_width=variant_info.get("width", "D-Average"),
        )

    # Shopify variant URL — use the products API for accurate per-variant stock
    if "ekster" in host or retailer_type == "shopify_variant":
        return scrape_shopify_variant(url, variant_info)

    # Generic HTTP — covers Quince and most non-JS-gated stores
    if retailer_type in ("shopify", "generic") or "quince" in host:
        return scrape_generic_http(url, variant_info)

    raise NotImplementedError(f"No scraper implemented for: {retailer_type} ({host})")
