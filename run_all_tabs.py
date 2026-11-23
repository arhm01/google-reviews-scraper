#!/usr/bin/env python3
"""
Run sheet_reviews.py over several Google Sheet tabs, one after another.

List the tabs in a text file, one per line:

    Dental    | https://docs.google.com/spreadsheets/d/<sheet id>/edit#gid=0
    ALF - FL  | https://docs.google.com/spreadsheets/d/<sheet id>/edit#gid=889078504 | Florida

    name      | link to the tab (copied while the tab is open)       | optional: state to assume
              |                                                       | when the tab has no state column

Lines starting with # are ignored. Then run:

    .venv/bin/python run_all_tabs.py tabs.txt          (Windows: .venv\\Scripts\\python run_all_tabs.py tabs.txt)

Results go to out/<name>.csv. All tabs share out/cache.json, so a business that appears in
several tabs is looked up once, and rerunning resumes where it stopped. A line
"TAB_DONE <name>" is printed after each tab, which is handy for watching progress.
"""

import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def slug(name):
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "tab"


def read_tabs(path):
    tabs = []
    for n, line in enumerate(Path(path).read_text(encoding="utf-8-sig").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split("|")]
        link = next((p for p in parts if "docs.google.com/spreadsheets" in p), None)
        if not link:
            sys.exit(f"Line {n} of {path} has no Google Sheets link: {line}")
        i = parts.index(link)
        name = parts[0] if i > 0 else f"tab_{len(tabs) + 1}"
        state = parts[i + 1] if len(parts) > i + 1 else ""
        tabs.append((name, link, state))
    return tabs


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    tabs = read_tabs(sys.argv[1])
    (HERE / "out").mkdir(exist_ok=True)
    (HERE / "out" / "pace.json").unlink(missing_ok=True)  # start each run at full speed
    for name, link, state in tabs:
        print(f"TAB_START {name}", flush=True)
        out = HERE / "out" / f"{slug(name)}.csv"
        cmd = [sys.executable, str(HERE / "sheet_reviews.py"), link,
               "-o", str(out), "--cache", str(HERE / "out" / "cache.json")]
        if state:
            cmd += ["--default-state", state]
        code = subprocess.call(cmd, cwd=HERE)
        if code == 3:
            print(f"TAB_BLOCKED {name}: Google kept blocking. Rerun later to resume.", flush=True)
            sys.exit(3)
        if code != 0:
            print(f"TAB_FAILED {name} (exit {code})", flush=True)
            continue
        print(f"TAB_DONE {name} -> {out.relative_to(HERE)}", flush=True)
    print("ALL_DONE", flush=True)


if __name__ == "__main__":
    main()
