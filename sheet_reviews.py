#!/usr/bin/env python3
"""
Add Google rating + review count to every business in a Google Sheet tab (or CSV export).

Works with Apollo-style exports (one row per contact) and similar lists. It finds the columns
by their headers: company / facility name, address, city, state, ZIP, or a Google Maps URL.
Each unique business is looked up once and the result is copied to every row for it.

Usage:
  python sheet_reviews.py "https://docs.google.com/spreadsheets/d/<id>/edit#gid=0" -o out/dental.csv
  python sheet_reviews.py --csv export.csv -o out.csv
  python sheet_reviews.py "<sheet link>#gid=889078504" -o out/alf_fl.csv --default-state Florida

The sheet must be shared as "anyone with the link can view" for the link form to work;
otherwise download the tab as CSV (File > Download > CSV) and use --csv.

Progress is saved to the cache file after every lookup (one cache can be shared by many tabs,
so a business that appears in two tabs is only looked up once). If Google shows a captcha the
script pauses for --cooldown minutes and carries on; stop it any time and rerun to resume.
"""

import argparse
import asyncio
import csv
import io
import json
import os
import random
import re
import subprocess
import sys
import time
import urllib.request
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from playwright.async_api import async_playwright

from google_reviews import scrape_one, speed_up


# Windows consoles may not be able to show every character (like the star); never crash over it.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")
    except Exception:
        pass


