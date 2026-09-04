"""
Price Monitor Scraper
======================
用途: 讀取 products.json,逐個攞現價,寫入 price_history.json,
      按 product_group 分組比較唔同平台嘅價錢,如果有平台跌到 target_price
      (或者 target unit price),就經 Telegram Bot 發通知。

執行環境: 由 GitHub Actions 每日觸發一次 (見 .github/workflows/price-check.yml)。

需要嘅環境變數 (喺 GitHub repo secrets 度set):
  TELEGRAM_BOT_TOKEN  - 你個Telegram bot嘅token (由 BotFather攞)
  TELEGRAM_CHAT_ID    - 你自己個chat id (見 README.md 點攞)

維護提示 (2026年9月寫呢個script時嘅網站結構):
  Amazon.ca / Walmart.ca 都會不時改版,令個CSS selector失效。
  所以呢個script用『三層fallback』去攞價錢,盡量頂得耐啲:
    1) JSON-LD structured data (schema.org Product/Offer) - 呢個係俾Google睇嘅,
       網站通常會keep到update,改版都未必會拆散佢,所以放第一層。
    2) 已知嘅CSS selector (今日睇個page寫落嚟嘅) - 隨時間可能要update。
    3) Regex掃成頁文字揾 "$XX.XX" pattern - 最後防線,唔準但好過乜都攞唔到。
  如果三層都失敗,個product會計入 failures,一次過用多一個Telegram訊息話你知
  邊幾件貨攞唔到價,等你自己去睇下個網頁,update返個selector。
"""

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

BASE_DIR = Path(__file__).parent
PRODUCTS_FILE = BASE_DIR / "products.json"
HISTORY_FILE = BASE_DIR / "price_history.json"

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# 已知嘅CSS selector, 攞唔到JSON-LD先會試呢啲 (2026年9月寫呢個script時嘅版面)
PLATFORM_SELECTORS = {
    "amazon": [
        "#corePrice_feature_div span.a-price span.a-offscreen",
        "#corePriceDisplay_desktop_feature_div span.a-price span.a-offscreen",
        "span.a-price span.a-offscreen",
    ],
    "walmart": [
        '[data-testid="price-wrap"] [data-seo-id="hero-price"]',
        '[data-testid="price"] span',
        '[itemprop="price"]',
    ],
    "shoppers": [
        '[data-testid="product-price"]',
        ".price",
    ],
}

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def load_json(path, default):
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def extract_price_from_jsonld(page):
    """喺page嘅 <script type=application/ld+json> 度揾 offers.price"""
    scripts = page.query_selector_all('script[type="application/ld+json"]')
    for script in scripts:
        try:
            data = json.loads(script.inner_text())
        except (json.JSONDecodeError, TypeError):
            continue
        candidates = data if isinstance(data, list) else [data]
        for item in candidates:
            if not isinstance(item, dict):
                continue
            offers = item.get("offers")
            if isinstance(offers, dict) and offers.get("price"):
                try:
                    return float(offers["price"])
                except (TypeError, ValueError):
                    continue
            if isinstance(offers, list):
                for offer in offers:
                    if isinstance(offer, dict) and offer.get("price"):
                        try:
                            return float(offer["price"])
                        except (TypeError, ValueError):
                            continue
    return None


def extract_price_from_selectors(page, platform):
    for selector in PLATFORM_SELECTORS.get(platform, []):
        el = page.query_selector(selector)
        if el:
            text = el.inner_text().strip()
            price = parse_price_text(text)
            if price is not None:
                return price
    return None


def extract_price_from_regex(page):
    """最後防線: 掃成頁可見文字揾第一個似價錢嘅pattern"""
    body_text = page.inner_text("body")
    match = re.search(r"\$\s?(\d{1,4}(?:,\d{3})*(?:\.\d{2}))", body_text)
    if match:
        return parse_price_text(match.group(0))
    return None


