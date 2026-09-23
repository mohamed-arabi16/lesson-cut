#!/usr/bin/env python3
"""Enforce the silence ceiling on the ASSEMBLED timeline, not on one source of cuts.

A source-side pause trimmer (an earlier tool, not shipped here) sizes wordless
REGIONS in the source. It cannot see the speech cuts, truncation cuts and
head/tail cuts the editor authors, and every one of those creates a new join.
Two regions each trimmed to a legal 2.2s, with a truncated word cut out between
them, deliver one continuous quiet run of 2.8s: each part legal, the whole
illegal. One lesson shipped 16 such windows past a trimmer that had already been
corrected four times, because the ceiling is a property of the DELIVERED
timeline and was being enforced on an input to it.

So: measure what `qc.py` will measure, on the timeline as assembled, and emit the
extra cuts. For each window over the ceiling, take the excess out of its LONGEST
word-free source segment (the one most likely to be genuine dead screen rather
than the breath around a word): trim that segment's head, or cut it whole when
it is barely longer than the excess.

    lc tighten [ceiling] [static_floor]     # prints EXTRA_CUTS
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
# Which take this run works on (see build_edl.py). A lesson recorded in two
# sittings is a normal case; every cutting tool has to be pointable at the take
# being cut, because a timestamp only means something against its own take.
#   lc tighten --source take2 ...
SOURCE = "take1"
for _i, _a in enumerate(sys.argv):
    if _a == "--source" and _i + 1 < len(sys.argv):
        SOURCE = sys.argv[_i + 1]
        del sys.argv[_i:_i + 2]
        break
if not re.fullmatch(r"take\d+", SOURCE):
    sys.exit(f"--source must look like take1/take2, got {SOURCE!r}")
_c = [HERE.parent / f"{SOURCE}{e}" for e in (".mov", ".mp4", ".MOV", ".MP4")]
SRC = next((c for c in _c if c.exists()), _c[0])
SR = 16000
NOISE_DB = -40.0
MIN_RUN = 2.0
CEILING = float(sys.argv[1]) if len(sys.argv) > 1 else 2.5
STATIC_FLOOR = float(sys.argv[2]) if len(sys.argv) > 2 else 2.0
MARGIN = 0.25          # aim this far under the bar, so rounding cannot cross it

# On a stitch, tighten runs against the take being cut, not the merged file:
# its output->source mapping assumes one source, and a merged EDL has two.
_EDL = HERE / ("edl.json" if SOURCE == "take1" else f"edl-{SOURCE}.json")
edl = json.loads(_EDL.read_text())
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
    wav = Path(td) / "d.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "s16le", "-ar", str(SR), "-ac", "1",
                    "-i", "-", "-y", str(wav)], input=D.tobytes(), check=True)
    p = subprocess.run(["ffmpeg", "-v", "info", "-i", str(wav), "-af",
                        f"silencedetect=noise={NOISE_DB}dB:d={MIN_RUN}", "-f", "null", "-"],
                       capture_output=True, text=True)
sil = [(max(0.0, float(a)), max(0.0, float(a)) + float(d)) for a, d in
       re.findall(r"silence_start: ([\d.-]+)[\s\S]*?silence_duration: ([\d.]+)", p.stderr)]


def segments(x, y):
    """The source spans a delivered window is assembled from."""
    o = []
    for ostart, s, L in marks:
        a, b = max(x, ostart), min(y, ostart + L)
        if b > a:
            o.append((s + (a - ostart), s + (b - ostart)))
    return o


# The measured audible extents, the same file build_edl and build_captions read.
#
# A silencedetect window can still CONTAIN an audible token. measure_tokens finds
# slivers that silencedetect's own -40dB/2.0s threshold does not register -- a
# 100ms tail on a 1.2s logged span -- and a cut placed over one drops a real word
# while leaving the sentence around it intact and broken. On one lesson that
# clipped «أدري» out of «خلص ما أدري» and «تخلص» off the end of «نشوف هاي شو
# اسمها بس تخلص» (rule 76: a cut chosen to remove silence can remove the good
# take). build_edl CANNOT catch this: the word is inside a cut span the editor
# declared, so its post-condition passes by construction. The guard has to live
# here, where the span is chosen.
try:
    WORDS = json.loads((HERE / "transcripts" / f"{SOURCE}.audible.json").read_text())
except Exception:
    WORDS = []


def word_free(a, b, guard=0.04):
    """Sub-intervals of [a, b], in SOURCE seconds, that hold no audible token."""
    out, cur = [], a
    for w in WORDS:
        if w["end"] + guard <= cur or w["start"] - guard >= b:
            continue
        if w["start"] - guard > cur:
            out.append((cur, w["start"] - guard))
        cur = max(cur, w["end"] + guard)
    if cur < b:
        out.append((cur, b))
    return [s for s in out if s[1] - s[0] > 0]


sys.path.insert(0, str(HERE))
try:
    import picture
except Exception:
    picture = None

try:
    from PIL import Image
except Exception:
    Image = None

# qc.py's frozen_check, replicated exactly, and pointed at the DELIVERED window.
#
# This used to call picture.classify() on each source span. Both tools count
# "8x8 blocks that moved", but they reduce the block differently:
#
#     picture.blocks_changed : d.reshape(...).MAX(axis=(1,3)) > 8
#     qc.frozen_check        : d.reshape(...).MEAN(axis=(1,3)) > 8
#
# A max lights a whole block from one changed pixel, so a caret, a spinner dot or
# a single antialiased edge reads as a live second. On one lesson two windows
# scored live 1/2 under the max and live 0/2 under the mean, which is the gate's
# fail condition -- tighten.py passed them and qc.py would have failed the render
# an hour later. Rule 110 in a third file: when a local check and the gate
# measure the same property, the local check runs the GATE's instrument.
#
# Sampling is on the delivered window mapped back through the EDL rather than
# per source span, so a window that spans a join is judged on the frames the
# viewer actually sees, including the join itself.
# DERIVED from picture.INSET, not hardcoded (2026-08-28, rule 103 applied to the
# webcam circle). qc.frozen_check's own default is (0, 264, 88, 360), which fits
# the circle on some sources and clips it on others: one lesson's was x 4-82,
# y 277-355 and another's was x 8-107, y 248-347, bigger and higher. An
# unmasked sliver of a MOVING face makes a frozen window read as live, which is
# how dead air survives (rule 72), so the mask has to follow the source.
# picture.INSET is re-measured per lesson; deriving from it means re-measuring
# once fixes both tools instead of one. Note the orders differ:
#   picture.INSET  = (x0, x1, y0, y1)
#   frozen_check   = (x0, y0, x1, y1)
if picture is not None and getattr(picture, "INSET", None):
    _px0, _px1, _py0, _py1 = picture.INSET
    QC_INSET = (_px0, _py0, _px1, _py1)
else:
    QC_INSET = (0, 264, 88, 360)      # qc.frozen_check's default
_mask = np.ones((45, 80), dtype=bool)
_mask[QC_INSET[1] // 8:QC_INSET[3] // 8, QC_INSET[0] // 8:QC_INSET[2] // 8] = False


def _src_of(t):
    for ostart, s, L in marks:
        if t < ostart + L:
            return s + (t - ostart)
    return marks[-1][1] + marks[-1][2]


def _frame(t):
    if Image is None:
        return None
    with tempfile.TemporaryDirectory() as td:
        o = Path(td) / "s.png"
        rc = subprocess.run(
            ["ffmpeg", "-y", "-ss", f"{t:.3f}", "-i", str(SRC), "-frames:v", "1",
             "-vf", "scale=640:360", "-update", "1", str(o)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode
        if rc != 0 or not o.exists():
            return None
        return np.asarray(Image.open(o).convert("L"), dtype=np.float64)


def _live_at(x, dur, phase):
    n = max(2, int(dur) + 1)
    frames = [f for f in (_frame(_src_of(x + phase + i)) for i in range(n))
              if f is not None]
    if len(frames) < 2:
        return None
    live = 0
    for a, b in zip(frames, frames[1:]):
        blocks = np.abs(a - b)[:360, :640].reshape(45, 8, 80, 8).mean(axis=(1, 3))
        if int((blocks[_mask] > 8).sum()) > 4:
            live += 1
    return live, len(frames) - 1


# Sample at several phases and take the WORST (most static) reading.
#
# The window's start is wherever silencedetect put it, and this file and the gate
# run silencedetect over different audio: this one over the assembled source, the
# gate over final.mp4 AFTER loudnorm has lifted it by ~9 dB. The same window
# therefore starts up to a few hundred ms apart in the two tools, every sample
# point shifts with it, and a window sitting near the threshold flips verdict on
# that shift alone. On one lesson this file read the window at out 585.65 as live
# 1/2 and passed it; the gate read the same window at out 585.90 as live 0/2 and
# failed the render, 45 minutes later.
#
# A phase-invariant answer is the only honest one, so take the minimum. A window
# that any reasonable phase calls frozen gets trimmed. The cost of being wrong in
# this direction is a fraction of a second of screen time; the cost of being
# wrong in the other direction is a whole re-render.
PHASES = (0.0, 0.25, 0.5)


def is_static(x, y):
    """Will qc.py call this DELIVERED window frozen? x, y are output seconds."""
    dur = y - x
    worst = None
    for ph in PHASES:
        got = _live_at(x, dur, ph)
        if got is None:
            continue
        live, total = got
        if not total:
            continue
        ratio = live / total
        if worst is None or ratio < worst[0]:
            worst = (ratio, live, total)
    if worst is None:
        return False                       # cannot measure -> do not invent a cut
    ratio, live, total = worst
    return live <= total / 3


print("EXTRA_CUTS = [")
n = skipped = partial = 0
for x, y in sil:
    segs = segments(x, y)
    if not segs:
        continue
    static = is_static(x, y)
    bar = STATIC_FLOOR if static else CEILING
    length = y - x
    # Match the tolerance the gate mirror uses. Triggering at bar-0.05 makes this
    # loop chase windows measured at 2.49s and 2.50s that the gate passes, and a
    # pass that never reaches zero is a pass nobody can read (rules 84/107c: a
    # boundary test without a real tolerance cries wolf).
    if length <= bar + 0.10:
        continue
    excess = length - (bar - MARGIN)
    # Longest span that holds no audible token, NOT longest span (see word_free).
    cands = [s for seg in segs for s in word_free(*seg)]
    if not cands:
        print(f"    # NOT CUT: window at out {x:.2f}-{y:.2f} runs {length:.2f}s over "
              f"the {bar}s bar, but every source span in it contains an audible "
              f"token. Author a speech cut for it by hand.")
        skipped += 1
        continue
    a, b = max(cands, key=lambda s: s[1] - s[0])
    if b - a <= excess + 0.10:                            # cut the whole span
        ca, cb = a, b
    else:
        ca, cb = a, a + excess                            # trim its head
    if cb - ca < 0.08:
        print(f"    # NOT CUT: window at out {x:.2f}-{y:.2f} runs {length:.2f}s over "
              f"the {bar}s bar; the largest word-free span in it is only "
              f"{b - a:.2f}s. Author a speech cut for it by hand.")
        skipped += 1
        continue
    if cb - ca < excess - 0.10:
        print(f"    # PARTIAL: window at out {x:.2f}-{y:.2f} needs {excess:.2f}s but "
              f"only {cb - ca:.2f}s of it is word-free; it stays "
              f"{length - (cb - ca):.2f}s, over the {bar}s bar.")
        partial += 1
    n += 1
    tag = "static" if static else "screen works"
    print(f"    ({ca:8.2f}, {cb:8.2f}, \"delivered window {length:.2f}s over the "
          f"{bar}s bar ({tag}); assembled from {len(segs)} span(s)\", 0.0, False, False),")
print("]")
print(f"# {n} window(s) tightened"
      + (f", {partial} only PARTIALLY" if partial else "")
      + (f", {skipped} NOT CUT and needing a hand-authored speech cut" if skipped else ""))
