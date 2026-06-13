#!/usr/bin/env python3
"""Generate dashboard3.html with real product images fetched from CDN."""

import base64, json, urllib.request, pathlib, io, sys
from datetime import datetime

# CDN image URLs (from prior extraction session)
IMAGE_URLS = {
    1: "https://cdn.sanity.io/images/v8kybopt/production/3a7a5bafb257435e71c474f9c8944cc65e612568-2000x2000.png",  # TEC loafer
    2: "https://images.quince.com/5dVheUQumSrPklFW9nIKrl/0c33ad756cef0a08f21a3608adef63e0/M-M--6-SND-016_EDITED.jpg",  # MULE
    3: "https://images.quince.com/6iMEQUyyUjTaSsfaDQwxI7/67f558e4145b22ab9ea9c458232ad03c/M-LKT-94-BAYOLI_01_EDITED.jpg",  # POLO
    4: "https://images.quince.com/ae1d8l2sHp6dcIbEyCMcD/1b143da34179e2500de5200946b1bb1e/M-BAG-25-BLA-171_EDITED.jpg",  # CARD
}

def fetch_image_b64(url, target_w=600, target_h=750):
    """Download image, resize with Pillow, return base64 data URI."""
    try:
        from PIL import Image
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        })
        data = urllib.request.urlopen(req, timeout=15).read()
        img = Image.open(io.BytesIO(data)).convert('RGB')
        ow, oh = img.size
        # Scale so image fills the target frame (cover), then center-crop
        scale = max(target_w / ow, target_h / oh)
        nw, nh = int(ow * scale), int(oh * scale)
        img = img.resize((nw, nh), Image.LANCZOS)
        # Center crop to exact target dimensions
        left = (nw - target_w) // 2
        top = (nh - target_h) // 2
        img = img.crop((left, top, left + target_w, top + target_h))
        # Save as JPEG
        buf = io.BytesIO()
        img.save(buf, 'JPEG', quality=82, optimize=True)
        b64 = base64.b64encode(buf.getvalue()).decode()
        return f"data:image/jpeg;base64,{b64}"
    except Exception as e:
        print(f"  ERROR fetching {url}: {e}", file=sys.stderr)
        return None

def load_state():
    p = pathlib.Path(__file__).parent / "tracker_state.json"
    return json.loads(p.read_text())

def get_latest_price(price_history, product_id):
    entries = [e for e in price_history if e['product_id'] == product_id]
    entries.sort(key=lambda x: x['scraped_at'], reverse=True)
    return entries[0] if entries else None

def price_change_pct(price_history, product_id):
    entries = [e for e in price_history if e['product_id'] == product_id and e.get('price')]
    if len(entries) < 2:
        return None
    entries.sort(key=lambda x: x['scraped_at'])
    first, last = entries[0]['price'], entries[-1]['price']
    return ((last - first) / first) * 100

def fmt_price(price):
    if price is None:
        return "—"
    return f"${price:.2f}"

def sparkline_svg(price_history, product_id, w=120, h=40):
    entries = [e for e in price_history if e['product_id'] == product_id and e.get('price')]
    if len(entries) < 2:
        return ""
    entries.sort(key=lambda x: x['scraped_at'])
    prices = [e['price'] for e in entries]
    mn, mx = min(prices), max(prices)
    if mn == mx:
        mn -= 1
        mx += 1
    def px(i, p):
        x = int((i / (len(prices) - 1)) * (w - 4)) + 2
        y = int(((mx - p) / (mx - mn)) * (h - 4)) + 2
        return f"{x},{y}"
    pts = " ".join(px(i, p) for i, p in enumerate(prices))
    trend_color = "#22c55e" if prices[-1] <= prices[0] else "#ef4444"
    return f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" fill="none" xmlns="http://www.w3.org/2000/svg"><polyline points="{pts}" stroke="{trend_color}" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>'

def build_card(product, latest, change_pct, data_uri):
    pid = product['id']
    title = product['title']
    url = product['url']
    currency = product.get('currency', 'USD')

    price = latest['price'] if latest else None
    in_stock = latest.get('in_stock', False) if latest else False
    scraped = latest['scraped_at'][:10] if latest else "—"

    price_str = fmt_price(price)
    stock_badge = (
        '<span class="badge badge-out">Out of Stock</span>'
        if not in_stock else
        '<span class="badge badge-in">In Stock</span>'
    )

    change_html = ""
    if change_pct is not None:
        arrow = "▼" if change_pct <= 0 else "▲"
        cls = "change-down" if change_pct <= 0 else "change-up"
        change_html = f'<span class="{cls}">{arrow} {abs(change_pct):.1f}%</span>'

    img_html = (
        f'<img src="{data_uri}" alt="{title}" class="product-img" loading="lazy">'
        if data_uri else
        '<div class="img-placeholder">No Image</div>'
    )

    variant = product.get('variant', {})
    variant_bits = []
    if 'size' in variant:
        variant_bits.append(f"Size: {variant['size']}")
    if 'color' in variant:
        variant_bits.append(f"Color: {variant['color'].replace('-', ' ').title()}")
    variant_html = f'<p class="variant">{" · ".join(variant_bits)}</p>' if variant_bits else ""

    return f"""
    <div class="card">
      <a href="{url}" target="_blank" class="img-link">
        <div class="img-wrap">
          {img_html}
        </div>
      </a>
      <div class="card-body">
        <a href="{url}" target="_blank" class="product-title">{title}</a>
        {variant_html}
        <div class="price-row">
          <span class="price">{price_str}</span>
          {stock_badge}
        </div>
        <div class="meta-row">
          {change_html}
          <span class="last-checked">Updated {scraped}</span>
        </div>
        <a href="{url}" target="_blank" class="shop-btn">View Product →</a>
      </div>
    </div>"""