def parse_price_text(text):
    match = re.search(r"(\d{1,4}(?:,\d{3})*(?:\.\d{2})?)", text.replace(",", ""))
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            return None
    return None


def fetch_price(page, url, platform):
    page.goto(url, wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(2000)  # 俾少少時間畀JS render完

    price = extract_price_from_jsonld(page)
    if price is not None:
        return price, "jsonld"

    price = extract_price_from_selectors(page, platform)
    if price is not None:
        return price, "selector"

    price = extract_price_from_regex(page)
    if price is not None:
        return price, "regex"

    return None, None


def send_telegram_message(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[警告] 未set TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID,跳過發送。")
        print("---訊息內容---")
        print(text)
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    resp = requests.post(
        url,
        json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"},
        timeout=15,
    )
    if resp.status_code != 200:
        print(f"[錯誤] Telegram發送失敗: {resp.status_code} {resp.text}")


def effective_price(product, raw_price):
    """按 compare_by 計返用嚟比較嘅價錢(單件價 vs 除pack_count嘅單位價)"""
    if product.get("compare_by") == "unit_price" and product.get("pack_count"):
        return raw_price / product["pack_count"]
    return raw_price


def effective_target(product):
    if product.get("compare_by") == "unit_price" and product.get("pack_count"):
        return product["target_price"] / product["pack_count"]
    return product["target_price"]


def main():
    products = load_json(PRODUCTS_FILE, {"products": []})["products"]
    history = load_json(HISTORY_FILE, {})

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    results = {}  # id -> {"raw_price":..., "product":...}
    failures = []

    active_products = [p for p in products if p.get("active", True)]

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(user_agent=USER_AGENT)

        for product in active_products:
            try:
                price, method = fetch_price(page, product["url"], product["platform"])
            except Exception as exc:  # noqa: BLE001 - 想乜錯都攞埋唔想成個run死咗
                print(f"[錯誤] {product['id']} 攞價失敗: {exc}")
                price, method = None, None

            if price is None:
                failures.append(product)
                continue

            print(f"[OK] {product['id']} ({product['platform']}) = ${price} (method={method})")
            results[product["id"]] = {"raw_price": price, "product": product}

            history.setdefault(product["id"], [])
            history[product["id"]].append({"date": today, "price": price})

        browser.close()

    save_json(HISTORY_FILE, history)

    # 按 product_group 分組,睇下有冇平台中target
    groups = {}
    for pid, r in results.items():
        group = r["product"]["product_group"]
        groups.setdefault(group, []).append(r)

    alert_lines = []
    for group, items in groups.items():
        hits = []
        lines = [f"<b>{items[0]['product']['name'].split(',')[0]}</b>"]
        for r in items:
            p = r["product"]
            raw = r["raw_price"]
            eff = effective_price(p, raw)
            target_eff = effective_target(p)
            hit = eff <= target_eff
            unit_note = f" (單價 ${eff:.2f})" if p.get("compare_by") == "unit_price" else ""
            mark = " ✅中咗!" if hit else ""
            lines.append(
                f"  {p['platform']}: ${raw:.2f}{unit_note} / target ${p['target_price']:.2f}{mark}"
            )
            if hit:
                hits.append(p["platform"])
        if hits:
            lines.append(f"👉 建議去 {', '.join(hits)} 買")
            alert_lines.append("\n".join(lines))

    if alert_lines:
        message = "🎯 平價提示!\n\n" + "\n\n".join(alert_lines)
        send_telegram_message(message)
    else:
        print("今次冇任何產品跌到target price,唔發通知。")

    if failures:
        fail_names = "\n".join(f"- {p['name']} ({p['platform']})" for p in failures)
        send_telegram_message(
            "⚠️ 以下產品今次攞唔到價錢,可能網站改咗版,要去check下selector:\n\n"
            + fail_names
        )

    if failures and not results:
        # 成批都攞唔到,好可能係網絡/環境問題,俾個非零exit code等GitHub Actions標紅
        sys.exit(1)


if __name__ == "__main__":
    main()
