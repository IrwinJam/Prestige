#!/usr/bin/env bash
# Sets up a fresh checkout, runs the tests and the offline demo. No keys and no spend.
#   bash scripts/quickstart.sh
set -euo pipefail
cd "$(dirname "$0")/.."

PYTHON="${PYTHON:-$(command -v python3 || command -v python)}"
"$PYTHON" -m venv .venv
PY=.venv/bin/python
[ -x "$PY" ] || PY=.venv/Scripts/python  # Git Bash on Windows

"$PY" -m pip install -q --upgrade pip
"$PY" -m pip install -q -e ".[dev,security]"
"$PY" -m pytest -q
"$PY" -m prestige assistant demo
