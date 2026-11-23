#!/bin/bash
# Double-click this file to look up Google ratings for a Google Sheet tab (Mac).

cd "$(dirname "$0")" || exit 1
clear

finish() {
  echo
  read -r -p "Press Enter to close this window." _
  exit "${1:-0}"
}

# --- One-time setup: only runs the first time, or after the folder is copied to a new Mac ---
if ! .venv/bin/python -c "import playwright" >/dev/null 2>&1; then
  echo "=================================================="
  echo "   Google Reviews lookup - first-time setup"
  echo "=================================================="
  echo
  echo "This takes a few minutes and only happens once."
  echo "(If your Mac asks to install 'command line developer tools', click Install,"
  echo " wait for it to finish, then double-click this file again.)"
  echo
  if ! python3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)" >/dev/null 2>&1; then
    echo "Python isn't installed yet (or is too old). Install the latest version from"
    echo "https://www.python.org/downloads/ then double-click this file again."
    finish 1
  fi
  rm -rf .venv
  if ! { python3 -m venv .venv \
         && .venv/bin/pip install --quiet --disable-pip-version-check -r requirements.txt \
         && .venv/bin/python -m playwright install chromium; }; then
    echo
    echo "Setup didn't finish. Check your internet connection and try again."
    finish 1
  fi
  echo
  echo "Setup done."
  echo
fi

.venv/bin/python start.py
finish 0
