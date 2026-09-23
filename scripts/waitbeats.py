#!/usr/bin/env python3
"""Contact sheet of every long-wait beat tighten_gaps.py kept (rule 160).

tighten_gaps.py shortens a long wordless wait to ~0.9s and keeps the BUSIEST
picture in it. "Busiest" is a proxy for "Claude working", and the proxy can pick
a DETOUR instead: on one real lesson the busiest 0.9s of a 45s wait was a
settings panel opened while waiting, so the delivered cut flashed an unrelated
panel between two frames of the tool working.
No check reads the picture of a wait beat for meaning, so this puts every beat
on one sheet, each row = the frame before the join | the kept beat | the frame
after, for an eye to scan in a minute.

  lc waitbeats              # writes waitbeats_NN.jpg next to edl.json
"""
import json
import re
import subprocess
from pathlib import Path

import lcenv                       # plugin: the tools live outside the project
HERE = lcenv.edit_dir(__file__)
edl = json.loads((HERE / "edl.json").read_text())
src = Path(next(iter(edl["sources"].values())))
if not src.is_absolute():
    src = (HERE / src).resolve()
pc = (HERE / "pause_cuts.py").read_text()
waits = [(float(a), float(b)) for a, b in
         re.findall(r"\(\s*([\d.]+),\s*([\d.]+),\s*'rule 150: [\d.]+s wait", pc)]
ranges = edl["ranges"]
beats = []
for k, r in enumerate(ranges):
    # a kept range sitting between two wait cuts is a wait beat
    if any(abs(b - r["start"]) < 0.02 for a, b in waits) and \
       any(abs(a - r["end"]) < 0.02 for a, b in waits):
        prev_t = ranges[k - 1]["end"] - 0.3 if k else r["start"]
        next_t = ranges[k + 1]["start"] + 0.3 if k + 1 < len(ranges) else r["end"]
        beats.append((prev_t, (r["start"] + r["end"]) / 2, next_t))
if not waits:
    print("no long waits in this cut (pause_cuts.py has no wait trims), nothing to check")
    raise SystemExit(0)
if not beats:
    # Wait cuts exist but no kept range sits between two of them: the matcher
    # measured nothing, which must never read as a pass.
    raise SystemExit(f"{len(waits)} wait cut(s) in pause_cuts.py but no kept beat matched them; "
                     "rebuild with `lc rebuild` and re-run")
tmp = HERE / "_waitbeats"
tmp.mkdir(exist_ok=True)
rows = []
for i, (p, m, n) in enumerate(beats):
    tiles = []
    for j, t in enumerate((p, m, n)):
        f = tmp / f"b{i:03d}_{j}.jpg"
        subprocess.run(["nice", "-n", "15", "ffmpeg", "-v", "error", "-y", "-ss", f"{t:.2f}",
                        "-i", str(src), "-frames:v", "1", "-vf",
                        f"scale=480:-1,drawtext=text='{i:02d} {t:.1f}':x=6:y=6:fontsize=20:"
                        "fontcolor=yellow:box=1:boxcolor=black", str(f)], check=True)
        tiles.append(f)
    rows.append(tiles)
PER = 8
for s in range(0, len(rows), PER):
    chunk = rows[s:s + PER]
    ins = sum((["-i", str(t)] for row in chunk for t in row), [])
    n = len(chunk) * 3
    layout = "|".join(f"{(k % 3) * 480}_{(k // 3) * 270}" for k in range(n))
    out = HERE / f"waitbeats_{s // PER:02d}.jpg"
    subprocess.run(["ffmpeg", "-v", "error", "-y", *ins, "-filter_complex",
                    f"xstack=inputs={n}:layout={layout}:fill=black", str(out)], check=True)
    print(out.name, f"beats {s:02d}-{s + len(chunk) - 1:02d}")
print(f"{len(beats)} wait beats; each row = before | KEPT BEAT | after")
