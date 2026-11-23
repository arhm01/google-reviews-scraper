# Google Reviews Scraper

Get the **Google star rating**, **number of reviews** and **Google Maps link** for every business
in a Google Sheet, a CSV, or a plain list of names or Maps links. No API key needed. Works on
**Mac and Windows**, with double-click launchers for non-technical users.

> **Using an AI assistant?** Give it this repo's link. [AGENTS.md](AGENTS.md) has step-by-step
> instructions for AI agents to set it up and run it for you.

## What it does

- Reads your list (for example an Apollo export with one row per contact) and looks up each
  **unique business once** on Google Maps.
- Adds four columns to every row: **Google Rating**, **Google Reviews**, **Google Business Link**
  and **Match Check**, plus Google's listing name and address so you can verify.
- **Checks every match**: compares Google's listing name and address with your row and flags the
  ones that don't agree, so a wrong business never silently gets a rating.
- **Saves progress after every lookup.** If it's interrupted, run it again and it carries on.
- Respects Google's rate limits: when Google shows a captcha it pauses and slows down. It never
  tries to solve or get around captchas.

## Quick start (no coding)

1. On this page click **Code → Download ZIP**, then unzip it.
2. Double-click **`Get Google Reviews (Mac).command`** or **`Get Google Reviews (Windows).bat`**.
   The first run installs what it needs. Windows needs [Python](https://www.python.org/downloads/)
   installed first, with "Add python.exe to PATH" ticked.
3. Paste the link to a Google Sheet tab (shared as **Anyone with the link → Viewer**) and type a name.
4. Your results appear in `Results/<name>.csv`. To put them in Google Sheets:
   **File → Import → Upload → Insert new sheet(s)**.

Full step-by-step guide with troubleshooting: **[HOW TO USE.txt](HOW%20TO%20USE.txt)**.

## Input format

Row 1 must be the column headers. Columns are found by their header names (capitals don't matter):

| Column | Needed? | Header names it recognises | Example |
|---|---|---|---|
| Business name | **Yes**, unless there's a Maps link column | Company Name, Business Name, Facility Name, Practice Name, Company, Organization | `Lakeview Dental Care` |
| Google Maps link | Optional, the most accurate | Google Maps URL, Maps URL, Map URL, Google Maps Link | `https://www.google.com/maps/...` |
| Address | Optional, strongly recommended | Company Address, Street Address, Address | `63 N Lakeview Dr, Gibbsboro, NJ 08026` |
| City | Optional | City, Company City, Location | `Gibbsboro` |
| State | Optional | State, Company State | `New Jersey` or `NJ` |
| ZIP | Optional | Zip, Zip Code, Postal Code | `08026` |

A plain `Name` header isn't recognised; use `Company Name` or `Business Name`. All other
columns are kept and copied to the output.

**Accuracy:** a Maps link matches exactly. Name plus street address matched about 85–90% of rows in
testing. Name plus city/state works but flags more rows for checking. Name only can match a
same-named business elsewhere.

## Output

Your original columns, plus:

| Column | Example | Meaning |
|---|---|---|
| Google Rating | `4.8` | Blank if the listing has no reviews or wasn't found |
| Google Reviews | `1120` | Number of reviews |
| Google Business Link | `https://maps.google.com/?cid=…` | Opens the exact listing |
| Match Check | `match` | `match` · `match (no reviews on Google)` · `check: Google shows "…"` (different name or town, so verify) · `not found on Google Maps` |
| Google Listing Name, Google Address | | What Google shows |

## Command line

Setup (once). macOS / Linux:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m playwright install chromium
```

Windows:

```bat
py -3 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m playwright install chromium
```

Run (on Windows use `.venv\Scripts\python` in place of `.venv/bin/python`):

```bash
# A Google Sheet tab (link copied while the tab is open)
.venv/bin/python sheet_reviews.py "https://docs.google.com/spreadsheets/d/<id>/edit#gid=<tab>" -o out/dental.csv

# A CSV file
.venv/bin/python sheet_reviews.py --csv export.csv -o out/results.csv

# Several tabs listed in a text file (format in run_all_tabs.py)
.venv/bin/python run_all_tabs.py tabs.txt

# A few businesses or Maps links, or a .txt list
.venv/bin/python google_reviews.py "Joe's Pizza 7 Carmine St New York" "https://maps.app.goo.gl/XXXX"
.venv/bin/python google_reviews.py -i listings.txt -o results.csv
```

`sheet_reviews.py` options:

| Option | Default | What it does |
|---|---|---|
| `--csv FILE` | | Use a CSV file instead of a sheet link |
| `-o FILE` | `sheet_reviews.csv` | Output CSV |
| `--cache FILE` | next to the output | Progress file; can be shared between tabs |
| `--default-state NAME` | | State to search with when the sheet has no state column |
| `--workers N` | `4` | Max lookups at once; drops by one after each captcha |
| `--cooldown MIN` | `10` | Minutes to pause after a captcha (longer if it repeats) |
| `--limit N` | | Only do the first N businesses (testing) |
| `--show` | off | Show the browser window |

Exit codes: `0` done · `3` Google kept blocking, so rerun later (progress is saved) · other: error.

## Speed

Roughly **100 businesses every 5–10 minutes**. Google limits how fast one computer can look things
up, so expect occasional 10-minute pauses on big lists. For thousands of lookups at a time, the
official [Google Places API](https://developers.google.com/maps/documentation/places/web-service/overview)
is faster (paid, needs an API key).

## How it works

A headless Chromium browser (via [Playwright](https://playwright.dev/python/)) searches Google
Maps for each business name plus address, opens the top non-sponsored result when several match,
and reads the rating, review count, address and place ID. The place ID becomes the short
`maps.google.com/?cid=` link. A name-similarity and address check decides `match` or `check`.

## Files

| File | What it is |
|---|---|
| `Get Google Reviews (Mac).command`, `Get Google Reviews (Windows).bat` | Double-click launchers (first-run setup included) |
| `start.py` | The questions the launchers ask |
| `sheet_reviews.py` | Whole sheet tab or CSV: column detection, dedupe, match check, progress, pacing |
| `google_reviews.py` | Core Google Maps lookup; also a simple CLI for lists |
| `run_all_tabs.py` | Runs several tabs in a row from a text file |
| `HOW TO USE.txt` | Plain-language guide |
| `AGENTS.md` | Instructions for AI assistants |

## Responsible use

This reads public Google Maps pages the way a browser does. Google's Terms of Service restrict
automated access, so use it at a modest scale and at your own risk; for commercial-scale use,
prefer the official Places API. Results come from Google and can be out of date or matched to the
wrong business, so check the rows marked `check`.

## License

[MIT](LICENSE)
