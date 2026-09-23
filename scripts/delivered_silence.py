#!/usr/bin/env python3
"""Dead-air sweep over the DELIVERED timeline, measured the way the GATE
measures it (ledger rules 73, 106, 110).

Rule 73 said the sweep must be audio-driven rather than transcript-driven. It did
not say WHICH audio. Sweeping the source and then cutting is not the same test:
every boundary the cut places creates a new join, and residue that sits at the
tail of a kept range is invisible in a source sweep because the source has speech
right after it. The operator found a 2.3s hole at output 02:20 that the source sweep
had scored as part of a 7.9s window I had cut "all but 2.3s" of.

**Rule 110: this file used to disagree with the gate and say OK anyway.** It
thresholded at the file's own 90th percentile minus 20 dB (0.0066 on one lesson)
while `qc.py` runs ffmpeg `silencedetect=noise=-40dB:d=2.0`, a FIXED 0.01. The
lower bar ends a run sooner, so this file reported 2.05s and 2.55s where the gate
measured 2.7s and 3.3s, printed "ceiling 2.5s: OK", and the lesson went to a
70-minute 4K render that then failed the gate on both windows. A pre-flight check
must run the downstream test, not a cousin of it: this now assembles the
delivered audio and hands it to the same silencedetect the gate uses.

    lc delivered_silence [min_run_seconds] [max_allowed_seconds]

Exits NON-ZERO when any delivered window exceeds max_allowed (default 2.5s, the
KEEP_DEMO_S ceiling an earlier cut list settled on). That matters more than it
sounds: on one lesson this check printed twelve windows, the run was piped
through `tail -12`, the LARGEST window was the first line and scrolled off, and
the report went out saying every window was justified -- from a list that had
been truncated. A check you have to read is a check you can truncate; a check
that exits non-zero is one you cannot (rule 106).

The gate ALSO forgives a long window whose picture is working (rule 54): it fails
only when the screen moved in <= 1/3 of the window's seconds. Where `picture.py`
can classify this source, each window is annotated `live/total`, so a window that
is over the ceiling but visibly alive can be judged rather than guessed at.
"""
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

import lcenv                       # plugin: the tools live outside the project
HERE = lcenv.edit_dir(__file__)
_c = [HERE.parent / f"take1{e}" for e in (".mov", ".mp4", ".MOV", ".MP4")]
SRC = next((c for c in _c if c.exists()), _c[0])
SR = 16000
MIN_RUN = float(sys.argv[1]) if len(sys.argv) > 1 else 2.0
# The KEEP_DEMO_S ceiling from an earlier cut list. A window whose SCREEN is
# busy does not get more than this; "the blocks were high" is not a defence
# (rule 106).
MAXLEN = float(sys.argv[2]) if len(sys.argv) > 2 else 2.5
# qc.py's own constant. Changing it here without changing it there re-opens
# exactly the gap rule 110 came from.
NOISE_DB = -40.0

edl = json.loads((HERE / "edl.json").read_text())
raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(SRC), "-vn", "-ac", "1",
                      "-ar", str(SR), "-f", "s16le", "-"], capture_output=True).stdout
A = np.frombuffer(raw, dtype=np.int16)

parts, marks, out = [], [], 0.0
for r in edl["ranges"]:
    i0, i1 = int(r["start"] * SR), int(r["end"] * SR)
    parts.append(A[i0:i1])
    marks.append((out, r["start"], (i1 - i0) / SR))
    out += (i1 - i0) / SR
D = np.concatenate(parts)

with tempfile.TemporaryDirectory() as td:
    wav = Path(td) / "delivered.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "s16le", "-ar", str(SR), "-ac", "1",
                    "-i", "-", "-y", str(wav)], input=D.tobytes(), check=True)
    p = subprocess.run(
        ["ffmpeg", "-v", "info", "-i", str(wav),
         "-af", f"silencedetect=noise={NOISE_DB}dB:d={MIN_RUN}", "-f", "null", "-"],
        capture_output=True, text=True)
sil = [(float(a), float(b)) for a, b in
       re.findall(r"silence_start: ([\d.-]+)[\s\S]*?silence_duration: ([\d.]+)", p.stderr)]


def src_of(t):
    for o, s, L in marks:
        if t < o + L:
            return s + (t - o)
    return marks[-1][1] + marks[-1][2]


classify = None
try:
    sys.path.insert(0, str(HERE))
    import picture                                     # noqa: E402
    classify = picture.classify
except Exception:
    pass

print(f"delivered {out:.1f}s  silencedetect noise={NOISE_DB}dB d={MIN_RUN}s "
      f"(the gate's own instrument):")
tot, shown = 0.0, []
for x, d in sil:
    x = max(0.0, x)
    y = x + d
    tot += d
    shown.append((x, y))
    a, b = src_of(x), src_of(y)
    note = ""
    # Only annotate a window that lies inside ONE kept range. A window that
    # spans a join covers removed source between its ends, so classifying
    # a..b would measure material the viewer never sees and call a live window
    # static. The gate classifies the DELIVERED picture and is right by
    # construction; this annotation is a hint, and a hint that can be wrong in
    # the reassuring direction is worse than none.
    same = [1 for o, s0, L in marks if o <= x and y <= o + L]
    if classify is not None and b > a and same:
        try:
            live, total = classify(a, b)[:2]
            note = f"   screen {live}/{total}s" + ("  STATIC" if live <= total / 3 else "")
        except Exception:
            note = ""
    elif not same:
        note = "   (spans a join)"
    print(f"  out {int(x)//60:02d}:{x%60:05.2f}-{int(y)//60:02d}:{y%60:05.2f} "
          f"({d:5.2f}s)   src {a:8.2f}-{b:8.2f}{note}")
print(f"  {tot:.1f}s total in runs >= {MIN_RUN}s")
# 0.15, not 0.05. A window measured at exactly the ceiling compares
# 2.55 > 2.55 and fails on float noise alone -- the third time in one day a
# boundary test without a real tolerance cried wolf (rules 84, 104, 105).
# 150ms is inaudible and well under anything the operator has ever flagged.
over = [(x, y) for x, y in shown if y - x > MAXLEN + 0.15]
if over:
    print(f"\n  !! {len(over)} window(s) over the {MAXLEN}s ceiling:")
    for x, y in over:
        print(f"     out {int(x)//60:02d}:{x%60:05.2f}   {y-x:6.2f}s")
    raise SystemExit(1)
print(f"  ceiling {MAXLEN}s: OK")
