#!/usr/bin/env python3
"""
Scrape the star rating and number of reviews from Google Maps listings.

Each input can be:
  - a Google Maps place URL      https://www.google.com/maps/place/...
  - a share / short link         https://maps.app.goo.gl/...  or  https://g.co/kgs/...
  - plain search text            "Joe's Pizza 7 Carmine St New York"

Usage:
  python google_reviews.py "Eiffel Tower" "https://maps.app.goo.gl/abc123"
  python google_reviews.py -i listings.txt -o results.csv
  python google_reviews.py -i listings.csv --show        # watch the browser work
"""

import argparse
import asyncio
import csv
import random
import re
import sys
from pathlib import Path
from urllib.parse import parse_qs, quote_plus, unquote_plus, urlencode, urlparse, urlunparse

from playwright.async_api import TimeoutError as PWTimeout
from playwright.async_api import async_playwright

RATING_BOX = "div.F7nice"          # the "4.7 ★★★★★ (501,218)" block under the place name
RESULTS_FEED = 'div[role="feed"]'  # list of results shown when a search matches many places
# CSV headers we look for (a header just has to contain one of these words, e.g. "Business Name").
INPUT_COLUMNS = ("url", "link", "query", "name", "business", "listing", "place")
LOCATION_COLUMNS = ("address", "city", "location")

# Runs in the page; returns raw strings that Python cleans up.
EXTRACT_JS = r"""
() => {
  const main = document.querySelector('div[role="main"][aria-label]');
  const h1 = document.querySelector('h1.DUwDvf') || (main && main.querySelector('h1'));
  const name = (h1 && h1.innerText.trim()) || (main && main.getAttribute('aria-label')) || null;

  let rating = null, reviews = null;
  const box = document.querySelector('div.F7nice');
  if (box) {
    const visible = box.querySelector('span[aria-hidden="true"]');
    if (visible) rating = visible.textContent.trim();
    for (const el of box.querySelectorAll('[aria-label]')) {
      const label = el.getAttribute('aria-label');
      let m;
      if (!rating && (m = label.match(/([\d.,]+)\s*star/i))) rating = m[1];
      if (!reviews && (m = label.match(/([\d.,\s ]+)\s*reviews?/i))) reviews = m[1];
    }
    if (!reviews) {
      const m = box.innerText.match(/\(([\d.,\s ]+)\)/);
      if (m) reviews = m[1];
    }
  }

  // Fallback: add up the 5-star..1-star histogram ("5 stars, 401,489 reviews").
  if (!reviews) {
    let sum = 0, found = false;
    for (const row of document.querySelectorAll('tr[role="img"][aria-label]')) {
      const m = row.getAttribute('aria-label').match(/,\s*([\d.,\s ]+)\s*reviews?/i);
      if (m) { sum += parseInt(m[1].replace(/\D/g, ''), 10); found = true; }
    }
    if (found) reviews = String(sum);
  }

  const addrEl = document.querySelector('button[data-item-id="address"]');
  const address = addrEl
    ? (addrEl.getAttribute('aria-label') || addrEl.innerText).replace(/^\s*Address:\s*/i, '').trim()
    : null;

  return { name, rating, reviews, address };
}
"""


FIRST_ORGANIC_JS = r"""
() => {
  for (const a of document.querySelectorAll('div[role="feed"] a.hfpxzc')) {
    if (!/\bSponsored\b/i.test(a.parentElement.innerText)) return a.href;
  }
  return null;
}
"""


def with_english(url: str) -> str:
    """Add hl=en to Google URLs so labels and number formats are predictable."""
    parts = urlparse(url)
    if "google." not in parts.netloc:
        return url
    query = parse_qs(parts.query)
    query["hl"] = ["en"]
    return urlunparse(parts._replace(query=urlencode(query, doseq=True)))


def search_query_from(url: str):
    """If url is a Google Search page (or the captcha page in front of one), return its search text.

    Google Search blocks headless browsers much faster than Maps does, so we never
    scrape Search itself; we look the same name up on Maps instead.
    """
    parts = urlparse(url)
    if "google." not in parts.netloc:
        return None
    if parts.path.startswith("/sorry"):
        cont = parse_qs(parts.query).get("continue", [None])[0]
        if not cont:
            return None
        parts = urlparse(cont)
    if parts.path.startswith("/search"):
        return parse_qs(parts.query).get("q", [None])[0]
    return None


