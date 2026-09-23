#!/usr/bin/env python3
"""Audible sound inside KEPT ranges that no transcript word covers (rule 158).

Every other check in this kit reads WORDS: post_cut_check, gapcheck, qc.py's
transcript pass, delivered_read. A stretch of speech-level audio with no Scribe
token under it is invisible to all of them, and it ships as sound with no
caption. Two shapes found on one real lesson:

  * a MURMUR: 3.3s of him reading the run report under his breath at
    -27..-35 dB, never transcribed, sitting between two kept words;
  * a RINGING TAIL: a removed filler («آآآ», «مـ», «ما تبع») whose audio runs
    0.3-0.5s past its measured extent, so the cut ends before the sound does
    (rule 151 at a speech cut's END edge).

Run after every build_edl --write. Reports each run >= MIN_S with its source
and approximate delivered time. A hit is not automatically a defect (a breath,
a click, a key press); judge each one, and extend the adjacent cut or add one.

  lc untranscribed [min_seconds]      # default 0.35
"""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

import lcenv                       # plugin: the tools live outside the project
HERE = lcenv.edit_dir(__file__)
# Delivered time on the RENDERER's grid: ffmpeg emits ceil(dur * fps) frames per
# range, so the finished file runs up to one frame longer per join than the raw
# EDL. Summing raw durations drifted up to 12s early on an 800-join lesson.
_FPS = float(lcenv.project_config(HERE).get("render", {}).get("fps", 30))


def _q(dur):
    import math
    return math.ceil(round(dur * _FPS, 6)) / _FPS


MIN_S = float(sys.argv[1]) if len(sys.argv) > 1 else 0.35
SR, HOP = 16000, 0.05

edl = json.loads((HERE / "edl.json").read_text())
hits_all = []
for src_name, src_path in edl["sources"].items():
    aud_p = HERE / "transcripts" / f"{src_name}.audible.json"
    if not aud_p.exists():
        sys.exit(f"no transcripts/{src_name}.audible.json: run `lc measure_tokens` first")
    words = json.loads(aud_p.read_text())
    src = Path(src_path)
    if not src.is_absolute():
        src = (HERE / src).resolve()
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(src), "-vn", "-ac", "1",
                          "-ar", str(SR), "-f", "s16le", "-"], capture_output=True).stdout
    a = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768
    h = int(SR * HOP)
    n = len(a) // h
    if n == 0:
        sys.exit(f"no audio decoded from {src}")        # rule 51: never pass on nothing
    db = 20 * np.log10(np.sqrt((a[:n * h].reshape(n, h) ** 2).mean(1)) + 1e-9)
    speech = float(np.percentile(db[db > -60], 90))
    thr = speech - 22.0                                   # speech-level, not room tone
    covered = np.zeros(n, bool)
    for w in words:
        lo = w.get("logged_start", w["start"]) - 0.05
        hi = w.get("logged_end", w["end"]) + 0.05
        covered[max(0, int(lo / HOP)):int(hi / HOP) + 1] = True
    out = 0.0
    measured = 0
    for r in edl["ranges"]:
        if r["source"] != src_name:
            out += _q(r["end"] - r["start"])
            continue
        i0, i1 = int(r["start"] / HOP), min(n, int(r["end"] / HOP))
        measured += i1 - i0
        run = None
        for i in range(i0, i1):
            loud = db[i] > thr and not covered[i]
            if loud and run is None:
                run = i
            if (not loud or i == i1 - 1) and run is not None:
                if (i - run) * HOP >= MIN_S:
                    hits_all.append((src_name, run * HOP, i * HOP,
                                     out + run * HOP - r["start"]))
                run = None
        out += _q(r["end"] - r["start"])
    print(f"{src_name}: speech p90 {speech:.1f} dB, threshold {thr:.1f} dB, "
          f"{measured * HOP:.0f}s of kept audio measured")
    if measured == 0:
        sys.exit("measured nothing")                      # rule 51

for s, a, b, o in hits_all:
    print(f"  {s} src {a:8.2f}-{b:8.2f} ({b - a:4.2f}s)  out ~{int(o // 60)}:{o % 60:05.2f}")
print(f"{len(hits_all)} untranscribed audible run(s) >= {MIN_S}s")
