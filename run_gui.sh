#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ -x .venv/bin/python ]]; then
  exec .venv/bin/python gui_tkinter.py "$@"
elif [[ -x venv/bin/python ]]; then
  exec venv/bin/python gui_tkinter.py "$@"
else
  exec python3 gui_tkinter.py "$@"
fi
