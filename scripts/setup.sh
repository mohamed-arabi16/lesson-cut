#!/usr/bin/env bash
# One-time setup: a private virtualenv at ~/.lesson-cut/venv, so the toolchain
# does not depend on whatever happens to be installed in the system python.
#
#   bash scripts/setup.sh            use the best python already on the machine
#   bash scripts/setup.sh --local-asr  also install faster-whisper (no API key needed)
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# Outside the plugin on purpose: Claude Code copies an installed plugin into its
# own cache, and a virtualenv does not survive being copied. Every entry point
# looks here, so the clone and the installed copy share one environment.
LC_HOME="${LESSON_CUT_HOME:-$HOME/.lesson-cut}"
VENV="$LC_HOME/venv"
mkdir -p "$LC_HOME" && chmod 700 "$LC_HOME"   # it holds the API key file; keep it private

pick_python() {
  for c in python3.13 python3.12 python3.11 python3.10 python3; do
    command -v "$c" >/dev/null 2>&1 || continue
    "$c" -c 'import sys;sys.exit(0 if sys.version_info[:2]>=(3,9) else 1)' 2>/dev/null && { echo "$c"; return; }
  done
  return 1
}

# A venv without a working pip is what a failed earlier run leaves behind (a
# Debian/Ubuntu python without python3-venv, or an interrupted install).
# Rebuild it instead of failing on it at every run after.
venv_ok() { [ -x "$VENV/bin/python" ] && "$VENV/bin/python" -m pip --version >/dev/null 2>&1; }

# Rebuilding clears the folder, so only ever clear one that is a virtualenv (it
# has pyvenv.cfg), is empty, or is not there yet. LESSON_CUT_HOME can point
# anywhere, and a `venv` folder that is not a virtualenv may hold someone's
# files. A folder that cannot be listed counts as not empty.
safe_to_clear() {
  [ -e "$VENV" ] || return 0
  [ -d "$VENV" ] || return 1
  [ -f "$VENV/pyvenv.cfg" ] && return 0
  [ -r "$VENV" ] && [ -z "$(ls -A "$VENV")" ]
}

if ! venv_ok; then
  if ! safe_to_clear; then
    echo "$VENV exists and is not a virtualenv, so setup will not clear it." >&2
    echo "move it aside, or set LESSON_CUT_HOME to another folder, then run this again" >&2
    exit 1
  fi
  [ -d "$VENV" ] && echo "-- $VENV is incomplete or broken; rebuilding it"
  if PY="$(pick_python)"; then
    echo "-- creating $VENV with $PY ($("$PY" -V 2>&1))"
    "$PY" -m venv --clear "$VENV" || {
      echo "could not create a virtualenv with $PY." >&2
      # $PY is the bare command name, so a versioned pick names its own package
      # (python3.12-venv), which is what is missing when it is not the default.
      echo "on Debian/Ubuntu:  sudo apt install ${PY}-venv   then run this again" >&2
      exit 1; }
  elif command -v uv >/dev/null 2>&1; then
    echo "-- no suitable python found; creating $VENV with uv"
    # --seed: a uv venv has no pip unless asked for one, and everything below
    # uses pip. --clear replaces a half-made venv (a current uv refuses an
    # existing one without it); it is passed only when this uv lists it, so an
    # older uv is not handed a flag it rejects.
    UV_HELP="$(uv venv --help 2>/dev/null || true)"
    case "$UV_HELP" in
      *--clear*) uv venv --seed --clear --python 3.12 "$VENV" ;;
      *)         uv venv --seed --python 3.12 "$VENV" ;;
    esac
  else
    echo "no python 3.9+ and no uv on this machine." >&2
    echo "install one:  brew install python@3.12   |   curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
    exit 1
  fi
fi

"$VENV/bin/python" -m pip install --quiet --upgrade pip
"$VENV/bin/python" -m pip install --quiet -r "$ROOT/requirements.txt"
echo "-- installed: $("$VENV/bin/python" -c 'import numpy,PIL,requests;print("numpy",numpy.__version__,"| pillow",PIL.__version__,"| requests",requests.__version__)')"

if [ "${1:-}" = "--local-asr" ]; then
  echo "-- installing faster-whisper (this one is large)"
  "$VENV/bin/python" -m pip install --quiet faster-whisper
fi

echo
# setup's job is the environment, and that succeeded if we got here. The doctor
# is information: its most common MISSING line on a fresh machine is simply
# that no transcription backend has been chosen yet.
bash "$ROOT/scripts/doctor.sh" || {
  echo
  echo "The environment is installed. If the only MISSING line is the ASR, that is"
  echo "expected: add a key or run  bash \"$ROOT/scripts/setup.sh\" --local-asr"
}
exit 0