def keep_awake():
    """Stop the computer from going to sleep while lookups run (released when the script ends)."""
    try:
        if sys.platform == "win32":
            import ctypes
            ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001
            ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
        elif sys.platform == "darwin":
            subprocess.Popen(["caffeinate", "-i", "-w", str(os.getpid())],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass

# What goes back into the sheet, then extra columns kept in the CSV only.
SHEET_COLUMNS = ["Google Rating", "Google Reviews", "Google Business Link", "Match Check"]
EXTRA_COLUMNS = ["Google Listing Name", "Google Address"]

NAME_HEADERS = ("company name", "companyname", "company name for emails", "facility name",
                "business name", "practice name", "company", "organization")
URL_HEADERS = ("google map url", "google maps url", "maps url", "map url", "google maps link")
ADDRESS_HEADERS = ("company address", "street address", "address")
CITY_HEADERS = ("company city", "city", "location")
STATE_HEADERS = ("company state", "state")
ZIP_HEADERS = ("zip", "zip code", "postal code")

# Words too common in business names to prove two names are the same business.
GENERIC = {
    "the", "of", "and", "at", "in", "a", "llc", "pc", "pllc", "inc", "ltd", "co", "pa", "dds", "dmd", "md",
    "dr", "dental", "dentistry", "dentist", "dentists", "family", "care", "center", "centre", "centers",
    "group", "associates", "clinic", "clinics", "office", "practice", "health", "healthcare", "medical",
    "wellness", "physical", "therapy", "rehab", "rehabilitation", "institute", "services", "specialists",
    "living", "assisted", "senior", "spa", "med", "surgery", "surgeons", "surgical", "general", "cosmetic",
    "urgent", "treatment", "recovery", "clinic", "llp", "corp", "corporation", "company",
}


def save_json(path, data):
    """Save progress safely. On Windows, antivirus or OneDrive can lock a file for a moment,
    so retry briefly instead of crashing; the next save catches up if this one is skipped."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    for _ in range(10):
        try:
            tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
            os.replace(tmp, path)
            return
        except PermissionError:
            time.sleep(0.3)


# ---------- reading the sheet ----------

def sheet_csv_url(url: str) -> str:
    m = re.search(r"/spreadsheets/d/([\w-]+)", url)
    if not m:
        sys.exit("That doesn't look like a Google Sheets link.")
    gid = re.search(r"gid=(\d+)", url)
    return f"https://docs.google.com/spreadsheets/d/{m.group(1)}/export?format=csv&gid={gid.group(1) if gid else '0'}"


def load_rows(sheet_url, csv_path):
    if csv_path:
        text = Path(csv_path).read_text(encoding="utf-8-sig")
    else:
        try:
            with urllib.request.urlopen(sheet_csv_url(sheet_url), timeout=60) as resp:
                if "text/csv" not in resp.headers.get("Content-Type", ""):
                    raise ValueError("not CSV")
                text = resp.read().decode("utf-8-sig")
        except Exception as e:
            sys.exit(f"Couldn't download the sheet ({e}). Share it as 'anyone with the link can view', "
                     "or download the tab as CSV and pass it with --csv.")
    reader = csv.DictReader(io.StringIO(text))
    return reader.fieldnames or [], list(reader)


def pick(fieldnames, candidates):
    lower = {f.lower().strip(): f for f in fieldnames}
    for c in candidates:            # exact header first
        if c in lower:
            return lower[c]
    for c in candidates:            # then a header that contains the word(s)
        for low, orig in lower.items():
            if c in low:
                return orig
    return None


# ---------- building searches and checking matches ----------

def clean_name(name):
    # "Word Therapy Center | Florida | Pediatric Speech Therapy" -> "Word Therapy Center"
    return re.split(r"\s+[|–]\s+|\s+-\s+(?=[A-Z])", name.strip())[0].strip()


def clean_address(addr):
    addr = re.sub(r",\s*United States\b", "", addr or "", flags=re.I)
    return re.sub(r",\s*(\d{5})(-\d{4})?\s*$", r" \1", addr).strip(" ,")


def queries_for(name, address, city, state, zip_code):
    """Most specific search first, then a looser name + city/state search as the fallback."""
    address = clean_address(address)
    loose = ", ".join(p for p in (name, city, state) if p)
    if address and re.match(r"^\d", address):
        if "," in address:                                  # full address: "63 N Lakeview Dr, Gibbsboro, NJ 08026"
            first = f"{name}, {address}"
        else:                                               # street only: "4902 BAYSHORE BLVD"
            first = ", ".join(p for p in (name, address, city, f"{state} {zip_code}".strip()) if p)
        return [first, loose] if loose != first else [first]
    if address and address.lower() not in loose.lower():    # city/state-level address
        return [f"{name}, {address}", loose]
    return [loose]


def expected_places(address, city, zip_code):
    """ZIP codes and town names the Google listing's address should contain."""
    places = set()
    addr = address or ""
    for z in (re.findall(r"\b(\d{5})(?:-\d{4})?\s*$", addr.strip()) + [zip_code or ""]):
        if re.fullmatch(r"\d{5}", z.strip()[:5] or "x"):
            places.add(z.strip()[:5])
    parts = [p.strip() for p in re.sub(r",\s*United States\b", "", addr, flags=re.I).split(",") if p.strip()]
    if len(parts) > 1 or (parts and not re.match(r"^\d", parts[0])):
        town = parts[1] if re.match(r"^\d", parts[0]) else parts[0]
        if not re.match(r"^\d", town):
            places.add(re.sub(r"\s+township$", "", town, flags=re.I).lower())
    if city and city.strip():
        places.add(city.strip().lower())
    return places


def tokens(s):
    return set(re.findall(r"[a-z0-9]+", re.sub(r"[’'`]", "", (s or "").lower())))


def name_similarity(a, b):
    if not a or not b:
        return 0.0
    ta, tb = tokens(a), tokens(b)
    da, db = ta - GENERIC, tb - GENERIC
    if da and db:
        overlap = len(da & db) / min(len(da), len(db))
    else:
        overlap = len(ta & tb) / max(1, min(len(ta), len(tb)))
    ratio = SequenceMatcher(None, " ".join(sorted(ta)), " ".join(sorted(tb))).ratio()
    return max(overlap, ratio)


def judge(company, result, places, trusted_url=False):
    """Returns 'match', 'match, no rating', 'check name', 'check location', or a failure status."""
    status = result["status"]
    if status.startswith("blocked"):
        return "blocked"
    if not status.startswith(("ok", "no rating")):
        return status  # listing not found / timed out / error
    rated = status.startswith("ok")
    if not trusted_url:
        if name_similarity(company, result["name"]) < 0.6:
            return "check name"
        found_addr = (result.get("address") or "").lower()
        if found_addr and places and not any(p in found_addr for p in places):
            return "check location"
    return "match" if rated else "match, no rating"


def sheet_note(res):
    """Short text for the sheet's Match Check column."""
    check = res["check"]
    if check == "match":
        return "match"
    if check == "match, no rating":
        return "match (no reviews on Google)"
    if check == "check name":
        return f"check: Google shows \"{res['name']}\""
    if check == "check location":
        return f"check: Google shows it at {res.get('address') or 'a different address'}"
    if check == "listing not found" or check == "no results":
        return "not found on Google Maps"
    return f"lookup failed ({check}), rerun to retry"


# ---------- running ----------

def new_context_args():
    return dict(locale="en-US", viewport={"width": 1366, "height": 900},
                user_agent=("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                            "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"))


async def lookup(page, job, args):
    """Try each query for one business; keep the first confident match, else the best attempt."""
    best = None
    for i, q in enumerate(job["queries"]):
        if i:
            await asyncio.sleep(random.uniform(args.delay, args.delay * 1.75))
        result = await scrape_one(page, q, int(args.timeout * 1000))
        result["query"] = q
        result["check"] = judge(job["company"], result, job["places"], trusted_url=job["trusted"])
        if result["check"] == "blocked":
            return None
        if best is None or (not best["check"].startswith("match") and result["check"].startswith("match")) \
                or (best["check"] not in ("check name", "check location") and result["check"].startswith("check")):
            best = result
        if best["check"].startswith("match"):
            break
    return best


async def worker(wid, context, queue, cache, cache_path, counter, blocked, args):
    page = await context.new_page()
    await asyncio.sleep(wid * 2)
    while not queue.empty() and not blocked.is_set():
        job = queue.get_nowait()
        best = await lookup(page, job, args)
        if best is None:
            queue.put_nowait(job)   # retry after the cooldown
            blocked.set()
            break
        cache[job["key"]] = best
        save_json(cache_path, cache)
        counter[0] += 1
        stars = f"{best['rating']}★" if best["rating"] is not None else "-"
        print(f"[{counter[0]}/{counter[1]}] {job['company'][:40]:<40} | {stars:>5} | "
              f"{best['reviews'] or 0:>6} reviews | {best['check']}", file=sys.stderr, flush=True)
        await asyncio.sleep(random.uniform(args.delay, args.delay * 1.75))
    await page.close()


async def run_lookups(jobs, cache, cache_path, args):
    """Run with as many workers as Google tolerates: on a captcha, pause and drop one worker.

    The worker count is saved in a small pace file so the next tab starts at the same pace.
    """
    queue = asyncio.Queue()
    for job in jobs:
        queue.put_nowait(job)
    counter = [0, len(jobs)]
    pace_path = cache_path.with_name("pace.json")
    try:
        workers = min(args.workers, json.loads(pace_path.read_text(encoding="utf-8"))["workers"])
    except Exception:
        workers = args.workers
    pauses = streak = 0
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=not args.show)
        while not queue.empty():
            blocked = asyncio.Event()
            context = await browser.new_context(**new_context_args())
            await speed_up(context)
            done_before = counter[0]
            await asyncio.gather(*(worker(i, context, queue, cache, cache_path, counter, blocked, args)
                                   for i in range(workers)))
            await context.close()
            if not blocked.is_set():
                break
            pauses += 1
            streak = streak + 1 if counter[0] - done_before < 5 else 1  # blocked again almost at once?
            if pauses > args.max_pauses:
                print("Still blocked after many pauses; stopping. Rerun later to finish.", file=sys.stderr)
                break
            workers = max(1, workers - 1)
            pace_path.write_text(json.dumps({"workers": workers}), encoding="utf-8")
            wait = args.cooldown * min(streak, 3)
            resume = time.strftime("%H:%M", time.localtime(time.time() + wait * 60))
            print(f"  Google showed a captcha. Pausing {wait:g} min (until about {resume}), "
                  f"then continuing with {workers} worker(s).", file=sys.stderr, flush=True)
            await asyncio.sleep(wait * 60)
        await browser.close()
    return queue.empty()


def main():
    ap = argparse.ArgumentParser(description="Add Google rating + review count to a sheet of businesses.")
    ap.add_argument("sheet_url", nargs="?", help="Google Sheets link (include the #gid=... of the tab)")
    ap.add_argument("--csv", help="use a downloaded CSV instead of the sheet link")
    ap.add_argument("-o", "--output", default="sheet_reviews.csv", help="output CSV (default: sheet_reviews.csv)")
    ap.add_argument("--cache", help="progress file, can be shared between tabs (default: next to the output)")
    ap.add_argument("--default-state", default="", help="state to search with when the sheet has no state column")
    ap.add_argument("--workers", type=int, default=4, help="max lookups at once; drops by one after each captcha (default: 4)")
    ap.add_argument("--delay", type=float, default=0.5, help="seconds between lookups per worker, randomised up to 1.75x (default: 0.5)")
    ap.add_argument("--timeout", type=float, default=10, help="seconds to wait for a listing (default: 10)")
    ap.add_argument("--cooldown", type=float, default=10, help="minutes to pause after a captcha; longer if it repeats (default: 10)")
    ap.add_argument("--max-pauses", type=int, default=12, help="give up after this many captcha pauses (default: 12)")
    ap.add_argument("--limit", type=int, help="only look up the first N businesses (for a test run)")
    ap.add_argument("--show", action="store_true", help="show the browser")
    args = ap.parse_args()
    if not args.sheet_url and not args.csv:
        ap.error("give a Google Sheets link or --csv FILE")

    fieldnames, rows = load_rows(args.sheet_url, args.csv)
    cols = {
        "name": pick(fieldnames, NAME_HEADERS), "url": pick(fieldnames, URL_HEADERS),
        "address": pick(fieldnames, ADDRESS_HEADERS), "city": pick(fieldnames, CITY_HEADERS),
        "state": pick(fieldnames, STATE_HEADERS), "zip": pick(fieldnames, ZIP_HEADERS),
    }
    if not cols["name"] and not cols["url"]:
        sys.exit(f"No company/business name or Google Maps URL column found in: {fieldnames}")
    print("Using columns: " + ", ".join(f"{k}={v!r}" for k, v in cols.items() if v), file=sys.stderr)

    def get(r, k):
        return (r.get(cols[k]) or "").strip() if cols[k] else ""

    def job_for(r):
        name = clean_name(get(r, "name"))
        url = get(r, "url")
        if url.startswith("http") and "google." in url:
            return {"key": "url|" + url, "company": name or url, "queries": [url], "places": set(),
                    "trusted": True}
        if not name:
            return None
        address, city, zip_code = get(r, "address"), get(r, "city"), get(r, "zip")
        state = get(r, "state") or args.default_state
        key = "|".join(x.lower() for x in ([name, address] if address else [name, city, state]))
        return {"key": key, "company": name, "queries": queries_for(name, address, city, state, zip_code),
                "places": expected_places(address, city, zip_code), "trusted": False}

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path = Path(args.cache) if args.cache else out_path.with_suffix(".cache.json")
    cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}

    row_jobs = [job_for(r) for r in rows]
    jobs, seen, unique = [], set(), set()
    for job in row_jobs:
        if not job:
            continue
        unique.add(job["key"])
        if job["key"] in cache or job["key"] in seen:
            continue
        seen.add(job["key"])
        jobs.append(job)
    if args.limit is not None:
        jobs = jobs[:args.limit]
    print(f"{len(rows)} rows, {len(unique)} unique businesses, {len(unique) - len(seen)} already in the cache, "
          f"{len(jobs)} to look up now.", file=sys.stderr, flush=True)

    if jobs:
        keep_awake()
    finished = asyncio.run(run_lookups(jobs, cache, cache_path, args)) if jobs else True

    out_fields = fieldnames + [c for c in SHEET_COLUMNS + EXTRA_COLUMNS if c not in fieldnames]
    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:  # BOM so Excel shows accents right
        w = csv.DictWriter(f, fieldnames=out_fields)
        w.writeheader()
        for r, job in zip(rows, row_jobs):
            res = cache.get(job["key"]) if job else None
            if res:
                found = res["check"] not in ("listing not found", "no results") and res["name"]
                r["Google Rating"] = res["rating"] if res["rating"] is not None else ""
                r["Google Reviews"] = res["reviews"] if found and res["reviews"] is not None else ""
                r["Google Business Link"] = res["maps_url"] if found else ""
                r["Match Check"] = sheet_note(res)
                r["Google Listing Name"] = res["name"] or ""
                r["Google Address"] = res.get("address") or ""
            w.writerow(r)

    counts = {}
    for job in {j["key"]: j for j in row_jobs if j}.values():
        res = cache.get(job["key"])
        label = res["check"] if res else "not looked up yet"
        counts[label] = counts.get(label, 0) + 1
    print(f"\nSaved {out_path}. {counts}", file=sys.stderr)
    if not finished:
        print("Not finished (Google kept blocking). Run the same command again later to continue.",
              file=sys.stderr)
    sys.exit(0 if finished else 3)


if __name__ == "__main__":
    main()
