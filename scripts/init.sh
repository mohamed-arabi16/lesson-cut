#!/usr/bin/env bash
# Scaffold a project around a raw take.
#
#   lc init <project-dir> --source <video> [options]
#
#   --source <file>   the raw take. MOVED into the project, not copied, so one
#                     70 GB take does not become two. --copy overrides.
#   --profile <name>  course-landscape (default) or reel-portrait
#   --lang <code>     ISO language for transcription (ar, en, ...). Omit to auto-detect.
#   --scale <px>      render long edge. Default: the source's own long edge, never less.
#   --fps <n>         render fps. Default 30.
#   --crf <n>         18 for a screen recording (flat UI), 23 for camera
#                     footage. The resolution is untouched either way.
#
# Layout, which the tools depend on:
#
#   <project>/take1.mov        the source, one level ABOVE the edit dir
#   <project>/edit/            everything generated, and the cut list
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

DIR=""; SRC=""; PROFILE="course-landscape"; LANG_CODE=""; SCALE=""; FPS="30"; CRF="18"; MOVE=1
die() { echo "init: $*" >&2; exit 1; }
need() { [ $# -ge 2 ] && [ -n "$2" ] || die "$1 needs a value"; }
while [ $# -gt 0 ]; do
  case "$1" in
    --source)  need "$@"; SRC="$2"; shift 2 ;;
    --profile) need "$@"; PROFILE="$2"; shift 2 ;;
    --lang)    need "$@"; LANG_CODE="$2"; shift 2 ;;
    --scale)   need "$@"; SCALE="$2"; shift 2 ;;
    --fps)     need "$@"; FPS="$2"; shift 2 ;;
    --crf)     need "$@"; CRF="$2"; shift 2 ;;
    --copy)    MOVE=0; shift ;;
    -*)        die "unknown option $1" ;;
    *)         [ -z "$DIR" ] && DIR="$1" || die "two project dirs?"; shift ;;
  esac
done
[ -n "$DIR" ] || { awk 'NR>1 && /^#/ {sub(/^# ?/,""); print; next} NR>1 {exit}' "${BASH_SOURCE[0]}"; exit 1; }
[ -e "$DIR/edit" ] && die "$DIR/edit already exists; refusing to overwrite a project."
for e in mov mp4 MOV MP4; do
  [ -e "$DIR/take1.$e" ] && die "$DIR already has a take1.$e; refusing to overwrite a take."
done
case "$PROFILE" in course-landscape|reel-portrait) ;; *) die "unknown profile '$PROFILE' (course-landscape | reel-portrait)" ;; esac

# Validate the source BEFORE creating or moving anything, so a failed init
# leaves nothing half-made behind and the source where it was.
if [ -n "$SRC" ]; then
  [ -f "$SRC" ] || die "no such file: $SRC"
  EXT="$(printf '%s' "${SRC##*.}" | tr '[:upper:]' '[:lower:]')"
  case "$EXT" in mov|mp4) ;; *) die "source must be .mov or .mp4 (got .${SRC##*.})" ;; esac
  PROBE="$(ffprobe -v error -select_streams v:0 -show_entries stream=width,height,r_frame_rate \
            -of csv=p=0 "$SRC" 2>/dev/null | head -1 || true)"   # set -e must not end init silently here
  [ -n "$PROBE" ] || die "ffprobe finds no video stream in $SRC"
  IFS=',' read -r W H RFR <<< "$PROBE"
fi

mkdir -p "$DIR/edit/transcripts"
DIR="$(cd "$DIR" && pwd)"

# ------------------------------------------------------------ the source --
if [ -n "$SRC" ]; then
  if [ "$MOVE" = 1 ]; then mv "$SRC" "$DIR/take1.$EXT"; else cp "$SRC" "$DIR/take1.$EXT"; fi
  echo "-- source: $DIR/take1.$EXT  ($(du -h "$DIR/take1.$EXT" | cut -f1))"
  echo "   ${W}x${H} @ ${RFR}  $(ffprobe -v error -show_entries format=duration -of csv=p=0 "$DIR/take1.$EXT" | cut -d. -f1)s"
  # render.scale is the LONG edge. Using the width would render a 1080x1920
  # portrait source at 608x1080, a downscale nobody asked for.
  [ -n "$SCALE" ] || { [ "$H" -gt "$W" ] && SCALE="$H" || SCALE="$W"; }
fi
[ -n "$SCALE" ] || SCALE=3840

# ------------------------------------------------------- caption profile --
# The two profiles are NOT convertible. FontSize is a fraction of the authoring
# canvas and MarginV was calibrated against one frame, so the portrait numbers
# on a landscape frame put captions in the middle of the picture, and the
# landscape numbers on a Reel put them under the Instagram chrome.
# Written by a JSON writer, never by string pasting: a quote in a folder name, or
# a non-number passed to --scale, used to produce a project.json nothing could read.
PYJ="${LC_PYTHON:-}"; [ -n "$PYJ" ] || PYJ="python3"
"$PYJ" - "$DIR/edit/project.json" "$(basename "$DIR")" "${LANG_CODE:-auto}" "$PROFILE" \
        "$SCALE" "$FPS" "$CRF" "${W:-}" "${H:-}" <<'PY' || { rm -rf "$DIR/edit"; [ -n "$SRC" ] && [ "$MOVE" = 1 ] && mv "$DIR/take1.$EXT" "$SRC"; exit 1; }
