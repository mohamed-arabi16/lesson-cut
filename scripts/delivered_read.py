#!/usr/bin/env python3
"""Emit the DELIVERED cut as readable prose, with every join marked.

Rule 127. The gate is a defect detector, not an editor. One lesson passed 6/6 and
was uploaded before a plain read of the delivered transcript turned up eleven
things worth cutting: twelve seconds of «آآآه. شو في عندنا هون؟ Mm. Okay.» over a
half-read screen card, two abandoned sentences, six duplicated phrases, and a
verdict that landed four times. The operator then had to ask for that read twice,
which is what makes it a pipeline step rather than a favour.

Why this file exists rather than "read the transcript":

  * The artifact has to be built from `edl.json`, not from the source transcript.
    The defects that matter are the ones the CUT created or left adjacent, and
    they are invisible in the source, where the two halves can be half a minute
    apart. «بكل بساطة.» and its restart were 27 seconds apart in the take and
    2.55 seconds apart in the delivery.
  * Every join must be visible while reading, with how much source it removed,
    because a join is where a non-sequitur gets manufactured.
  * Output times, not source times, so anything found can be described to the operator
    in the timecodes of the file he will actually watch (rule 100).

What it does NOT do: judge. It builds the thing a person reads. The three
questions to hold while reading are the operator's own, in their order:

    1. Does anything not make sense?  (a join that manufactured a non-sequitur,
       a sentence he abandoned, a reference to something that was cut)
    2. Does anything still need deleting?
    3. Is anything repeated?  (the mechanical half is post_cut_check's n-gram and
       adjacent-duplicate scans, but a point can land four times in four
       different wordings and trip neither)

    lc delivered_read [edit_dir]        # default: the project's edit dir
"""
import json
import sys
from pathlib import Path

import lcenv                       # plugin: the tools live outside the project
HERE = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else lcenv.edit_dir(__file__)
EDL = HERE / "edl.json"
edl = json.loads(EDL.read_text())

# One transcript PER SOURCE. A stitched lesson's EDL carries two takes, and a
# range's timestamps only mean something against its own take's transcript: read
# take 2's ranges against take 1's words and every line comes out wrong while the
# file still looks well formed. Keyed exactly as build_captions.py and qc.py key
# theirs, so all three agree about which words belong to which range.
WORDS = {}
for key, src in edl["sources"].items():
    stem = Path(src).stem
    aud = HERE / "transcripts" / f"{stem}.audible.json"
    raw = HERE / "transcripts" / f"{stem}.json"
    if aud.exists():
        WORDS[key] = json.loads(aud.read_text())
    elif raw.exists():
        WORDS[key] = [w for w in json.loads(raw.read_text())["words"]
                      if w.get("type") == "word" and w.get("start") is not None]
    else:
        sys.exit(f"no transcript for source {key!r} (looked for {aud.name} and {raw.name})")

ranges = edl["ranges"]


# Delivered time on the RENDERER's grid: ffmpeg emits ceil(dur * fps) frames per
# range, so the finished file runs up to one frame longer per join than the raw
# EDL. Summing raw durations drifted up to 12s early on an 800-join lesson.
_FPS = float(lcenv.project_config(HERE).get("render", {}).get("fps", 30))


def _q(dur):
    import math
    return math.ceil(round(dur * _FPS, 6)) / _FPS


def mmss(t):
    return f"{int(t // 60):02d}:{t % 60:05.2f}"


out = 0.0
lines = []
total_removed_at_joins = 0.0
for idx, r in enumerate(ranges):
    s, e = r["start"], r["end"]
    words = WORDS[r["source"]]
    kept = [w for w in words if s < w["end"] <= e]
    if idx > 0:
        gap = s - ranges[idx - 1]["end"]
        prev = ranges[idx - 1]
        if prev["source"] != r["source"]:
            # A take boundary is not a join: the two numbers are on different
            # clocks, so a "removed Ns" figure across it would be meaningless.
            lines.append(f"\n   ==== TAKE CHANGE {idx:02d}   {prev['source']} ends {prev['end']:8.2f} "
                         f"-> {r['source']} starts {s:8.2f}   (different timelines, "
                         f"nothing 'removed' here) ====")
        else:
            total_removed_at_joins += gap
            lines.append(f"\n   ---- JOIN {idx:02d}   removed {gap:6.2f}s of source "
                         f"({prev['end']:8.2f} -> {s:8.2f}) ----")
    buf, t0 = [], None
    for w in kept:
        if t0 is None:
            t0 = out + (w["start"] - s)
        buf.append(w["text"])
        if w["text"].endswith(("،", ".", "؟", "!", "…")) or len(buf) >= 15:
            lines.append(f"[{mmss(t0)}] {' '.join(buf)}")
            buf, t0 = [], None
    if buf:
        lines.append(f"[{mmss(t0)}] {' '.join(buf)}")
    out += _q(e - s)

kept_n = sum(1 for r in ranges for w in WORDS[r["source"]] if r["start"] < w["end"] <= r["end"])
total_w = sum(len(v) for v in WORDS.values())
print(f"# DELIVERED CUT -- {len(ranges)} ranges, {mmss(out)}, {kept_n} of {total_w} words kept")
print(f"# sources: {', '.join(edl['sources'])}")
print(f"# {len(ranges)-1} joins, {total_removed_at_joins:.1f}s of source removed at them")
print("#")
print("# Read this in order, holding three questions:")
print("#   1. does anything not make sense (a join that made a non-sequitur, an abandoned sentence)")
print("#   2. does anything still need deleting")
print("#   3. is anything repeated (a point can land four times in four wordings and trip no scan)")
print("\n".join(lines))
