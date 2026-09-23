#!/usr/bin/env bash
# Probe the take, transcribe it ONCE, and measure the audible extent of every
# word. Run from the project (lc has already moved us into edit/).
#
#   lc intake [--backend auto|scribe|local] [--lang ar] [--model large-v3]
#
# Transcription is cached on the output file: a second run on an unchanged
# source costs nothing and re-uses the transcript. Deleting transcripts/*.json
# is the only way to pay for it twice.
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
EDIT="${LC_EDIT_DIR:?lc sets this}"
PROJ="$(dirname "$EDIT")"

BACKEND="auto"; LANG_CODE=""; MODEL="large-v3"
while [ $# -gt 0 ]; do
  case "$1" in
    --backend) BACKEND="$2"; shift 2 ;;
    --lang)    LANG_CODE="$2"; shift 2 ;;
    --model)   MODEL="$2"; shift 2 ;;
    *) echo "intake: unknown option $1" >&2; exit 1 ;;
  esac
done

SRC=""
# first match wins: on a case-insensitive disk take1.mp4 also "exists" as take1.MP4
for e in mov mp4 MOV MP4; do [ -f "$PROJ/take1.$e" ] && { SRC="$PROJ/take1.$e"; break; }; done
[ -n "$SRC" ] || { echo "intake: no take1.mov / take1.mp4 in $PROJ. Run 'lc init <dir> --source <video>' first." >&2; exit 1; }

# language from project.json unless the flag overrides
if [ -z "$LANG_CODE" ] && [ -f "$EDIT/project.json" ]; then
  LANG_CODE="$("$PY" -c 'import json,sys;print(json.load(open(sys.argv[1])).get("language","") or "")' "$EDIT/project.json")"
fi
[ "$LANG_CODE" = "auto" ] && LANG_CODE=""

echo "== source"
ffprobe -v error -select_streams v:0 \
  -show_entries stream=width,height,r_frame_rate,codec_name \
  -show_entries format=duration,size -of default=nw=1 "$SRC"

echo
echo "== transcribe (cached; costs money on the first run with Scribe)"
"$PY" "$HERE/transcribe.py" "$SRC" --edit-dir "$EDIT" --backend "$BACKEND" --model "$MODEL" \
  ${LANG_CODE:+--language "$LANG_CODE"} || exit 1

echo
echo "== measure audible word extents"
# Every later tool reads these MEASURED extents rather than the recogniser's
# logged spans. A recogniser pads a token's end (and sometimes its start) with
# silence, so a cut placed on a logged boundary either restores seconds of dead
# air or clips the word. This is the single most load-bearing step in intake.
( cd "$EDIT" && LC_EDIT_DIR="$EDIT" PYTHONPATH="$EDIT" "$PY" "$HERE/measure_tokens.py" ) || exit 1

echo
echo "== transcript as readable lines"
( cd "$EDIT" && LC_EDIT_DIR="$EDIT" PYTHONPATH="$EDIT" "$PY" "$HERE/analyze.py" dump ) > "$EDIT/transcript_lines.txt" || exit 1
echo "   $(wc -l < "$EDIT/transcript_lines.txt" | tr -d ' ') utterances -> transcript_lines.txt"

echo
echo "intake done. Read transcript_lines.txt against the script, then decide the cuts."
