#!/bin/bash
# Double-click this file (on a Mac) to start CV Maker. It sets everything up the first time.
cd "$(dirname "$0")" || exit 1

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 isn't installed. Get it from https://www.python.org/downloads/ and try again."
  read -r -p "Press Enter to close."
  exit 1
fi

if [ ! -d .venv ]; then
  echo "First run: setting up (this takes a minute)…"
  python3 -m venv .venv || { read -r -p "Couldn't set up Python. Press Enter to close."; exit 1; }
fi
source .venv/bin/activate

# Install or update packages only when requirements.txt has changed.
wanted="$(shasum requirements.txt | cut -d' ' -f1)"
if [ "$(cat .venv/.requirements-hash 2>/dev/null)" != "$wanted" ]; then
  echo "Installing what CV Maker needs…"
  python -m pip install -q --upgrade pip >/dev/null
  python -m pip install -q -r requirements.txt && echo "$wanted" > .venv/.requirements-hash
fi

echo "Starting CV Maker. Keep this window open while you use it; close it to stop."
python -m cv_maker "$@"
