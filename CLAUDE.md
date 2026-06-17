# Product Price Tracker — Prashant Krovvidi

## Purpose
Track prices for specific products (Quince, Tecovas) via web scraping, store history in SQLite, and render an HTML dashboard. Scheduled price checks run daily and push dashboard updates.

## Tech Stack
- **Language**: Python 3.11+
- **DB**: SQLite (`price_tracker.db`)
- **Scraping**: `scraper.py` (requests/BeautifulSoup or Playwright)
- **Dashboard**: `gen_dashboard4.py` → `dashboard.html` / `index.html`
- **Notifications**: `notifier.py`
- **Scheduling**: Claude Code `/schedule` tasks

## Key Files
- `scraper.py` — fetches current price for a given URL
- `price_check.py` — runs a single product check and writes to DB
- `db.py` — SQLite read/write helpers
- `gen_dashboard4.py` — regenerates `dashboard.html` from DB history
- `notifier.py` — sends alerts when price drops below threshold
- `requirements.txt` — dependencies

## Tracked Products
| ID | Title | URL | Active |
|----|-------|-----|--------|
| 1 | The Monterrey Men's Loafer - Granite Suede (7.5 D) | tecovas.com/products/the-monterrey?color=granite-suede | ✓ |
| 2 | Italian Leather Mule Slip-On in Sand (8) | quince.com/...mens-italian-leather-mule-slip-on | ✗ inactive |
| 3 | 100% Organic Cotton Mesh-Stitch Polo in Bayberry Olive | quince.com/...mens-mesh-stitch-organic-cotton-button-through-polo | ✓ |
| 4 | Italian Leather RFID Card Holder in Black | quince.com/...mens-italian-leather-rfid-card-holder | ✓ |
| 5 | Tech Merino Short Sleeve Tee in Black (M) | quince.com/men/tech-merino-short-sleeve-tee?color=black&size=m | ✓ |
| 6 | Tech Merino Short Sleeve Tee in Off White (M) | quince.com/men/tech-merino-short-sleeve-tee?color=off-white&size=m | ✓ |
| 7 | Tech Merino Long Sleeve Baselayer in Black (M) | quince.com/men/tech-merino-long-sleeve-baselayer?color=black&size=m | ✓ |

**Next ID to use: 8**

Always keep this table in sync when adding or deactivating products.

## Claude Behavior

### CRITICAL — Adding a new product
When the user pastes a URL and says "add this" or "track this":
1. Fetch the OG image URL from the product page (httpx + BeautifulSoup, use the venv)
2. Add the product entry to `tracker_state.json` (next available ID, `active: true`, `image_url` set)
3. Add an initial `price_history` entry (`in_stock: true`, `price: null`, note that price will be confirmed on next CI run)
4. **Immediately** run `python3 gen_dashboard4.py && cp dashboard.html index.html`
5. Commit all three files (`tracker_state.json`, `dashboard.html`, `index.html`) and push to `main`
6. Update the Tracked Products table above with the new entry and bump the "Next ID" counter

Do all of this in one shot — the dashboard must reflect the new product before reporting back.

### General rules
- Never hardcode URLs in new code — read from `tracker_state.json`
- Keep DB writes idempotent (upsert by product + date)
- Lint with `ruff check . && ruff format .` before committing

## Git Workflow — Direct Push to Main
**This repo uses direct commits to `main` — no PRs.**
- Never create a feature branch or open a pull request for this repo
- Commit and push directly to `main` after every change
- This applies to all changes: adding products, config tweaks, code fixes, dashboard updates
- Trigger phrases like "add this product", "stop tracking X", "push it", "ship it" all mean: commit + `git push origin main` immediately
