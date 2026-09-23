#!/usr/bin/env bash
# Rebuild the whole cut from cutlist.py, in the one order that works.
#
#   lc rebuild [short_ceiling short_target long_ceiling long_target]
#   lc rebuild --no-captions
#
# Defaults: 0.50 0.18 4.0 0.90. Every wordless gap over 0.50s becomes 0.18s, and
# a wait over 4.0s keeps 0.9s of its busiest picture, so the viewer still sees
# the tool working.
#
# Why this exists: the tightener regenerates pause_cuts.py from the CURRENT
# edl.json, so it has to see the raw gaps. Run it over an EDL that already has
# the pause cuts in it and it writes an EMPTY list, and the next build restores
# every second of dead air, with nothing reporting it. Doing these five steps by
# hand is how that happens; this does them in order and stops on the first
# failure.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${LC_PYTHON_RESOLVED:?run this through lc}"
EDIT="${LC_EDIT_DIR:?run this through lc}"

CAPS=1; NUMS=()
for a in "$@"; do
  case "$a" in
    --no-captions) CAPS=0 ;;
    -*) echo "rebuild: unknown option $a" >&2; exit 1 ;;
    *) NUMS+=("$a") ;;
  esac
done
[ ${#NUMS[@]} -eq 0 ] && NUMS=(0.50 0.18 4.0 0.90)
[ ${#NUMS[@]} -eq 4 ] || { echo "rebuild: give all four numbers or none" >&2; exit 1; }

run() { # label, command...
  local label="$1"; shift
  echo "-- $label"
  local out; out="$("$@" 2>&1)"; local rc=$?
  # the lines that matter: summaries, refusals, and every cut that did NOT happen
  printf '%s\n' "$out" | grep -E "ranges,|violation|dropped|SKIPPED|DROPPED|NOT made|gap\(s\)|cues|refusing|wrote|!!|Error|error" \
    | grep -v "^  wrote" | sed 's/^/   /'
  if [ $rc -ne 0 ]; then
    printf '%s\n' "$out" | tail -8 | sed 's/^/   | /'
    echo "rebuild stopped at: $label"; exit $rc
  fi
}

cd "$EDIT" || exit 1
[ -f "transcripts/take1.audible.json" ] || { echo "rebuild: no measured transcript. Run lc intake first." >&2; exit 1; }
# One take only. On a stitched lesson build_edl writes edl-<take>.json and leaves
# edl.json alone, so this chain would wipe pause_cuts.py and report "rebuilt"
# while nothing was rebuilt.
TAKES=0; for f in ../take*.mov ../take*.mp4 ../take*.MOV ../take*.MP4; do [ -f "$f" ] && TAKES=$((TAKES+1)); done
if [ "$TAKES" -gt 1 ] || ls edl-take*.json >/dev/null 2>&1; then
  echo "rebuild: this is a stitched (multi-take) lesson, and rebuild handles one take." >&2
  echo "        Build each take with 'lc build_edl --source takeN --write', then 'lc merge_edl ... --write'." >&2
  exit 1
fi
printf 'PAUSE_CUTS = []\n' > pause_cuts.py
run "build_edl (speech cuts only)" "$PY" "$HERE/build_edl.py" --write
run "tighten_gaps ${NUMS[*]}"      "$PY" "$HERE/tighten_gaps.py" "${NUMS[@]}"
run "build_edl (with pause cuts)"  "$PY" "$HERE/build_edl.py" --write
[ "$CAPS" = 1 ] && run "build_captions" "$PY" "$HERE/build_captions.py" .
echo "rebuilt. Any SKIPPED line above is a cut that did not happen: widen it, or accept it in writing."
