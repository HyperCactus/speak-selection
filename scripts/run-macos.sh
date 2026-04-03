#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

if [[ -x "${PROJECT_ROOT}/.venv/bin/python" ]]; then
  PYTHON_BIN="${PROJECT_ROOT}/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="python3"
elif command -v python >/dev/null 2>&1; then
  PYTHON_BIN="python"
else
  echo "Python was not found. Install Python 3 and try again." >&2
  exit 1
fi

if [[ "$#" -gt 0 ]]; then
  exec "${PYTHON_BIN}" "${PROJECT_ROOT}/speak-selection.py" "$@"
fi

selected_text=""

if command -v osascript >/dev/null 2>&1; then
  selected_text="$(osascript <<'APPLESCRIPT' || true
set oldClipboard to the clipboard
tell application "System Events"
  keystroke "c" using command down
end tell
delay 0.12
set selectedText to the clipboard
set the clipboard to oldClipboard
return selectedText
APPLESCRIPT
)"
fi

if [[ -z "${selected_text//[[:space:]]/}" ]] && command -v pbpaste >/dev/null 2>&1; then
  selected_text="$(pbpaste || true)"
fi

if [[ -z "${selected_text//[[:space:]]/}" ]]; then
  exit 0
fi

exec "${PYTHON_BIN}" "${PROJECT_ROOT}/speak-selection.py" --text "${selected_text}"
