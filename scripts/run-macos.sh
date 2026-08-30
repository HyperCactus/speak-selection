#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

PYTHON_CMD=()
CONDA_ENV_NAME="${SPEAK_SELECTION_CONDA_ENV:-speak-selection}"

find_conda_python() {
  local candidate base_dir

  if [[ -n "${SPEAK_SELECTION_CONDA_PYTHON:-}" && -x "${SPEAK_SELECTION_CONDA_PYTHON}" ]]; then
    printf '%s\n' "${SPEAK_SELECTION_CONDA_PYTHON}"
    return 0
  fi

  for candidate in \
    "${CONDA_PREFIX:-}/bin/python" \
    "$HOME/miniconda3/envs/${CONDA_ENV_NAME}/bin/python" \
    "$HOME/anaconda3/envs/${CONDA_ENV_NAME}/bin/python" \
    "$HOME/mambaforge/envs/${CONDA_ENV_NAME}/bin/python" \
    "$HOME/micromamba/envs/${CONDA_ENV_NAME}/bin/python"
  do
    if [[ -n "${candidate}" && -x "${candidate}" ]]; then
      printf '%s\n' "${candidate}"
      return 0
    fi
  done

  for base_dir in "$HOME/miniconda3" "$HOME/anaconda3" "$HOME/mambaforge" "$HOME/micromamba"; do
    candidate="${base_dir}/envs/${CONDA_ENV_NAME}/bin/python"
    if [[ -x "${candidate}" ]]; then
      printf '%s\n' "${candidate}"
      return 0
    fi
  done

  if command -v conda >/dev/null 2>&1; then
    if conda run --no-capture-output -n "${CONDA_ENV_NAME}" python -V >/dev/null 2>&1; then
      printf '%s\n' "conda run --no-capture-output -n ${CONDA_ENV_NAME} python"
      return 0
    fi
  fi

  return 1
}

if [[ -x "${PROJECT_ROOT}/.venv/bin/python" ]]; then
  PYTHON_CMD=("${PROJECT_ROOT}/.venv/bin/python")
elif CONDA_PYTHON="$(find_conda_python 2>/dev/null || true)"; [[ -n "${CONDA_PYTHON}" ]]; then
  # shellcheck disable=SC2206
  PYTHON_CMD=(${CONDA_PYTHON})
fi

if [[ "${#PYTHON_CMD[@]}" -eq 0 ]]; then
  if command -v python3 >/dev/null 2>&1; then
    PYTHON_CMD=(python3)
  elif command -v python >/dev/null 2>&1; then
    PYTHON_CMD=(python)
  else
    echo "Python was not found. Install Python 3 and try again." >&2
    exit 1
  fi
fi

if [[ "$#" -gt 0 ]]; then
  exec "${PYTHON_CMD[@]}" "${PROJECT_ROOT}/speak-selection.py" "$@"
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

exec "${PYTHON_CMD[@]}" "${PROJECT_ROOT}/speak-selection.py" --text "${selected_text}"