def to_url(target: str) -> str:
    t = target.strip()
    if re.match(r"^(https?://)?([\w-]+\.)*(google\.[a-z.]+|goo\.gl|g\.co|g\.page)/", t, re.I):
        if not t.lower().startswith("http"):
            t = "https://" + t
        q = search_query_from(t)
        if q:
            return to_url(q)
        # A place URL trimmed of its "data=..." part has no place ID and Google shows an
        # empty map, so search for the name at the same coordinates instead.
        m = re.search(r"/maps/place/([^/@?]+)/?(@[-\d.]+,[-\d.]+,[\d.]+z)?", t)
        if m and "data=" not in t:
            name = unquote_plus(m.group(1))
            coords = f"/{m.group(2)}" if m.group(2) else ""
            return f"https://www.google.com/maps/search/{quote_plus(name)}{coords}?hl=en"
        return with_english(t)
    return f"https://www.google.com/maps/search/{quote_plus(t)}?hl=en"


def parse_rating(raw):
    if not raw:
        return None
    try:
        return float(raw.replace(",", "."))
    except ValueError:
        return None


def parse_count(raw):
    if not raw:
        return None
    digits = re.sub(r"\D", "", raw)
    return int(digits) if digits else None


def clean_url(url: str) -> str:
    """Short, stable link for a place: https://maps.google.com/?cid=<id> when the ID is in the URL."""
    m = re.search(r"!1s0x[0-9a-f]+:0x([0-9a-f]+)", url)
    if m:
        return f"https://maps.google.com/?cid={int(m.group(1), 16)}"
    return url.split("?")[0] if "/maps/place/" in url else url


async def handle_consent(page):
    """Google's EU cookie wall: choose 'Reject all' and carry on."""
    if "consent.google." not in page.url:
        return
    for label in ("Reject all", "Alle ablehnen", "Tout refuser", "Rechazar todo"):
        btn = page.get_by_role("button", name=re.compile(label, re.I)).first
        if await btn.count():
            await btn.click()
            await page.wait_for_load_state("domcontentloaded")
            return


PLACE_H1 = "h1.DUwDvf"
HEX_ID = re.compile(r"0x[0-9a-f]{6,}:0x([0-9a-f]{6,})")


async def speed_up(context):
    """Skip images, fonts, video and map tiles; the rating text doesn't need them."""
    async def handler(route):
        if route.request.resource_type in ("image", "media", "font"):
            await route.abort()
        else:
            await route.continue_()
    await context.route("**/*", handler)


def watch_place_ids(page):
    """Remember the place ID from Maps' search data, so we needn't wait for the URL to change."""
    if getattr(page, "_watching_ids", False):
        return
    page._watching_ids = True
    page._place_cid = None

    async def on_response(resp):
        if "tbm=map" not in resp.url and "/maps/preview/place" not in resp.url:
            return
        try:
            m = HEX_ID.search(await resp.text())
        except Exception:
            return
        if m:
            page._place_cid = int(m.group(1), 16)

    page.on("response", on_response)


async def wait_for_place(page, timeout_ms):
    try:
        await page.wait_for_selector(f"{RATING_BOX}, {RESULTS_FEED}, {PLACE_H1}", timeout=timeout_ms)
    except PWTimeout:
        return  # nothing found; extraction will tell
    if not await page.locator(f"{RATING_BOX}, {RESULTS_FEED}").count():
        try:  # place name is up; give the rating a moment (listings with no reviews never get one)
            await page.wait_for_selector(RATING_BOX, timeout=1500)
        except PWTimeout:
            pass


async def scrape_one(page, target, timeout_ms):
    row = {"input": target, "name": None, "rating": None, "reviews": None,
           "address": None, "maps_url": None, "status": "ok"}
    try:
        watch_place_ids(page)
        page._place_cid = None
        await page.goto(to_url(target), wait_until="domcontentloaded", timeout=45000)
        await handle_consent(page)

        # Share links like g.co/kgs/... redirect to Google Search; redo them as a Maps search.
        q = search_query_from(page.url)
        if q:
            await page.goto(to_url(q), wait_until="domcontentloaded", timeout=45000)
            await handle_consent(page)

        if "/sorry/" in page.url:
            row["status"] = "blocked by Google (captcha) - slow down or try later"
            return row

        await wait_for_place(page, timeout_ms)

        # Search matched several places: open the top result that isn't an ad.
        if await page.locator(RESULTS_FEED).count() and not await page.locator(RATING_BOX).count():
            href = await page.evaluate(FIRST_ORGANIC_JS)
            if not href:
                row["status"] = "no results"
                return row
            page._place_cid = None
            await page.goto(with_english(href), wait_until="domcontentloaded", timeout=45000)
            await wait_for_place(page, timeout_ms)
            row["status"] = "ok (top search result)"

        data = await page.evaluate(EXTRACT_JS)
        row["name"] = data.get("name")
        row["rating"] = parse_rating(data.get("rating"))
        row["reviews"] = parse_count(data.get("reviews"))
        row["address"] = data.get("address")

        # Link to the listing: from the URL if Google has already switched to the place URL,
        # else from the place ID in Maps' search data, else wait briefly for the URL to switch.
        if row["name"] and "/maps/place/" not in page.url:
            for _ in range(20):
                if page._place_cid or "/maps/place/" in page.url:
                    break
                await page.wait_for_timeout(250)
        if "!1s0x" in page.url:
            row["maps_url"] = clean_url(page.url)
        elif page._place_cid and row["name"]:
            row["maps_url"] = f"https://maps.google.com/?cid={page._place_cid}"
        else:
            row["maps_url"] = clean_url(page.url)

        if not row["name"]:
            row["status"] = "listing not found"
        elif row["rating"] is None:
            row["reviews"] = row["reviews"] or 0
            row["status"] = "no rating shown"
    except PWTimeout:
        row["status"] = "timed out"
    except Exception as e:  # keep going with the rest of the list
        row["status"] = f"error: {e.__class__.__name__}: {e}".splitlines()[0][:200]
    return row


