# Product Price Tracking — Technical Specification

---

## 1. Overview

A self-hosted price-tracking system that:
- Accepts product URLs from multiple retailer types (Amazon, Etsy, Shopify, generic)
- Scrapes price + metadata on a 12-hour schedule
- Stores price history
- Sends email + Claude notification when a price drops, including a buy/wait analysis
- Exposes a live artifact dashboard showing all tracked products and their price history graphs

---

## 2. System Architecture

```
User submits URL
      │
      ▼
┌─────────────────┐
│  URL Intake     │  — Classify retailer type, extract product ID
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Scraper Layer  │  — Retailer-specific adapters (see §4)
└────────┬────────┘
         │ price, title, image_url, currency
         ▼
┌─────────────────┐
│  Price Store    │  — SQLite (local) or Postgres; append-only history table
└────────┬────────┘
         │
    ┌────┴────┐
    ▼         ▼
Scheduler  Dashboard
(12h cron) (Live Artifact)
    │
    ▼
Price Drop Detector
    │
    ▼
Notifier (Email + Claude analysis)
```

---

## 3. Data Model

### `products` table
| Column        | Type    | Notes                        |
|---------------|---------|------------------------------|
| id            | INTEGER | PK                           |
| url           | TEXT    | Original product URL         |
| retailer_type | TEXT    | `amazon` `etsy` `shopify` `generic` |
| title         | TEXT    | Product name                 |
| image_url     | TEXT    |                              |
| currency      | TEXT    | ISO 4217 (USD, GBP, etc.)    |
| added_at      | TEXT    | ISO 8601                     |
| active        | BOOLEAN | Stop tracking if false       |

### `price_history` table
| Column      | Type    | Notes                   |
|-------------|---------|-------------------------|
| id          | INTEGER | PK                      |
| product_id  | INTEGER | FK → products.id        |
| price       | REAL    |                         |
| scraped_at  | TEXT    | ISO 8601 UTC            |
| raw_payload | TEXT    | JSON blob of full scrape result |

---

## 4. Scraper Layer

### 4.1 Retailer Classification

```python
from urllib.parse import urlparse

RETAILER_PATTERNS = {
    "amazon":   ["amazon.com", "amazon.co.uk", "amazon.ca", "amazon.de", "amzn.to"],
    "etsy":     ["etsy.com"],
    "shopify":  [],  # detected via HTML meta tag `shopify-checkout-api-token`
}

def classify(url: str) -> str:
    host = urlparse(url).netloc.lower()
    for retailer, patterns in RETAILER_PATTERNS.items():
        if any(p in host for p in patterns):
            return retailer
    return "generic"
```

### 4.2 Scraper Adapters

Each adapter must return:
```python
{
  "title": str,
  "price": float,
  "currency": str,
  "image_url": str | None,
  "in_stock": bool,
  "raw": dict   # full parsed payload for auditing
}
```

---

#### 4.2.1 Generic / Shopify Scraper (Playwright)

Used for: Shopify stores, most JS-heavy sites, fallback for unknown retailers.

