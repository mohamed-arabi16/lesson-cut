#!/usr/bin/env python3
"""Wordless gaps in the DELIVERED cut, measured from the transcript (rule 142).

Why this exists:

An earlier pause generator (not shipped here) sized its windows with ffmpeg
`silencedetect=noise=-40dB`, and so does `qc.py`. When that generator under-cuts
a window, the gate agrees with it, because they are the same instrument asking
the same question. On one lesson the generator fell back to Scribe's raw
transcript (measure_tokens.py had not run yet), clamped a 26.6s wordless region
down to 2.8s because «ونبحث» is LOGGED at 478.10 and actually spoken at 501.98,
and emitted a 0.85s cut. Thirty seconds of dead air went into the EDL.
`build_edl.py` post-conditions passed. `qc.py` would have passed. The only thing
that found it was reading the delivered cut and noticing the clock jumped 32
seconds between two spoken lines.

So this check asks a different question with a different instrument: **between
two consecutive words the viewer actually hears, how long is the silence?** A
word is what ends a pause (the same premise that earlier generator used),
audible extents come from `measure_tokens.py`, and nothing here consults an audio
threshold, so it cannot agree with the generator by construction.

    lc gapcheck [ceiling]        # default 2.5s, exits non-zero on a fail
"""
import json
import math
import sys
from pathlib import Path

import lcenv                       # plugin: the tools live outside the project
HERE = lcenv.edit_dir(__file__)
OUT_FPS = float(lcenv.project_config(HERE).get("render", {}).get("fps", 30))
_nums = [a for a in sys.argv[1:] if not a.startswith("-")]
CEILING = float(_nums[0]) if _nums else 2.5


def quantised(dur):
    return math.ceil(round(dur * OUT_FPS, 6)) / OUT_FPS


def main():
    edl = json.loads((HERE / "edl.json").read_text())
    words = {}
    for name in edl["sources"]:
        p = HERE / "transcripts" / f"{name}.audible.json"
        if not p.exists():
            raise SystemExit(f"gapcheck: {p.name} missing -- run measure_tokens.py first")
        words[name] = json.loads(p.read_text())

    kept = []          # (out_start, out_end, text, source, src_start, src_end)
    clock = 0.0
    for r in edl["ranges"]:
        for w in words[r["source"]]:
            if r["start"] <= w["start"] and w["end"] <= r["end"]:
                kept.append((clock + w["start"] - r["start"],
                             clock + w["end"] - r["start"], w["text"],
                             r["source"], w["start"], w["end"]))
        clock += quantised(r["end"] - r["start"])
    kept.sort()

    fails = []
    # Lead-in and tail count too: a delivered file that opens on four seconds of
    # nothing is the same defect as one with a hole in the middle.
    edges = []
    if kept:
        edges.append((0.0, kept[0][0], "(start)", kept[0][2], None, kept[0][4]))
    for i in range(len(kept) - 1):
        edges.append((kept[i][1], kept[i + 1][0], kept[i][2], kept[i + 1][2],
                      kept[i][5], kept[i + 1][4]))

    if kept:
        edges.append((kept[-1][1], clock, kept[-1][2], "(end)", kept[-1][5], None))
    # minutes are FLOORED: :.0f rounded 1:45 up to "2:45"
    print(f"delivered {int(clock // 60)}:{clock % 60:04.1f}, {len(kept)} words, ceiling {CEILING}s")
    emit = "--emit" in sys.argv
    tuples = []
    for a, b, before, after, sa, sb in edges:
        if b - a > CEILING:
            fails.append((a, b - a, before, after))
            _src = (f"src {sa:8.2f}-{sb:8.2f}" if sa is not None and sb is not None
                    else "at the " + ("start" if sa is None else "end"))
            print(f"  X  {int(a // 60):3d}:{a % 60:05.2f}  {b-a:6.2f}s wordless   "
                  f"{_src}   «{before}» -> «{after}»")
            # Keep TARGET seconds in the middle of the source gap and cut the
            # rest. The middle is the safe slice: the head still carries the
            # tail of the last word's reverb and the foot the in-breath before
            # the next one, and neither edge can land inside a word because
            # both bounds ARE word boundaries.
            if emit and sa is not None and sb is not None and sb - sa > CEILING:
                target = max(0.8, CEILING - 0.42)   # builder pads 0.12 x2, plus margin
                mid = (sa + sb) / 2.0
                ka, kb = mid - target / 2, mid + target / 2
                tuples.append((round(sa + 0.10, 2), round(ka, 2),
                               f"delivered gap {b-a:.1f}s (gapcheck); head"))
                tuples.append((round(kb, 2), round(sb - 0.10, 2),
                               f"delivered gap {b-a:.1f}s (gapcheck); tail"))
    if emit:
        print("\nGAP_CUTS = [")
        for a, b, why in tuples:
            if b - a > 0.10:
                print(f"    ({a:8.2f}, {b:8.2f}, {why!r}, 0.0, False, False),")
        print("]")
    if not fails:
        print(f"  ok  no wordless gap over {CEILING}s")
    else:
        print(f"\n  {len(fails)} gap(s) over the ceiling, "
              f"{sum(f[1] for f in fails):.1f}s total")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
