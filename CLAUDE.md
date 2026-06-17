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
- Quince men's polo
- Quince leather mule
- Quince card holder
- Tecovas Monterrey boot

## Claude Behavior
- Never hardcode URLs in new code — read from `tracker_state.json`
- Always regenerate dashboard after a price write
- Keep DB writes idempotent (upsert by product + date)
- Lint with `ruff check . && ruff format .` before committing

## Git Workflow — Direct Push to Main
**This repo uses direct commits to `main` — no PRs.**
- Never create a feature branch or open a pull request for this repo
- Commit and push directly to `main` after every change
- This applies to all changes: adding products, config tweaks, code fixes, dashboard updates
- Trigger phrases like "add this product", "stop tracking X", "push it", "ship it" all mean: commit + `git push origin main` immediately