**Tool:** [Playwright](https://playwright.dev/python/) (headless Chromium)

```python
from playwright.sync_api import sync_playwright
import json, re

def scrape_generic(url: str) -> dict:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(user_agent="Mozilla/5.0 ...")
        page.goto(url, wait_until="networkidle", timeout=30000)

        # Try JSON-LD first (works on Shopify + many others)
        ld = page.evaluate("""
            () => {
                const scripts = document.querySelectorAll('script[type="application/ld+json"]');
                for (const s of scripts) {
                    try {
                        const d = JSON.parse(s.textContent);
                        if (d['@type'] === 'Product') return d;
                    } catch {}
                }
                return null;
            }
        """)

        if ld:
            offer = ld.get("offers", {})
            if isinstance(offer, list):
                offer = offer[0]
            return {
                "title": ld.get("name"),
                "price": float(offer.get("price", 0)),
                "currency": offer.get("priceCurrency", "USD"),
                "image_url": ld.get("image"),
                "in_stock": offer.get("availability", "").endswith("InStock"),
                "raw": ld
            }

        # Fallback: Open Graph + visible price text
        title = page.evaluate("document.querySelector('meta[property=\"og:title\"]')?.content")
        price_text = page.evaluate("""
            () => {
                const el = document.querySelector('[class*="price"],[id*="price"],[itemprop="price"]');
                return el ? el.textContent.trim() : null;
            }
        """)
        price = float(re.sub(r"[^0-9.]", "", price_text or "0") or 0)
        browser.close()
        return {"title": title, "price": price, "currency": "USD",
                "image_url": None, "in_stock": True, "raw": {}}
```

---

#### 4.2.2 Etsy Scraper

Etsy renders server-side HTML with structured data; also exposes Open Graph tags.

```python
import httpx
from bs4 import BeautifulSoup
import json, re

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 Chrome/124 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

def scrape_etsy(url: str) -> dict:
    r = httpx.get(url, headers=HEADERS, follow_redirects=True, timeout=15)
    soup = BeautifulSoup(r.text, "html.parser")

    # JSON-LD
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            d = json.loads(tag.string)
            if d.get("@type") == "Product":
                offer = d.get("offers", {})
                return {
                    "title": d.get("name"),
                    "price": float(offer.get("price", 0)),
                    "currency": offer.get("priceCurrency", "USD"),
                    "image_url": d.get("image"),
                    "in_stock": True,
                    "raw": d
                }
        except Exception:
            pass

    # Fallback: meta tags
    price = soup.find("meta", property="product:price:amount")
    currency = soup.find("meta", property="product:price:currency")
    title = soup.find("meta", property="og:title")
    return {
        "title": title["content"] if title else None,
        "price": float(price["content"]) if price else 0.0,
        "currency": currency["content"] if currency else "USD",
        "image_url": None,
        "in_stock": True,
        "raw": {}
    }
```

---

#### 4.2.3 Amazon Scraper

Amazon aggressively blocks scrapers. Use the following layered strategy:

**Option A — Rainforest API (recommended, paid)**
- API: `https://api.rainforestapi.com/request`
- Extracts ASIN from URL, calls API, returns structured price data
- No bot detection, handles all Amazon locales

```python
import httpx, re

def extract_asin(url: str) -> str | None:
    m = re.search(r"/dp/([A-Z0-9]{10})", url)
    return m.group(1) if m else None

def scrape_amazon_rainforest(url: str, api_key: str) -> dict:
    asin = extract_asin(url)
    r = httpx.get("https://api.rainforestapi.com/request", params={
        "api_key": api_key,
        "type": "product",
        "asin": asin,
        "amazon_domain": "amazon.com"
    }, timeout=20)
    d = r.json().get("product", {})
    return {
        "title": d.get("title"),
        "price": d.get("buybox_winner", {}).get("price", {}).get("value", 0.0),
        "currency": d.get("buybox_winner", {}).get("price", {}).get("currency", "USD"),
        "image_url": d.get("main_image", {}).get("link"),
        "in_stock": d.get("buybox_winner", {}).get("availability", {}).get("type") == "now",
        "raw": d
    }
```

**Option B — Playwright with stealth (free, less reliable)**

```bash
pip install playwright-stealth
```

```python
from playwright.sync_api import sync_playwright
from playwright_stealth import stealth_sync

def scrape_amazon_playwright(url: str) -> dict:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        stealth_sync(page)  # patches navigator.webdriver and other tells
        page.goto(url, wait_until="domcontentloaded", timeout=30000)

        title = page.text_content("#productTitle")
        price_whole = page.text_content(".a-price-whole")
        price_frac  = page.text_content(".a-price-fraction")
        price = float(f"{(price_whole or '0').strip().replace(',','')}"
                      f".{(price_frac or '00').strip()}")
        browser.close()
        return {"title": (title or "").strip(), "price": price,
                "currency": "USD", "image_url": None, "in_stock": True, "raw": {}}
```

> **Note:** Rotate user agents and add random delays between requests to reduce block rate. For production, prefer Option A.

---

### 4.3 Scraper Router

```python
SCRAPERS = {
    "amazon":  scrape_amazon_rainforest,   # swap for playwright variant if no API key
    "etsy":    scrape_etsy,
    "shopify": scrape_generic,
    "generic": scrape_generic,
}

def scrape(url: str, **kwargs) -> dict:
    retailer = classify(url)
    return SCRAPERS[retailer](url, **kwargs)
```

---

## 5. Scheduler

Use the [schedule](https://schedule.readthedocs.io/) library or APScheduler. Alternatively, use Cowork's built-in scheduled task feature.

### 5.1 Using APScheduler

```python
from apscheduler.schedulers.blocking import BlockingScheduler
from db import get_active_products, save_price
from scraper import scrape
from notifier import check_and_notify

scheduler = BlockingScheduler()

@scheduler.scheduled_job("interval", hours=12)
def run_price_checks():
    for product in get_active_products():
        try:
            result = scrape(product["url"])
            save_price(product["id"], result["price"])
            check_and_notify(product, result["price"])
        except Exception as e:
            print(f"[ERROR] {product['url']}: {e}")

scheduler.start()
```

### 5.2 Using Cowork Scheduled Tasks

In Claude (Cowork), you can say:
> "Every 12 hours, check prices of all tracked products and notify me of any drops."

Claude will create a scheduled task that re-runs this conversation context automatically.

---

## 6. Price Drop Detection & Notification

### 6.1 Drop Detection Logic

```python
def is_price_drop(product_id: int, new_price: float) -> tuple[bool, float]:
    """Returns (dropped: bool, previous_price: float)."""
    prev = get_latest_price(product_id)  # query price_history ORDER BY scraped_at DESC LIMIT 1
    if prev is None:
        return False, new_price
    return new_price < prev, prev
```

### 6.2 Claude Analysis Prompt

When a drop is detected, call Claude with:

```
Product: {title}
URL: {url}
Price history (last 30 days): {json_array_of_price_points}
Previous price: {prev_price} {currency}
Current price: {new_price} {currency}
Drop: {pct_drop:.1f}%

Based on this price history, give a concise buy-vs-wait recommendation.
Consider: how deep the drop is relative to the historical range, whether the
price has been lower before, and the overall trend direction.
Keep the analysis under 100 words.
```

### 6.3 Email Notification

**Library:** `smtplib` + `email.mime` (stdlib) or `sendgrid` SDK

```python
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

def send_price_drop_email(to: str, product: dict, prev: float, new: float,
                          analysis: str, url: str):
    pct = round((prev - new) / prev * 100, 1)
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"💸 Price Drop: {product['title']} — now {new} ({pct}% off)"
    msg["From"] = "price-tracker@yourdomain.com"
    msg["To"] = to

    html = f"""
    <h2>{product['title']}</h2>
    <p><strong>Previous price:</strong> {prev} {product['currency']}<br>
       <strong>New price:</strong> {new} {product['currency']} ({pct}% drop)</p>
    <p><a href="{url}">View product →</a></p>
    <hr>
    <h3>Claude's Analysis</h3>
    <p>{analysis}</p>
    """
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login("your@gmail.com", "app_password")
        s.send_message(msg)
```

> Use Gmail App Passwords or SendGrid for reliable delivery. Store credentials in `.env`, never in code.

---

## 7. Live Dashboard (Cowork Artifact)

The dashboard is a live artifact in Cowork that calls stored data on load and renders:
- A card for each tracked product (image, current price, % change)
- A price history line chart per product (Chart.js)
- Color-coded indicators: green = all-time low, red = rising, gray = stable

**Trigger phrase to create it:**
> "Create a live artifact dashboard showing all my tracked products and their price history charts."

The artifact uses `window.cowork.callMcpTool` to read from a connected data source (e.g., Google Sheets synced from the price store, or a REST endpoint you expose).

---

## 8. Configuration

Store all config in a `.env` file:

```env
# Scraping
RAINFOREST_API_KEY=your_key_here
SCRAPE_INTERVAL_HOURS=12

# Notifications
NOTIFY_EMAIL=krovvidiprashant@gmail.com
SMTP_HOST=smtp.gmail.com
SMTP_PORT=465
SMTP_USER=your@gmail.com
SMTP_PASSWORD=your_app_password

# Database
DB_PATH=./price_tracker.db

# Claude API (for analysis)
ANTHROPIC_API_KEY=your_key_here
```

---

## 9. Adding a New Product

### Via CLI
```bash
python add_product.py "https://www.amazon.com/dp/B0CXYZ1234"
```

Output:
```
✓ Classified as: amazon
✓ Fetched: "Sony WH-1000XM5 Headphones" — $279.99
✓ Added to tracker (id=7). Next check in ~12h.
```

### Via Cowork
Tell Claude:
> "Start tracking this product: [URL]"

Claude will scrape it, confirm the title and price, save it, and confirm the next scheduled check.

---

## 10. Tech Stack Summary

| Layer         | Tool / Library                  |
|---------------|---------------------------------|
| Language      | Python 3.11+                    |
| Scraping (JS) | Playwright + playwright-stealth |
| Scraping (HTML) | httpx + BeautifulSoup          |
| Amazon        | Rainforest API (preferred)      |
| Database      | SQLite (local) / Postgres (prod)|
| Scheduler     | APScheduler or Cowork Tasks     |
| Notifications | smtplib / SendGrid              |
| Analysis      | Claude API (claude-haiku-4-5)   |
| Dashboard     | Cowork Live Artifact + Chart.js |
| Config        | python-dotenv                   |

---

## 11. Setup & Installation

```bash
# Clone / create project directory
cd "Product Price Tracking"

# Install dependencies
pip install playwright httpx beautifulsoup4 apscheduler python-dotenv anthropic sendgrid --break-system-packages
playwright install chromium

# Init database
python init_db.py

# Add first product
python add_product.py "https://www.etsy.com/listing/123456789"

# Start scheduler
python scheduler.py
```

---

## 12. Edge Cases & Notes

- **Out-of-stock items:** Store price as `null`; skip drop detection; re-check on next cycle.
- **Currency normalization:** If tracking products across regions, normalize to a base currency via an FX API before comparison.
- **Price variants:** Some products (e.g., clothing sizes) have multiple prices. Always scrape and store the lowest listed price, or make variant selection explicit in the URL.
- **Cloudflare / bot protection:** Some Shopify stores use Cloudflare Turnstile. If Playwright is blocked, try Zyte API or ScraperAPI as a fallback proxy layer.
- **Rate limiting:** Add a random 3–8 second delay between scrapes when running a batch. Never hammer the same domain in rapid succession.
- **Amazon regional URLs:** ASIN is universal; the scraper should normalize `amazon.co.uk` → `amazon.com` before Rainforest API calls (or pass the correct `amazon_domain` param).
