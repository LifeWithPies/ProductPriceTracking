"""Email notification for price drops and back-in-stock alerts."""
import os
import smtplib
import json
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv

load_dotenv()

SMTP_HOST     = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT     = int(os.getenv("SMTP_PORT", 465))
SMTP_USER     = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
NOTIFY_EMAIL  = os.getenv("NOTIFY_EMAIL", "krovvidiprashant@gmail.com")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")


def _claude_analysis(title, url, history, prev_price, new_price, currency) -> str:
    """Call claude-haiku-4-5 for buy/wait recommendation."""
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        pct = round((prev_price - new_price) / prev_price * 100, 1)
        prompt = f"""Product: {title}
URL: {url}
Price history (last 30 days): {json.dumps(history)}
Previous price: {prev_price} {currency}
Current price: {new_price} {currency}
Drop: {pct}%

Give a concise buy-vs-wait recommendation (under 100 words).
Consider: depth of drop relative to historical range, whether price has been
lower before, and overall trend direction."""

        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}]
        )
        return msg.content[0].text
    except Exception as e:
        return f"(Analysis unavailable: {e})"


def _send_email(subject: str, body: str):
    if not SMTP_USER or not SMTP_PASSWORD:
        print(f"[notifier] SMTP not configured. Would send:\nSubject: {subject}\n{body}")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = SMTP_USER
    msg["To"]      = NOTIFY_EMAIL
    msg.attach(MIMEText(body, "plain"))

    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as s:
        s.login(SMTP_USER, SMTP_PASSWORD)
        s.sendmail(SMTP_USER, NOTIFY_EMAIL, msg.as_string())
    print(f"[notifier] Email sent: {subject}")


def notify_price_drop(product: dict, prev_price: float, new_price: float, history: list):
    currency = product.get("currency", "USD")
    pct = round((prev_price - new_price) / prev_price * 100, 1)
    analysis = _claude_analysis(
        product["title"], product["url"], history,
        prev_price, new_price, currency
    )
    subject = f"Price Drop: {product['title']} — now {currency} {new_price} ({pct}% off)"
    body = f"""Price drop detected!

Product : {product['title']}
URL     : {product['url']}
Variant : {product.get('variant_info', '')}

Previous price : {currency} {prev_price}
New price      : {currency} {new_price}
Drop           : {pct}%

--- Buy/Wait Analysis ---
{analysis}
"""
    _send_email(subject, body)


def notify_back_in_stock(product: dict):
    variant = product.get("variant_info", "")
    subject = f"Back in Stock: {product['title']} {variant}"
    body = f"""Great news — the item you're tracking is back in stock!

Product : {product['title']}
URL     : {product['url']}
Variant : {variant}

Current price: {product.get('currency','USD')} {product.get('last_price','N/A')}

Check it out before it sells out again.
"""
    _send_email(subject, body)