import json, sys
out, name, lang, profile, scale, fps, crf, w, h = sys.argv[1:10]
def num(label, v, lo, hi, cast):
    try:
        x = cast(float(v))
    except ValueError:
        sys.exit(f"init: --{label} must be a number, got {v!r}")
    if not lo <= x <= hi:
        sys.exit(f"init: --{label} {x} is out of range ({lo}-{hi})")
    return x
scale = num("scale", scale, 144, 16384, int)
fps = num("fps", fps, 1, 240, float)
fps = int(fps) if fps == int(fps) else fps
crf = num("crf", crf, 0, 51, int)
# The caption canvas takes the SOURCE's aspect. Authoring a 16:9 canvas onto a
# 1.54:1 frame lets libass stretch the glyphs; the height stays the calibrated
# one and the width follows the picture.
if profile == "reel-portrait":
    caps = {"font": "Almarai ExtraBold", "font_size": 66, "outline": 4.0, "shadow": 1.2,
            "margin_v": 420, "margin_h": 90, "play_h": 1920, "max_chars_per_line": 25}
    default_w = 1080
else:
    caps = {"font": "Almarai ExtraBold", "font_size": 72, "outline": 4.4, "shadow": 0.4,
            "margin_v": 80, "margin_h": 110, "play_h": 1440, "max_chars_per_line": 23}
    default_w = 2560
caps["play_w"] = (int(round(caps["play_h"] * int(w) / int(h) / 2)) * 2) if w and h else default_w
caps["max_lines"] = 2
cfg = {"name": name, "language": lang,
       "render": {"scale": scale, "fps": fps, "crf": crf, "av_offset_s": 0.0},
       "captions": {"profile": profile, **caps}}
with open(out, "w", encoding="utf-8") as fh:
    json.dump(cfg, fh, indent=2, ensure_ascii=False)
    fh.write("\n")
PY

# ------------------------------------------------------------ the stubs ----
cat > "$DIR/edit/cutlist.py" <<'PY'
# -*- coding: utf-8 -*-
"""The cut list. This file IS the edit.

Each entry is a span of SOURCE seconds to remove:

    (start, end, "why", keep_tail, refine_start, refine_end)

keep_tail keeps that many seconds of silence before speech resumes (normally
0.0). refine_* True lets build_edl move that edge to the nearest quiet point,
which is right for a cut of dead air; False pins it, which is right for a cut
that removes speech, and is what mkcuts emits.

Do not type these by hand. Write the editorial decisions as JSON and convert:

    lc mkcuts decisions.json > speech_cuts.txt     # read the ‖ [dropped] ‖ lines
    # paste the tuples below WHOLE, all six fields, then:
    lc rebuild

A speech cut needs its last two fields False: they pin the edges where mkcuts
put them. Pasted as just (start, end, "why"), build_edl moves the edges to the
nearest quiet point, which for a cut that removes speech can shrink it to
nothing, and it prints SKIPPED. A SKIPPED cut is a cut that did not happen.
"""

SPEECH_CUTS = [
    # (start, end, "why"),
]

TRUNCATION_CUTS = []
SWEEP_CUTS = []

try:
    from pause_cuts import PAUSE_CUTS       # generated by tighten_gaps.py
except ImportError:
    PAUSE_CUTS = []

try:
    from extra_cuts import EXTRA_CUTS
except ImportError:
    EXTRA_CUTS = []

CUTS = SPEECH_CUTS + TRUNCATION_CUTS + SWEEP_CUTS + list(PAUSE_CUTS) + list(EXTRA_CUTS)
PY

printf 'PAUSE_CUTS = []\n' > "$DIR/edit/pause_cuts.py"
cat > "$DIR/edit/protect.py" <<'PY'
# Spans tighten_gaps.py must not touch, as (start, end) in SOURCE seconds.
# Use this for a beat that has to survive intact: a deliberate pause, or a
# window a mask depends on.
PROTECT = []
PY
printf '[]\n' > "$DIR/edit/qc-accept.json"
cat > "$DIR/edit/captions_project.py" <<'PY'
# -*- coding: utf-8 -*-
"""This project's caption vocabulary.

CORRECTIONS: what the recogniser heard wrong, where the spoken audio is right.
Verify each one against the SCREEN at that timestamp, never against the ear: an
ASR renders an unfamiliar product or UI word as the nearest common word, and
both readings sound right on replay.

NO_SPLIT: phrases that must stay inside one cue.
"""

CORRECTIONS = [
    # ("heard", "actual"),
]

NO_SPLIT = [
]
PY

echo "-- project ready: $DIR"
# The full path of the lc that ran this, because `lc` is on nobody's PATH: a bare
# `lc intake` here is a command that fails as printed.
echo "   next:  cd \"$DIR\" && \"$HERE/lc\" intake"
