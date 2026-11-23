# Instructions for AI assistants

A user has given you this repository and wants the **Google star rating, review count and Google
Maps link** for a list of businesses (usually a Google Sheet tab, often an Apollo export).
This file tells you how to set it up, run it and hand back the results. Human docs:
[README.md](README.md) and [HOW TO USE.txt](HOW%20TO%20USE.txt).

## 0. First decide what you can do

- **You can run shell commands on the user's computer** (Claude Code, Codex, Cursor/Windsurf agent,
  a terminal tool, etc.): follow sections 1–5 and do the whole job yourself.
- **You can't run commands** (plain chat): don't pretend to run it. Walk the user through
  [HOW TO USE.txt](HOW%20TO%20USE.txt): download the ZIP from GitHub, double-click
  `Get Google Reviews (Mac).command` or `Get Google Reviews (Windows).bat`, paste the sheet link.
- Ask the user only for what you can't find yourself: the sheet/tab link (or file), and permission
  before writing into their Google Sheet.

## 1. Get the code

```bash
git clone https://github.com/arhm01/google-reviews-scraper.git
cd google-reviews-scraper
```

(No git? Download `https://github.com/arhm01/google-reviews-scraper/archive/refs/heads/main.zip` and unzip.)

## 2. Set up once (Python 3.9+, internet)

macOS / Linux:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m playwright install chromium        # Linux servers: add --with-deps
```

Windows (PowerShell or cmd):

```bat
py -3 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m playwright install chromium
```

Below, `PY` means `.venv/bin/python` (macOS/Linux) or `.venv\Scripts\python` (Windows).

Smoke test (about 15 seconds), which should print roughly `Eiffel Tower | 4.7★ | 500,000+ reviews | ok`:

```bash
PY google_reviews.py "Eiffel Tower" -o smoke_test.csv
```

## 3. Choose the command for the user's input

| The user has | Run |
|---|---|
| A Google Sheet tab | `PY sheet_reviews.py "<link to the tab>" -o out/<name>.csv` |
| A CSV / Excel export | Save as CSV, then `PY sheet_reviews.py --csv <file.csv> -o out/<name>.csv` |
| Several tabs | Write `tabs.txt` (see the docstring in `run_all_tabs.py`), then `PY run_all_tabs.py tabs.txt` |
| A few names or Maps links | `PY google_reviews.py "Joe's Pizza 7 Carmine St New York" "https://maps.app.goo.gl/..." -o out.csv` |

Google Sheet notes:

- The script downloads the tab's CSV export, so the sheet must be shared as
  **"Anyone with the link" → Viewer**. If it isn't, it exits with "Couldn't download the sheet".
  Then either ask the user to change sharing, or (if you have Google Drive/Sheets access) export the
  tab to CSV yourself and use `--csv`.
- The link must point at the tab: it contains `gid=<number>` (copied while the tab is open).
  Without it the first tab is used.

Input format the script expects:

- **Row 1 = headers.** One row per contact or business; duplicate businesses are looked up once.
- Columns are found by header (case-insensitive; exact match first, then "contains"):
  - **name** (required unless there's a Maps link column): `Company Name`, `Business Name`,
    `Facility Name`, `Practice Name`, `Company`, `Organization`. A bare `Name` is **not** recognised.
  - **Maps link** (optional, exact match): `Google Maps URL`, `Maps URL`, `Map URL`, `Google Maps Link`.
  - **address** (optional, best accuracy): `Company Address`, `Street Address`, `Address`.
    Full address or street only.
  - **city**: `City`, `Company City`, `Location`. **state**: `State`, `Company State`.
    **ZIP**: `Zip`, `Zip Code`, `Postal Code`.
- If the tab has no state column but you know the region, add `--default-state "Florida"`.
- Other columns are passed through unchanged.

## 4. Run it (long-running, so run in the background and watch the log)

- Speed: roughly 100 unique businesses per 5–10 minutes. Each finished business prints a line
  like `[37/524] Lakeview Dental Care | 4.8★ | 1120 reviews | match`.
- Google rate-limits by speed. The script starts with 4 parallel workers; when Google shows a
  captcha it pauses 10 minutes (longer if it repeats) and drops one worker. **Do not try to get
  around captchas** (no captcha solvers, no proxy/IP rotation). If you need much higher volume,
  tell the user about the official Google Places API instead.
- Exit codes: `0` finished · `3` Google kept blocking after many pauses; rerun the same command
  later · anything else is an error (read the message).
- Progress is saved after every lookup in the cache file (`--cache`, default `<output>.cache.json`).
  Rerunning the same command resumes. One cache can be shared across tabs.
- The script keeps the computer awake by itself on macOS and Windows while it runs.
- Don't use `start.py` or the `.command`/`.bat` launchers yourself: they're interactive, for humans.

Useful options for `sheet_reviews.py`: `--limit N` (test on the first N businesses),
`--workers N` (max parallel lookups, default 4), `--cooldown MIN` (default 10),
`--timeout SEC` (default 10), `--show` (visible browser).

## 5. Check and hand back the results

Output CSV (UTF-8 with BOM, same rows and order as the input) = all input columns plus:

| Column | Meaning |
|---|---|
| Google Rating | e.g. `4.8`; blank if the listing has no reviews or wasn't found |
| Google Reviews | review count, e.g. `1120` |
| Google Business Link | `https://maps.google.com/?cid=…`, which opens the exact listing |
| Match Check | `match` · `match (no reviews on Google)` · `check: Google shows "…"` (name or town differs, so verify) · `not found on Google Maps` |
| Google Listing Name / Google Address | what Google shows, to help verify |

Before reporting:

1. Count the Match Check values and give the user the numbers. Tell them `check:` rows need a
   human look via the link, and why (often the same practice under a doctor's or parent brand's
   name, sometimes a wrong business).
2. Spot-check 2–3 `match` rows by opening their Google Business Link.
3. Putting it back into Google Sheets:
   - If you have a Google Sheets tool with write access **and the user agrees**, write the four
     columns `Google Rating, Google Reviews, Google Business Link, Match Check` into empty columns
     to the right of the existing data. Rows line up 1:1 with the input (row 1 = header). First
     re-read the tab and confirm the name column still matches row by row, in case someone sorted
     it meanwhile. Check the target columns are empty before writing.
   - Otherwise tell the user: Google Sheets → File → Import → Upload → "Insert new sheet(s)".

## Gotchas

- Vague searches (name only) can match a same-named business near **the computer running the
  script**, because Google biases to the searcher's location. The location check flags these as `check:`.
- Tabs with only city/state (no street address) get many more `check:` flags. That's expected.
- `out/`, `Results/` and `*.cache.json` contain the user's data and are git-ignored. Never commit them.

## Files

| File | What it is |
|---|---|
| `google_reviews.py` | Core scraper: one lookup per business name / URL; also a simple CLI for lists |
| `sheet_reviews.py` | Whole Google Sheet tab or CSV: column detection, dedupe, match check, cache, pacing |
| `run_all_tabs.py` | Runs `sheet_reviews.py` over a list of tabs from a text file |
| `start.py` | Interactive prompts used by the double-click launchers |
| `Get Google Reviews (Mac).command` / `(Windows).bat` | Double-click launchers with one-time setup |
| `listings.txt` | Example input for `google_reviews.py -i` |
