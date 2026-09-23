#!/usr/bin/env python3
"""Measure caption glyph extents through libass BEFORE the render.

`qc.py caption-px` does this on final.mp4, which costs a 40-minute render to
find out. This runs the SAME path -- the ass filter, at the delivery
resolution -- over a synthetic black source, so an over-wide line is caught in
seconds. Reports the worst left/right extents against the frame edge.
"""
import re, subprocess, sys, tempfile
from pathlib import Path
import numpy as np
from PIL import Image

import lcenv                       # plugin: the tools live outside the project
H = lcenv.edit_dir(__file__)

# The frame is the DELIVERED one: the caption canvas (PlayRes, from master.ass)
# scaled so its long edge is render.scale. It used to be a fixed 3840x2160,
# which made the numbers meaningless on a portrait project.
_ass = (H / "master.ass").read_text(encoding="utf-8")
def _playres(key, default):
    m = re.search(rf"^{key}:\s*(\d+)", _ass, re.M)
    return int(m.group(1)) if m else default
PW, PH = _playres("PlayResX", 2560), _playres("PlayResY", 1440)
LONG = int(lcenv.project_config(H).get("render", {}).get("scale", 3840))
W = int(round(PW * LONG / max(PW, PH) / 2) * 2)
HT = int(round(PH * LONG / max(PW, PH) / 2) * 2)
SAFE = max(24, round(60 * max(W, HT) / 3840))   # 60px at 4K, proportional elsewhere

cues = []
for ln in _ass.splitlines():
    if not ln.startswith("Dialogue:"):
        continue
    f = ln.split(",", 9)
    def sec(t):
        hh, mm, ss = t.split(":")
        return int(hh) * 3600 + int(mm) * 60 + float(ss)
    cues.append((sec(f[1]), sec(f[2]), f[9]))

# Longest lines first: those are the ones that can touch an edge. RLE/PDF
# (the RTL embedding on right-to-left lines) are escapes, never literals: a
# literal bidi control is invisible in source and GitHub flags the file.
def longest(c):
    return max(len(p) for p in c[2].replace("\u202b", "").replace("\u202c", "").split("\\N"))
order = sorted(range(len(cues)), key=lambda i: -longest(cues[i]))
n = int(sys.argv[1]) if len(sys.argv) > 1 else 60
worst_l, worst_r, measured = W, 0, 0
with tempfile.TemporaryDirectory() as td:
    for i in order[:n]:
        a, b, _ = cues[i]
        t = (a + b) / 2
        o = Path(td) / "f.png"
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
             "-i", f"color=c=black:s={W}x{HT}:d=1:r=25",
             "-vf", f"setpts=PTS+{t}/TB,ass='{lcenv.filter_safe_path(H / 'master.ass')}'",
             "-frames:v", "1", "-update", "1", str(o)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if not o.exists():
            continue
        px = np.asarray(Image.open(o).convert("L"))
        xs = np.nonzero(px.max(axis=0) > 40)[0]
        if xs.size == 0:
            continue
        measured += 1
        worst_l = min(worst_l, int(xs.min()))
        worst_r = max(worst_r, int(xs.max()))
        if xs.min() < SAFE or xs.max() > W - SAFE:
            print(f"  X cue {i} @{t:.2f}s spans x={xs.min()}..{xs.max()}  {cues[i][2][:70]}")
# A pass that measured nothing is a failing pass, not a green one (rule 51).
if measured == 0:
    print("FAIL: measured 0 cues"); sys.exit(1)
print(f"measured {measured} of the widest cues: text spans x={worst_l}..{worst_r} "
      f"in a {W}px frame (clearance {worst_l}px left, {W - worst_r}px right, bar {SAFE}px)")
sys.exit(0 if worst_l >= SAFE and worst_r <= W - SAFE else 1)
