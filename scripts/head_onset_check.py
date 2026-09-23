#!/usr/bin/env python3
"""Rule 153: verify the HEAD and TAIL cuts do not clip the words they keep.

Every interior cut in this kit is validated against audio energy (rule 71) and
snapped out of words (rule 79). The head and tail are the two edges that never
were, because `build_edl.py`'s post-conditions cannot see the defect: a head cut
drops no word it did not declare and straddles no boundary. The word it damages
is the one it KEEPS.

One video's head was authored at the Scribe token start for the first word
(1.46s). The audible onset was at 1.35s, so the delivered file opened with its
first 20ms already at -9.4 dBFS against a -3.0 dBFS speech level: the cut was
inside the word.

Test: read the first 20ms after the head cut and the last 20ms before the tail
cut. If either sits within MARGIN_DB of the take's own speech level, the cut is
inside a word.

    lc head_onset_check <edit_dir>     # exit 1 if either edge clips
"""
import json, subprocess, sys
from pathlib import Path
import numpy as np

# Calibrated against the real defect and four clean lessons, and the first
# value (6.0) FAILED its own self-test: that video's clipped head opened at
# -9.4 dB against -2.7 dB speech, which is 6.7 dB down, so a 6 dB margin passed
# the very cut the check exists to catch.
#   defect  : head opens  6.7 dB below speech
#   cleanest: tail closes 23.9 dB below speech (one of the clean lessons)
# 15 dB sits between them with room on both sides.
MARGIN_DB = 15.0     # within this of speech level == still inside the word
SR, FRAME = 16000, 0.02

# The speech reference MUST come from the whole take, not from the 1.2s window at
# the edge. First version of this check derived it from the window's own p90, so
# a tail sitting in pure silence reported "-76.3 dB against a -76.3 dB speech
# level" and failed two clean lessons: with no speech in the window, room tone
# IS the p90. A window whose reference is quiet proves the edge is in silence,
# which is the passing case, not the failing one.

def speech_level(src, ranges):
    """p95 of 20ms frame peaks sampled across the KEPT content of the take."""
    picks, span = [], 0.0
    for r in ranges:                       # sample up to 60s spread over the cut
        if span >= 60.0: break
        take = min(3.0, r["end"] - r["start"])
        if take < 0.5: continue
        picks.append((r["start"], take)); span += take
    lv = []
    for t0, dur in picks:
        f = frames(src, t0, dur)
        if len(f): lv.append(f)
    if not lv: return None
    return float(np.percentile(np.concatenate(lv), 95))


def frames(src, t0, dur):
    p = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", f"{max(0.0,t0):.3f}", "-i", src,
         "-t", f"{dur:.3f}", "-ac", "1", "-ar", str(SR), "-f", "s16le", "-"],
        capture_output=True)
    a = np.frombuffer(p.stdout, dtype=np.int16).astype(np.float32) / 32768
    n = int(FRAME * SR)
    if len(a) < n: return np.array([])
    return np.array([20*np.log10(np.abs(a[i:i+n]).max()+1e-9)
                     for i in range(0, len(a)-n, n)])

def main(edit_dir):
    d = Path(edit_dir).resolve()
    edl = json.loads((d / "edl.json").read_text())
    src = list(edl["sources"].values())[0]
    r_first, r_last = edl["ranges"][0], edl["ranges"][-1]
    fails = []

    speech = speech_level(src, edl["ranges"])
    if speech is None:
        print("   could not establish a speech reference"); return 1
    print(f"  take speech level: {speech:.1f} dBFS")

    head = frames(src, r_first["start"], 1.2)
    if len(head):
        if head[0] > speech - MARGIN_DB:
            fails.append(f"HEAD cut at {r_first['start']:.2f}s opens at "
                         f"{head[0]:.1f} dB against a {speech:.1f} dB speech level "
                         f"-- it is inside the first word")
        else:
            rise = np.where(head > speech - MARGIN_DB)[0]
            ms = rise[0]*20 if len(rise) else -1
            rise = (f"rises over {ms}ms" if ms >= 0 else
                    "then more than 1.2s of quiet before speech; consider a head cut")
            print(f"  head OK: opens at {head[0]:.1f} dB, speech {speech:.1f} dB, {rise}")

    tail = frames(src, r_last["end"] - 1.2, 1.2)
    if len(tail):
        if tail[-1] > speech - MARGIN_DB:
            fails.append(f"TAIL cut at {r_last['end']:.2f}s closes at "
                         f"{tail[-1]:.1f} dB against a {speech:.1f} dB speech level "
                         f"-- it is inside the last word")
        else:
            print(f"  tail OK: closes at {tail[-1]:.1f} dB, speech {speech:.1f} dB")

    for f in fails:
        print(f"   {f}")
    return 1 if fails else 0

if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "."))
