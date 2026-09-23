#!/usr/bin/env bash
# What is missing on this machine, and the exact command that fixes each one.
#
# Run this first on a new machine. The pipeline needs very little (ffmpeg, a
# recent python, three packages, an ASR), but it needs all of it, and finding
# out 40 minutes into a render is expensive.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# The venv setup.sh builds lives in ~/.lesson-cut/venv, OUTSIDE the plugin.
# It used to live in the plugin's own .venv, and that broke on install: Claude
# Code copies a plugin into its cache, a virtualenv is not relocatable, and the
# copied one silently fell back to the system python. A user-level location is
# found by the clone and by the installed copy alike.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LC_HOME="${LESSON_CUT_HOME:-$HOME/.lesson-cut}"
PY="${LC_PYTHON:-}"
[ -n "$PY" ] || { [ -x "$LC_HOME/venv/bin/python" ] && PY="$LC_HOME/venv/bin/python" || PY="python3"; }
FAIL=0
ok()   { printf '  ok      %s\n' "$*"; }
warn() { printf '  note    %s\n' "$*"; }
bad()  { printf '  MISSING %s\n' "$*"; FAIL=1; }

echo "lesson-cut doctor"
echo "  plugin: $(cd "$HERE/.." && pwd)"
echo

# ---------------------------------------------------------------- binaries --
for b in ffmpeg ffprobe; do
  if command -v "$b" >/dev/null 2>&1; then
    ok "$b  ($("$b" -version 2>/dev/null | head -1 | cut -d' ' -f1-3))"
  else
    # ffmpeg-full, not ffmpeg: the plain formula has no libass (see below).
    bad "$b        install: brew install ffmpeg-full   (macOS)  |  apt install ffmpeg  (Debian/Ubuntu)"
  fi
done

# ------------------------------------------------------------------ libass --
# Every lesson burns its captions with ffmpeg's `ass` filter, which exists only
# in an ffmpeg built with libass. Homebrew's plain `ffmpeg` formula is built
# without it; `ffmpeg-full` has it.
if command -v ffmpeg >/dev/null 2>&1; then
  # Captured first: with pipefail, `grep -q` exiting at its first match gives
  # ffmpeg a SIGPIPE and the pipeline "fails" at random, which read as no libass.
  FILTERS="$(ffmpeg -hide_banner -filters 2>/dev/null || true)"
  if printf '%s\n' "$FILTERS" | grep -E '^ *[.A-Z|]+ +ass +' >/dev/null; then
    ok "ffmpeg has libass (the ass filter that burns captions)"
  else
    bad "ffmpeg has no libass, so it cannot burn captions.
          macOS:  brew install ffmpeg-full   (if plain ffmpeg is also installed:
                  brew unlink ffmpeg && brew link ffmpeg-full)
          Linux:  any distribution ffmpeg built with --enable-libass"
  fi
fi

# ------------------------------------------------------------------ python --
if command -v "$PY" >/dev/null 2>&1; then
  V="$("$PY" -c 'import sys;print("%d.%d"%sys.version_info[:2])')"
  # 3.9 is the measured floor, not a guess: the whole chain, render and QC gate
  # included, was run on 3.9.6. setup.sh accepts the same version, so the two
  # cannot disagree about a venv one of them just built.
  if "$PY" -c 'import sys;sys.exit(0 if sys.version_info[:2]>=(3,9) else 1)'; then
    ok "python $V  ($(command -v "$PY"))"
  else
    bad "python $V is too old; 3.9 or newer is required"
  fi
else
  bad "$PY not found"
fi

for m in numpy PIL requests; do
  if "$PY" -c "import $m" 2>/dev/null; then
    ok "python module $m"
  else
    # setup.sh builds the private venv, repairs one an earlier run left without
    # pip, and installs requirements.txt into it, so it is the fix whenever the
    # python is ours. Before it has run, $PY is the system python: an externally
    # managed (PEP 668) one such as Homebrew's refuses a pip install, and macOS's
    # own scatters it into the user's site-packages. A pip line is right only
    # for a python chosen with LC_PYTHON.
    if [ -n "${LC_PYTHON:-}" ]; then
      bad "python module $m    install: \"$PY\" -m pip install -r \"$ROOT/requirements.txt\""
    else
      bad "python module $m    install: bash \"$ROOT/scripts/setup.sh\"   (builds or repairs $LC_HOME/venv)"
    fi
  fi
done

