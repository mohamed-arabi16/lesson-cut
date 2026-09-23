#!/usr/bin/env bash
# Render the cut, then STOP. Nothing is uploaded and nothing is published.
#
#   lc render [--scale 3840] [--fps 30] [--out final.mp4] [--accept-findings]
#
# Three checks run BEFORE the render, not after it. That ordering is the whole
# point of this script: on a 40 minute 4K render, a defect found afterwards has
# already cost the render. Two of the three never touch the video at all, so
# there was never a reason for them to run second.
#
#   1. post_cut_check   truncations, adjacent duplicates, n-gram repeats
#   2. qc transcript    the GATE's own transcript scan, which sees two classes
#                       post_cut_check cannot: a pause-straddling trail-off, and
#                       a repeat a few words apart
#   3. head_onset       the head and tail cuts must not clip the kept word
#
# --accept-findings renders anyway. Only use it once every finding is written
# into qc-accept.json with a measured reason.
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

SCALE=""; FPS=""; OUT="$EDIT/final.mp4"; ACCEPT="${ACCEPT_FINDINGS:-0}"
while [ $# -gt 0 ]; do
  case "$1" in
    --scale) SCALE="$2"; shift 2 ;;
    --fps)   FPS="$2"; shift 2 ;;
    --out)   OUT="$2"; shift 2 ;;
    --accept-findings) ACCEPT=1; shift ;;
    *) echo "render: unknown option $1" >&2; exit 1 ;;
  esac
done