def generate_html(cards_html, generated_at):
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Price Tracker Dashboard</title>
<style>
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: #f5f5f5;
    color: #111;
    min-height: 100vh;
  }}

  header {{
    background: #fff;
    border-bottom: 1px solid #e5e5e5;
    padding: 20px 32px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    position: sticky;
    top: 0;
    z-index: 10;
    box-shadow: 0 1px 3px rgba(0,0,0,0.06);
  }}

  .logo {{
    font-size: 18px;
    font-weight: 700;
    letter-spacing: -0.3px;
    color: #111;
  }}

  .logo span {{ color: #2563eb; }}

  .header-meta {{
    font-size: 12px;
    color: #888;
  }}

  .grid {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(270px, 1fr));
    gap: 24px;
    max-width: 1200px;
    margin: 36px auto;
    padding: 0 24px;
  }}

  .card {{
    background: #fff;
    border-radius: 12px;
    overflow: hidden;
    box-shadow: 0 1px 4px rgba(0,0,0,0.08), 0 4px 16px rgba(0,0,0,0.04);
    transition: transform 0.15s ease, box-shadow 0.15s ease;
    display: flex;
    flex-direction: column;
  }}

  .card:hover {{
    transform: translateY(-2px);
    box-shadow: 0 4px 12px rgba(0,0,0,0.12), 0 8px 24px rgba(0,0,0,0.06);
  }}

  .img-link {{
    display: block;
    text-decoration: none;
  }}

  .img-wrap {{
    width: 100%;
    aspect-ratio: 4 / 5;
    overflow: hidden;
    background: #fafafa;
    position: relative;
  }}

  .product-img {{
    width: 100%;
    height: 100%;
    object-fit: cover;
    object-position: center top;
    display: block;
    transition: transform 0.3s ease;
  }}

  .card:hover .product-img {{
    transform: scale(1.03);
  }}

  .img-placeholder {{
    width: 100%;
    height: 100%;
    display: flex;
    align-items: center;
    justify-content: center;
    color: #bbb;
    font-size: 14px;
    background: #f0f0f0;
  }}

  .card-body {{
    padding: 16px 18px 20px;
    display: flex;
    flex-direction: column;
    gap: 8px;
    flex: 1;
  }}

  .product-title {{
    font-size: 14px;
    font-weight: 600;
    color: #111;
    line-height: 1.35;
    text-decoration: none;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }}

  .product-title:hover {{ color: #2563eb; }}

  .variant {{
    font-size: 12px;
    color: #666;
    text-transform: capitalize;
  }}

  .price-row {{
    display: flex;
    align-items: center;
    gap: 10px;
    margin-top: 4px;
  }}

  .price {{
    font-size: 22px;
    font-weight: 700;
    color: #111;
    letter-spacing: -0.5px;
  }}

  .badge {{
    font-size: 10px;
    font-weight: 600;
    padding: 3px 8px;
    border-radius: 20px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }}

  .badge-in {{
    background: #dcfce7;
    color: #15803d;
  }}

  .badge-out {{
    background: #fee2e2;
    color: #b91c1c;
  }}

  .meta-row {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    font-size: 11px;
  }}

  .change-down {{ color: #16a34a; font-weight: 600; }}
  .change-up {{ color: #dc2626; font-weight: 600; }}

  .last-checked {{ color: #aaa; }}

  .shop-btn {{
    display: inline-block;
    margin-top: 8px;
    padding: 9px 16px;
    background: #111;
    color: #fff;
    border-radius: 8px;
    font-size: 13px;
    font-weight: 600;
    text-decoration: none;
    text-align: center;
    transition: background 0.15s;
  }}

  .shop-btn:hover {{ background: #2563eb; }}

  footer {{
    text-align: center;
    padding: 24px;
    font-size: 12px;
    color: #bbb;
  }}
</style>
</head>
<body>
<header>
  <div class="logo">Price<span>Tracker</span></div>
  <div class="header-meta">Generated {generated_at} · {len(cards_html)} products tracked</div>
</header>
<main>
  <div class="grid">
    {''.join(cards_html)}
  </div>
</main>
<footer>Prices sourced from retailer websites. Check links for current availability.</footer>
</body>
</html>"""


def main():
    state = load_state()
    products = state['products']
    price_history = state['price_history']

    # Target image dimensions: 600x750 (4:5) for portrait items, 600x600 for square
    dim_map = {
        1: (600, 600),  # TEC - square loafer shot
        2: (600, 750),  # MULE - portrait
        3: (600, 750),  # POLO - portrait
        4: (600, 750),  # CARD - portrait
    }

    cards_html = []
    for product in products:
        pid = product['id']
        url = IMAGE_URLS.get(pid)
        print(f"Fetching image for product {pid}: {product['title'][:40]}...")
        if url:
            w, h = dim_map.get(pid, (600, 750))
            data_uri = fetch_image_b64(url, target_w=w, target_h=h)
            if data_uri:
                print(f"  ✓ Got image ({len(data_uri)//1024}KB b64)")
            else:
                print(f"  ✗ Failed")
        else:
            data_uri = None
            print(f"  ✗ No URL")

        latest = get_latest_price(price_history, pid)
        change = price_change_pct(price_history, pid)
        cards_html.append(build_card(product, latest, change, data_uri))

    generated_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    html = generate_html(cards_html, generated_at)

    out = pathlib.Path(__file__).parent / "dashboard.html"
    out.write_text(html, encoding='utf-8')
    print(f"\n✓ Written to {out} ({len(html)//1024}KB)")
    return str(out)

if __name__ == "__main__":
    main()