# --------------------------------------------------------------------- ASR --
# The whole pipeline is built on WORD-level timestamps. A transcript without
# them cannot place a cut between two words, which is every cut this tool makes.
ASR=0
# Same two places transcribe.py reads, in the same order: the environment, then
# $LESSON_CUT_HOME/env. Never inside the plugin or a project.
if [ -n "${ELEVENLABS_API_KEY:-}" ] || grep -qsE '^[[:space:]]*ELEVENLABS_API_KEY[[:space:]]*=[[:space:]]*["'"'"']?[^"'"'"'[:space:]]' "$LC_HOME/env"; then
  ok "ASR: ElevenLabs Scribe key present"; ASR=1
fi
if "$PY" -c 'import faster_whisper' 2>/dev/null; then
  ok "ASR: faster-whisper (local, no key, no per-run cost)"; ASR=1
elif "$PY" -c 'import whisper' 2>/dev/null; then
  ok "ASR: openai-whisper (local)"; ASR=1
fi
[ "$ASR" = 1 ] || bad "no ASR backend.
          Either:  (umask 077; mkdir -p \"$LC_HOME\" && echo 'ELEVENLABS_API_KEY=sk_...' > \"$LC_HOME/env\")
          Or:      bash \"$(cd "$HERE/.." && pwd)/scripts/setup.sh\" --local-asr     (local, free, slower)"

# -------------------------------------------------------------------- font --
# The definitive check is what libass itself resolves, not whether a file with
# the right name exists somewhere. libass prints its choice, and a silent
# fallback to a default font is exactly the failure this catches.
FONT="${1:-}"
PJ=""
for p in "${LC_EDIT_DIR:-}/project.json" "./project.json" "./edit/project.json"; do
  [ -f "$p" ] && { PJ="$p"; break; }
done
if [ -z "$FONT" ] && [ -n "$PJ" ]; then
  FONT="$("$PY" -c 'import json,sys;print(json.load(open(sys.argv[1])).get("captions",{}).get("font",""))' "$PJ" 2>/dev/null)"
  [ -n "$FONT" ] && warn "font: checking this project's caption font (from $PJ)"
fi
[ -n "$FONT" ] || FONT="Almarai ExtraBold"
if command -v ffmpeg >/dev/null 2>&1; then
  TMP="$(mktemp -d)"
  cat > "$TMP/t.ass" <<ASS
[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, Bold, Alignment, MarginV, Encoding
Style: Cap,$FONT,72,&H00FFFFFF,0,2,80,1
[Events]
Format: Layer, Start, End, Style, Text
Dialogue: 0,0:00:00.00,0:00:01.00,Cap,font check
ASS
  LOG="$(ffmpeg -v verbose -f lavfi -i color=c=black:s=320x180:d=0.1 \
          -vf "subtitles=$TMP/t.ass" -frames:v 1 -f null - 2>&1 | grep -i fontselect | head -3)"
  rm -rf "$TMP"
  # The log line reads "fontselect: (<requested>, ...) -> <file>, <index>, <postscript name>".
  # Only the right-hand side says what libass FOUND; the requested name is always
  # on the left, so matching the whole line passed even when libass fell back.
  RES="$(echo "$LOG" | sed -n '1s/.*-> //p')"
  GOT="$(echo "$RES" | awk -F', ' '{print $NF}' | tr -d ' _-' | tr '[:upper:]' '[:lower:]')"
  WANT="$(echo "$FONT" | tr -d ' _-' | tr '[:upper:]' '[:lower:]')"
  # A family resolves to a PostScript name that often extends it (Arial ->
  # ArialMT, Times New Roman -> TimesNewRomanPSMT, Almarai -> Almarai-Regular),
  # so the resolved name must START with the requested one. A fallback face
  # (Helvetica for a missing font) does not.
  if [ -n "$GOT" ] && case "$GOT" in "$WANT"*) true ;; *) false ;; esac; then
    ok "font: libass resolves '$FONT' -> $RES"
  elif [ -n "$LOG" ]; then
    bad "font: libass did NOT find '$FONT'; it fell back to: ${RES:-unknown}"
    warn "        captions would render in the wrong face. Install the font, or set"
    warn "        captions.font in the project's project.json to one you have."
    case "$WANT" in
      almarai*) warn "        Almarai is free (SIL Open Font License 1.1): https://fonts.google.com/specimen/Almarai" ;;
    esac
  else
    warn "font: could not read libass's choice from this ffmpeg build; check a rendered frame by eye"
  fi
fi

# -------------------------------------------------------------------- disk --
FREE="$(df -h . | awk 'NR==2{print $4}')"
warn "free disk here: $FREE  (a half-hour 4K screen recording uses about 3 GB of render scratch; camera footage needs more)"

echo
[ "$FAIL" = 0 ] && echo "ready." || echo "not ready: fix the MISSING lines above."
exit "$FAIL"