cfg() { "$PY" -c 'import json,os,sys
p=sys.argv[1]
if not os.path.exists(p): c={}
else:
    try: c=json.load(open(p))
    except Exception as e: sys.exit("render: project.json does not parse (%s). Fix it; refusing to guess the settings." % e)
print(c.get("render",{}).get(sys.argv[2], sys.argv[3]))' "$EDIT/project.json" "$1" "$2"; }
cfg scale 0 >/dev/null || exit 1
[ -n "$SCALE" ] || SCALE="$(cfg scale 3840)"
[ -n "$FPS" ]   || FPS="$(cfg fps 30)"

[ -f "$EDIT/edl.json" ] || { echo "render: no edl.json. Build the cut first." >&2; exit 1; }
# --out is a FILE, read from where the user stands (lc exports LC_CALLER_DIR).
# It renders to a temporary name and only replaces --out after a successful
# render, and it never touches an existing file outside edit/: `--out
# take1.mp4` from the project dir used to delete the raw take, which is the
# only copy because init moves it.
case "$OUT" in /*) ;; *) OUT="${LC_CALLER_DIR:-$EDIT}/$OUT" ;; esac
case "$OUT" in *.mp4|*.mov|*.MP4|*.MOV) ;; *) echo "render: --out must be a .mp4 or .mov file, got: $OUT" >&2; exit 1 ;; esac
[ -d "$OUT" ] && { echo "render: --out is a directory: $OUT" >&2; exit 1; }
if [ -e "$OUT" ]; then
  _od="$(cd "$(dirname "$OUT")" && pwd)"
  if [ "$_od" != "$EDIT" ]; then
    echo "render: $OUT already exists outside edit/; refusing to overwrite it. Pick a new name." >&2; exit 1
  fi
fi
if "$PY" - "$EDIT/edl.json" "$OUT" <<'PY'
import json, os, sys
edl, out = sys.argv[1], os.path.realpath(sys.argv[2])
srcs = json.load(open(edl)).get("sources", {}).values()
base = os.path.dirname(os.path.abspath(edl))
sys.exit(0 if any(os.path.realpath(os.path.join(base, s)) == out for s in srcs) else 1)
PY
then echo "render: --out is one of this project's SOURCE files: $OUT. Refusing." >&2; exit 1; fi

# The captions were authored against a frame rate. ffmpeg emits ceil(dur*fps)
# frames per segment, so the delivered timeline is longer than the EDL predicts
# by up to one frame per join; the caption builder compensates for exactly the
# fps it was told. A mismatch here silently re-creates the drift it removes:
# measured at -1.1s by minute 17 on an 82-join lesson.
CFG_FPS="$(cfg fps 30)"
if [ ! -f "$EDIT/master.ass" ] && grep -q '"subtitles": *"master.ass"' "$EDIT/edl.json"; then
  echo "render: edl.json asks for master.ass and there is none; the render would ship without captions." >&2
  echo "        Run 'lc build_captions .' (or 'lc rebuild'), then render." >&2
  exit 1
fi
if [ -f "$EDIT/master.ass" ]; then
  # master.ass must describe THIS cut: a caption file older than the EDL was
  # timed against ranges that no longer exist.
  if [ "$EDIT/edl.json" -nt "$EDIT/master.ass" ]; then
    echo "render: master.ass is older than edl.json, so its cues are timed for an earlier cut." >&2
    echo "        Run 'lc build_captions .' (or 'lc rebuild'), then render." >&2
    exit 1
  fi
  # and the fps it was built for is stamped inside it; trust that over the config
  ASS_FPS="$(sed -n 's/^; grid-fps: *//p' "$EDIT/master.ass" | head -1)"
  if [ -n "$ASS_FPS" ] && ! "$PY" -c "import sys;sys.exit(0 if abs(float(sys.argv[1])-float(sys.argv[2]))<0.01 else 1)" "$ASS_FPS" "$FPS"; then
    echo "render: master.ass was built for ${ASS_FPS}fps but this render is ${FPS}fps; captions would drift." >&2
    echo "        Set render.fps in project.json, rebuild the captions, then render." >&2
    exit 1
  fi
fi
if [ -f "$EDIT/master.ass" ] && [ -z "${ASS_FPS:-}" ] && \
   ! "$PY" -c "import sys;sys.exit(0 if abs(float(sys.argv[1])-float(sys.argv[2]))<0.01 else 1)" "$CFG_FPS" "$FPS"; then
  echo "render: master.ass was built for ${CFG_FPS}fps (project.json) but this render is ${FPS}fps." >&2
  echo "        Captions would drift progressively early. Set render.fps in project.json," >&2
  echo "        rebuild the captions, then render." >&2
  exit 1
fi

# Versions before 1.2.0 wrapped EVERY caption line in right-to-left embedding,
# which scrambles a line with no right-to-left letters, and the QC gate fails
# such a file. That gate runs after the render, so check here, in seconds.
# Same test as has_rtl() in build_captions.py and qc.py.
if [ -f "$EDIT/master.ass" ] && ! "$PY" - "$EDIT/master.ass" <<'PY'
import sys, unicodedata
RLE, PDF = chr(0x202B), chr(0x202C)
def has_rtl(s):
    return any(unicodedata.bidirectional(c) in ("R", "AL")
               and unicodedata.category(c).startswith("L") for c in s)
bad = 0
for ln in open(sys.argv[1], encoding="utf-8"):
    if ln.startswith("Dialogue:"):
        for seg in ln.rstrip("\n").split(",", 9)[-1].split("\\N"):
            if (RLE in seg or PDF in seg) and not has_rtl(seg):
                bad += 1
if bad:
    sys.exit(f"render: master.ass wraps {bad} caption line(s) that have no right-to-left letters in\n"
             "        right-to-left embedding (a version before 1.2.0 built it); the QC gate would fail it\n"
             "        after the render. Run 'lc build_captions .' (or 'lc rebuild'), then render.")
PY
then exit 1; fi

if [ -f "$EDIT/qc-accept.json" ] && ! "$PY" - "$EDIT/qc-accept.json" <<'PY'
import json, sys
try:
    d = json.load(open(sys.argv[1]))
except Exception as e:
    sys.exit(f"render: qc-accept.json does not parse: {e}")
if not isinstance(d, list) or not all(isinstance(a, dict) and str(a.get("phrase", "")).strip()
                                      and str(a.get("reason", "")).strip() for a in d):
    sys.exit('render: qc-accept.json must be [{"phrase": "...", "reason": "..."}, ...] with both filled in')
PY
then exit 1; fi

gate() { # name command...
  local name="$1"; shift
  echo "-- pre-render: $name"
  if ! ( cd "$EDIT" && LC_EDIT_DIR="$EDIT" PYTHONPATH="$EDIT" "$@" ) > "$EDIT/${name}.log" 2>&1; then
    # the finding lines; if none match (a crash, or qc refusing on a malformed
    # qc-accept.json), show the end of the log instead of refusing in silence
    # (captured first: with pipefail, an early-closing head would make the
    # pipeline's status lie about whether anything matched)
    local exc; exc="$(grep -E "^  X|^   |cut at" "$EDIT/${name}.log" | head -12 || true)"
    if [ -n "$exc" ]; then printf '%s\n' "$exc" | sed 's/^/   /'
    else tail -6 "$EDIT/${name}.log" | sed 's/^/   | /'; fi
    if grep -q "^Traceback" "$EDIT/${name}.log"; then
      echo "REFUSING TO RENDER: $name crashed (see $EDIT/${name}.log). That is a tool error,"
      echo "not a finding, so --accept-findings does not apply."; exit 1
    fi
    [ "$ACCEPT" = "1" ] || { echo "REFUSING TO RENDER. Fix these, or accept each one in qc-accept.json."; exit 1; }
    echo "   (findings accepted)"
  else
    echo "   clean"
  fi
}

gate post_cut_check "$PY" "$HERE/post_cut_check.py"
gate pre-transcript "$PY" "$HERE/qc.py" transcript --edit-dir "$EDIT" --video /dev/null
gate onset          "$PY" "$HERE/head_onset_check.py" .

# One render at a time. Waiting on `pgrep -x ffmpeg` alone let several waiting
# renders start together the moment ffmpeg went idle, so there is a lock too.
# mkdir is atomic; a lock whose owner is gone is taken over.
LC_HOME="${LESSON_CUT_HOME:-$HOME/.lesson-cut}"; mkdir -p "$LC_HOME"
LOCK="$LC_HOME/render.lock"
until mkdir "$LOCK" 2>/dev/null; do
  OWNER="$(cat "$LOCK/pid" 2>/dev/null || true)"
  if [ -n "$OWNER" ] && ! kill -0 "$OWNER" 2>/dev/null; then rm -rf "$LOCK"; continue; fi
  echo "   waiting: another lesson-cut render holds the lock (pid ${OWNER:-?})"; sleep 20
done
echo $$ > "$LOCK/pid"
trap 'rm -rf "$LOCK"' EXIT
# and any other ffmpeg on the machine. -x matches the process NAME; -f would
# match this script's own command line and wait forever on itself.
if pgrep -x ffmpeg >/dev/null; then
  echo "   waiting for other ffmpeg process(es) to finish: $(pgrep -x ffmpeg | tr '\n' ' ')"
  while pgrep -x ffmpeg >/dev/null; do sleep 20; done
fi

rm -rf "$EDIT/clips_graded"          # the renderer's own scratch, inside edit/
rm -f "$EDIT/base.mp4"
TMP_OUT="$EDIT/.render-$$.mp4"; rm -f "$TMP_OUT"
RANGES=$("$PY" -c 'import json,sys;print(len(json.load(open(sys.argv[1]))["ranges"]))' "$EDIT/edl.json")
DUR=$("$PY" -c 'import json,sys;print(round(json.load(open(sys.argv[1]))["total_duration_s"],1))' "$EDIT/edl.json")
# 18 is visually lossless for flat UI; camera footage needs 23 or the file is
# too large to stream. The RESOLUTION is untouched either way, which is the
# distinction that matters: a higher CRF is not a lower-resolution delivery.
export LC_CRF="$(cfg crf 18)"
echo "-- rendering at ${SCALE}px / ${FPS}fps / CRF ${LC_CRF} (${RANGES} ranges, ${DUR}s)"
echo "   a half-hour 4K lesson takes roughly an hour and a half and lands around 600 MB"
( cd "$EDIT" && "$PY" -u "$HERE/render.py" "$EDIT/edl.json" -o "$TMP_OUT" \
    --fps "$FPS" --scale "$SCALE" ) > "$EDIT/render.log" 2>&1
[ -f "$TMP_OUT" ] || { echo "RENDER FAILED"; tail -8 "$EDIT/render.log"; exit 1; }
mv -f "$TMP_OUT" "$OUT"
echo "-- size: $(du -h "$OUT" | cut -f1)  delivered: $(ffprobe -v error -show_entries format=duration -of csv=p=0 "$OUT" | cut -d. -f1)s"

echo "-- QC gate"
QC_OK=0
PCC_OK=1
if ! ( cd "$EDIT" && LC_EDIT_DIR="$EDIT" PYTHONPATH="$EDIT" "$PY" "$HERE/post_cut_check.py" ) \
     > "$EDIT/post_cut_check.log" 2>&1; then PCC_OK=0; fi
ONSET_OK=1
if ! ( cd "$EDIT" && LC_EDIT_DIR="$EDIT" PYTHONPATH="$EDIT" "$PY" "$HERE/head_onset_check.py" . ) \
     > "$EDIT/onset.log" 2>&1; then ONSET_OK=0; fi
if ( cd "$EDIT" && LC_EDIT_DIR="$EDIT" PYTHONPATH="$EDIT" \
     "$PY" "$HERE/qc.py" all --edit-dir "$EDIT" --video "$OUT" ) > "$EDIT/qc.log" 2>&1; then
  echo "QC GREEN"; grep -E "passes OK" "$EDIT/qc.log"; QC_OK=1
else
  echo "QC FAILED (full report: $EDIT/qc.log):"
  QX="$(grep -E "^  X" "$EDIT/qc.log" | head -12 || true)"
  if [ -n "$QX" ]; then printf '%s\n' "$QX"; else tail -6 "$EDIT/qc.log" | sed 's/^/   | /'; fi
fi
echo "-- HOLDING for review. Nothing uploaded."
echo "   file: $OUT"
echo "   the gate's verdict is necessary and not sufficient: read its MEASUREMENT"
echo "   lines, and pull frames from $OUT itself at every spot you fixed."
if [ "$PCC_OK" = 0 ]; then
  echo "   NOT CLEAN: post_cut_check still has findings that are not accepted in qc-accept.json"
  echo "   (rendered with --accept-findings). See $EDIT/post_cut_check.log"
fi
if [ "$ONSET_OK" = 0 ]; then
  echo "   NOT CLEAN: head_onset_check still finds the head or tail cut inside a word"
  echo "   (rendered with --accept-findings). See $EDIT/onset.log"
fi
# exit status carries the verdict, so a script or an agent can act on it
[ "$QC_OK" = 1 ] && [ "$PCC_OK" = 1 ] && [ "$ONSET_OK" = 1 ] || exit 1
