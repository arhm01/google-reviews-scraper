#!/usr/bin/env python3
"""
The questions-and-answers part of the "Get Google Reviews" launchers (Mac and Windows).

Asks for a Google Sheet tab link and a name, runs sheet_reviews.py on it, and shows the
results file when it's done. The launchers handle the one-time setup, then run this.
"""

import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "Results"


def ask(prompt):
    try:
        return input(prompt)
    except EOFError:
        return ""


def is_locked(path):
    if not path.exists():
        return False
    try:
        with open(path, "a"):
            return False
    except PermissionError:
        return True


def reveal(path):
    """Open the folder with the results file selected (Finder on Mac, File Explorer on Windows)."""
    if os.environ.get("NO_OPEN"):
        return
    try:
        if sys.platform == "win32":
            subprocess.Popen(f'explorer /select,"{path}"')
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path.parent)])
    except Exception:
        pass


def run_once():
    print("-" * 50)
    print("Paste the link to the Google Sheet tab, then press Enter.")
    print("(Open the tab you want first, then copy the link from the address bar.)")
    print("To quit, just press Enter.")
    link = ask("> ").strip()
    if not link:
        return False
    if "docs.google.com/spreadsheets" not in link:
        print()
        print("That doesn't look like a Google Sheets link. It should start with")
        print("https://docs.google.com/spreadsheets/ ... Please try again.")
        print()
        return True

    print()
    print("What should the results file be called? (for example: Dental)")
    name = re.sub(r"[^\w \-]", "", ask("> ")).strip() or "Results"
    out = RESULTS / f"{name}.csv"
    while is_locked(out):  # Excel on Windows locks files it has open
        print()
        print(f"{name}.csv is open in another program (probably Excel).")
        print("Close it, then press Enter.")
        ask("")

    print()
    print("Working on it. Keep this window open, and keep the laptop open and plugged in.")
    print("Each line below is one business: name | stars | number of reviews | match check.")
    print(flush=True)
    try:
        code = subprocess.call([sys.executable, str(HERE / "sheet_reviews.py"), link,
                                "-o", str(out), "--cache", str(RESULTS / "progress.json")])
    except KeyboardInterrupt:
        code = 130

    print()
    if code == 0:
        print(f"Done! Your results are in the Results folder: {name}.csv")
        reveal(out)
    elif code == 3:
        print("Google is blocking lookups for now, so this stopped partway.")
        print("Nothing is lost. Try again in an hour with the same link and the same name,")
        print("and it will carry on from where it stopped.")
        if out.exists():
            reveal(out)
    elif code == 130:
        print("Stopped. Run it again with the same link and the same name to carry on.")
    else:
        print("Something went wrong (see the message above).")
        print("Most often the sheet isn't shared: in Google Sheets click Share, set")
        print("'General access' to 'Anyone with the link' (Viewer), and try again.")
    print()
    return True


def main():
    os.chdir(HERE)
    RESULTS.mkdir(exist_ok=True)
    print("=" * 50)
    print("   Google Reviews lookup")
    print("=" * 50)
    print()
    try:
        while run_once():
            pass
    except KeyboardInterrupt:
        print()
    print("Bye!")


if __name__ == "__main__":
    main()