def find_column(header, keywords):
    for kw in keywords:
        for i, h in enumerate(header):
            if kw in h:
                return i
    return None


def read_inputs(path: Path):
    text = path.read_text(encoding="utf-8-sig")
    if path.suffix.lower() != ".csv":
        return [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]

    rows = list(csv.reader(text.splitlines()))
    if not rows:
        return []
    header = [h.strip().lower() for h in rows[0]]
    col = find_column(header, INPUT_COLUMNS)
    if col is None:  # no recognised header: use the first column, keep every row
        return [r[0].strip() for r in rows if r and r[0].strip()]

    # For name searches, add the city/address so Google finds the right branch.
    extra = find_column(header, LOCATION_COLUMNS)
    targets = []
    for r in rows[1:]:
        value = r[col].strip() if len(r) > col else ""
        if not value:
            continue
        if extra is not None and extra != col and not value.lower().startswith(("http", "www.", "maps.")):
            location = r[extra].strip() if len(r) > extra else ""
            if location and location.lower() not in value.lower():
                value = f"{value} {location}"
        targets.append(value)
    return targets


async def run(targets, out_path, show, delay, timeout_ms):
    results = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=not show)
        context = await browser.new_context(
            locale="en-US",
            viewport={"width": 1366, "height": 900},
            user_agent=("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"),
        )
        await speed_up(context)
        page = await context.new_page()
        for i, target in enumerate(targets, 1):
            row = await scrape_one(page, target, timeout_ms)
            results.append(row)
            stars = f"{row['rating']}★" if row["rating"] is not None else "-"
            count = "-" if row["reviews"] is None else \
                f"{row['reviews']:,} review{'' if row['reviews'] == 1 else 's'}"
            print(f"[{i}/{len(targets)}] {row['name'] or target}  |  {stars}  |  {count}  |  {row['status']}",
                  file=sys.stderr, flush=True)
            if row["status"].startswith("blocked"):
                print("Google is showing a captcha; stopping early. Try again later with a bigger --delay.",
                      file=sys.stderr)
                break
            if i < len(targets):
                await asyncio.sleep(random.uniform(delay, delay * 1.75))
        await browser.close()

    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:  # BOM so Excel shows accents right
        writer = csv.DictWriter(f, fieldnames=["input", "name", "rating", "reviews", "address", "maps_url",
                                               "status"])
        writer.writeheader()
        writer.writerows(results)
    return results


def main():
    ap = argparse.ArgumentParser(description="Get star rating + review count from Google Maps listings.")
    ap.add_argument("targets", nargs="*", help="Google Maps URLs, share links, or search text")
    ap.add_argument("-i", "--input", type=Path, help=".txt (one per line) or .csv (column named url/query/name)")
    ap.add_argument("-o", "--output", type=Path, default=Path("results.csv"), help="CSV to write (default: results.csv)")
    ap.add_argument("--show", action="store_true", help="show the browser window")
    ap.add_argument("--delay", type=float, default=2.0, help="seconds to wait between listings (default: 2)")
    ap.add_argument("--timeout", type=float, default=15, help="seconds to wait for a listing to load (default: 15)")
    args = ap.parse_args()

    targets = list(args.targets)
    if args.input:
        targets += read_inputs(args.input)
    if not targets:
        ap.error("give at least one listing, or -i FILE")

    results = asyncio.run(run(targets, args.output, args.show, args.delay, int(args.timeout * 1000)))
    print(f"\nSaved {len(results)} row(s) to {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
