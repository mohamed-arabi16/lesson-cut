#!/usr/bin/env python3
"""Merge per-take EDLs into the one EDL a stitched lesson renders from.

A lesson recorded in two sittings is a normal case (two of the lessons this kit
was built on were). Each take is cut on its OWN timeline with its own cut list,
because a cut number only means something against the take it was measured in.
This joins the results.

    lc merge_edl edl-take1.json edl-take2.json          # report
    lc merge_edl edl-take1.json edl-take2.json --write  # write edl.json

The output is a single EDL whose `sources` and `av_offset_s` carry every take and
whose `ranges` are the inputs concatenated IN THE ORDER GIVEN. Order is the
argument order, never a sort: take 2 continues take 1, and no timestamp in either
file can express that relationship.

Refuses to write if:
  * a source name is claimed by two different files, which would silently make
    half the ranges read from the wrong take;
  * a take contributes no ranges, which means its cut list never ran;
  * `subtitles` disagree between inputs (they must all render one master.ass).
"""
import json
import sys
from pathlib import Path

import lcenv                       # plugin: the tools live outside the project
HERE = lcenv.edit_dir(__file__)
args = [a for a in sys.argv[1:] if not a.startswith("--")]
WRITE = "--write" in sys.argv
if len(args) < 2:
    sys.exit(__doc__)

edls = []
for a in args:
    p = (HERE / a) if not Path(a).is_absolute() else Path(a)
    if not p.exists():
        sys.exit(f"missing: {p}")
    edls.append((p, json.loads(p.read_text())))

# The same file twice is the easy mistake, and duplicating every range is silent:
# the merged EDL is valid, renders, and delivers the lesson twice. Caught by
# self-testing this tool against a case known to be bad (rule 137), which is the
# step whose absence made rule 136's first gate check ship broken.
_seen = {}
for p, e in edls:
    rp = p.resolve()
    if rp in _seen:
        sys.exit(f"{p.name} given twice. Merging an EDL with itself duplicates every "
                 f"range and the result still renders, so nothing downstream would catch it.")
    _seen[rp] = True

# Each take's ranges must come from exactly ONE input. Two inputs both claiming
# `take1` means one of them is the wrong file, whatever their paths say.
_owner = {}
for p, e in edls:
    for r in e.get("ranges", []):
        s = r["source"]
        if s in _owner and _owner[s] != p.name:
            sys.exit(f"source {s!r} has ranges in BOTH {_owner[s]} and {p.name}. "
                     f"In a stitch each take is cut once; refusing to merge.")
        _owner[s] = p.name

sources, offsets, ranges = {}, {}, []
for p, e in edls:
    n = len(e.get("ranges", []))
    if n == 0:
        sys.exit(f"{p.name} has 0 ranges: its cut list never ran. Refusing to merge.")
    for k, v in e["sources"].items():
        if k in sources and sources[k] != v:
            sys.exit(f"source name {k!r} claimed by two different files:\n"
                     f"  {sources[k]}\n  {v}\nRefusing: half the ranges would read the wrong take.")
        sources[k] = v
    for k, v in (e.get("av_offset_s") or {}).items():
        offsets[k] = v
    ranges.extend(e["ranges"])
    print(f"  {p.name:<22} {n:>4} ranges  "
          f"{sum(r['end']-r['start'] for r in e['ranges']):9.2f}s  sources {list(e['sources'])}")

subs = {e.get("subtitles") for _, e in edls}
if len(subs) > 1:
    sys.exit(f"inputs disagree about `subtitles`: {subs}. They must all render one master.ass.")

# Every range must name a source the merged EDL actually carries.
for r in ranges:
    if r["source"] not in sources:
        sys.exit(f"range names source {r['source']!r}, which is not in the merged sources")

merged = {
    "version": edls[0][1].get("version", 1),
    "sources": sources,
    "av_offset_s": offsets,
    "grade": edls[0][1].get("grade", ""),
    "ranges": ranges,
    "overlays": [o for _, e in edls for o in (e.get("overlays") or [])],
    "subtitles": subs.pop(),
    "total_duration_s": round(sum(r["end"] - r["start"] for r in ranges), 3),
}
order = " -> ".join(dict.fromkeys(r["source"] for r in ranges))
print(f"\n  merged: {len(ranges)} ranges, {merged['total_duration_s']:.2f}s "
      f"({merged['total_duration_s']/60:.1f} min), source order {order}")
print(f"  sources: {list(sources)}   av_offset_s: {offsets}")

if WRITE:
    out = HERE / "edl.json"
    out.write_text(json.dumps(merged, ensure_ascii=False, indent=2))
    print(f"  wrote {out}")
else:
    print("  (report only; pass --write to write edl.json)")
