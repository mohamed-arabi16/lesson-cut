#!/usr/bin/env python3
"""Per-second picture-activity classification (ledger rules 66 / 72).

rule 66: count how many 8x8 blocks change, not how much the worst one changes --
         a drifting mouse cursor lights 1-3 blocks, a spinner or a streaming
         response lights 40-900. The circular webcam inset must be masked or it
         reports motion forever.
rule 72: measure PER SECOND. An aggregate over a window answers "did anything
         happen?" when the question is "was it worth the viewer's time?"

  inset            locate the webcam inset by temporal std-dev
  window A B       classify one window, second by second
  sweep            classify every quiet run from analyze.py deadair
"""
import subprocess
import sys
import re
from pathlib import Path

import numpy as np

import lcenv                       # plugin: the tools live outside the project
HERE = lcenv.edit_dir(__file__)
# Which take this run works on (see build_edl.py). A lesson recorded in two
# sittings is a normal case; every cutting tool has to be pointable at the take
# being cut, because a timestamp only means something against its own take.
#   lc picture --source take2 ...
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
GW, GH = 640, 360                     # analysis downscale
BS = 8                                # block size -> 80 x 45 grid
DELTA = 8                             # grey levels a block must move
MOVED_BLOCKS = 4                      # rule 66 threshold


def frames(t0, n, fps=1.0):
    """n greyscale frames starting at t0, one every 1/fps seconds."""
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", f"{t0}", "-i", str(SRC),
         "-frames:v", str(n), "-vf", f"fps={fps},scale={GW}:{GH},format=gray",
         "-f", "rawvideo", "-"], capture_output=True).stdout
    a = np.frombuffer(raw, dtype=np.uint8)
    got = len(a) // (GW * GH)
    return a[:got * GW * GH].reshape(got, GH, GW).astype(np.int16)


# Webcam inset in the 640x360 analysis frame. On the source it was measured on,
# it sits bottom LEFT (another lesson's sat bottom left too, but a third's was
# bottom right -- never inherit this constant, re-measure it per source with
# `picture.py inset`).
# cmd_inset at t=2s returns a robust bbox of x 16-67, y 287-356; std-dev only
# lights the parts of the face that MOVE, so the circle is wider than that.
# Padded out to the corner, which costs nothing: the screen content behind the
# padding is the Finder tag list, which never changes.
# ⚠ THIS IS A PLACEHOLDER, NOT A MEASUREMENT (rule 103). Re-measure per source
# and per TAKE: on one stitched lesson the webcam moved between take 1
# (x 6-78, y 269-347) and take 2 (x 18-83, y 275-360), recorded hours apart.
# std-dev finds it only where the SCREEN is static; on a take where a build runs
# throughout, measure the circle off a full-res frame instead.
INSET = (0, 100, 250, 360)            # x0, x1, y0, y1


def blocks_changed(f0, f1, mask_inset=True):
    d = np.abs(f1 - f0)
    if mask_inset:
        x0, x1, y0, y1 = INSET
        d[y0:y1, x0:x1] = 0
    h, w = (GH // BS) * BS, (GW // BS) * BS
    b = d[:h, :w].reshape(h // BS, BS, w // BS, BS).max(axis=(1, 3))
    return int((b > DELTA).sum())


def cmd_inset():
    """Temporal std-dev over a window where the SCREEN is known static."""
    f = frames(2.0, 10, fps=2.0)
    sd = f.astype(np.float64).std(axis=0)
    hot = sd > 6.0
    ys, xs = np.nonzero(hot)
    print(f"frames {len(f)}  hot pixels {hot.sum()}")
    if len(xs):
        print(f"  bbox in {GW}x{GH}: x {xs.min()}-{xs.max()}  y {ys.min()}-{ys.max()}")
        print(f"  bbox in 3840x2160: x {xs.min()*6}-{xs.max()*6}  y {ys.min()*6}-{ys.max()*6}")
    # column/row profile so a stray hot pixel does not blow the bbox out
    cols = np.nonzero(hot.sum(axis=0) > 3)[0]
    rows = np.nonzero(hot.sum(axis=1) > 3)[0]
    if len(cols) and len(rows):
        print(f"  robust: x {cols.min()}-{cols.max()}  y {rows.min()}-{rows.max()}")


def classify(a, b):
    """Return (seconds_moved, seconds_measured, per-second counts)."""
    n = max(2, int(round(b - a)) + 1)
    f = frames(a, n, fps=1.0)
    counts = [blocks_changed(f[i], f[i + 1]) for i in range(len(f) - 1)]
    moved = sum(1 for c in counts if c > MOVED_BLOCKS)
    return moved, len(counts), counts


def cmd_window(a, b):
    a, b = float(a), float(b)
    moved, total, counts = classify(a, b)
    print(f"{a:8.2f}-{b:8.2f}  {b-a:6.2f}s   moved {moved}/{total}s   {counts}")


QUIET = []                             # filled from stdin: "start end" per line


def cmd_sweep():
    # Accepts "start end ..." rows and analyze deadair's "start-end ..." rows;
    # headers and anything else without two numbers up front are skipped.
    rows = []
    for l in sys.stdin.read().split("\n"):
        m = re.match(r"\s*([\d.]+)\s*[-\s]\s*([\d.]+)", l)
        if m:
            rows.append((float(m.group(1)), float(m.group(2))))
    if not rows:
        sys.exit("picture sweep: no 'start end' rows on stdin")
    print(f"{'start':>8} {'end':>8} {'len':>6}  {'moved':>7}  verdict")
    for a, b in rows:
        moved, total, counts = classify(a, b)
        frac = moved / total if total else 0
        verdict = "DEMO keep" if frac > 1 / 3 else "DEAD cut"
        # Print the WHOLE per-second list, never a head slice. The trim rule in
        # cutlist.py needs the TAIL seconds -- the ones that will actually be
        # kept -- and a 24-entry head told it nothing about a 30s window. Three
        # stretches of dead air reached the delivered file because of that.
        print(f"{a:8.2f} {b:8.2f} {b-a:6.2f}  {moved:3d}/{total:3d}  {verdict}"
              f"   {counts}")


if __name__ == "__main__":
    _cmds = sorted(k[4:] for k in globals() if k.startswith("cmd_"))
    if len(sys.argv) < 2 or f"cmd_{sys.argv[1]}" not in globals():
        sys.exit(f"usage: lc {Path(__file__).stem} <{'|'.join(_cmds)}> [args]")
    globals()[f"cmd_{sys.argv[1]}"](*sys.argv[2:])
