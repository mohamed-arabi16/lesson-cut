#!/usr/bin/env python3
"""Trim EVERY wordless gap in the delivered cut, not just the long ones.

The operator, on one lesson: *"00:06:00 to 00:07:50 shows a lot of
silence. I think you need to be tighter on the cuts. If you check the frame, it
shows me looking at the script, which is not good. When I speak, I don't look at
the script normally, but when I pause for like one second, you should cut that if
it's silent and I'm looking at the screen for the script."*

He is right, and the reason it was invisible is that **every dead-air pass in
this kit only ever looked at gaps of 2.0 seconds or more**: the pause trimmer
then in use (not shipped here) built its windows from `silencedetect ... d=2.0`,
`qc.py` fails at the same floor, and `gapcheck.py`'s ceiling defaulted to 2.5.
Measured on two lessons, at `d=0.6`:

    lesson A   123 silent runs, 12.4% of the runtime   (101 of them UNDER 2.0s)
    lesson B    85 silent runs, 22.0% of the runtime   ( 78 of them UNDER 2.0s)

So four fifths of the dead air sat below every threshold in the pipeline. A
one-second pause where he is reading the next line off the script is exactly the
thing the viewer feels and no check was looking at it.

This works from the transcript, on the DELIVERED timeline, and trims every gap:

  * gap >= SHORT_CEILING  ->  keep SHORT_TARGET, taken from the MIDDLE
  * gap >= LONG_CEILING   ->  keep LONG_TARGET, taken from the BUSIEST slice
    (a model run is worth watching; a pause before a sentence is not)

Both bounds are word boundaries, so no cut can land inside a word.

    lc tighten_gaps [short_ceiling] [short_target] [long_ceiling] [long_target]
    lc tighten_gaps                 # 0.75 / 0.40 / 4.0 / 1.20
"""
import ast
import json
import math
import re
import sys
from pathlib import Path

import numpy as np

import picture
from cutlist import SPEECH_CUTS

# Source spans that must survive intact. A lesson with a blurred region has its
# mask built from a source window, and a mask builder cannot emit an overlay for
# a window a cut has split. More generally: a beat where the point
# IS the silence (a paste, a keystroke, a deliberate hold) should not be
# tightened. Put those spans in `protect.py` as PROTECT = [(start, end), ...].
try:
    from protect import PROTECT
except ImportError:
    PROTECT = []

import lcenv                       # plugin: the tools live outside the project
HERE = lcenv.edit_dir(__file__)

# This regenerates pause_cuts.py from the CURRENT edl.json. If that EDL was
# built with pause cuts already in it, the gaps are gone, the regenerated list
# comes out EMPTY, and the next build_edl restores every second of dead air.
# Following this file's own old "Regenerate" recipe did exactly that.
_pc = HERE / "pause_cuts.py"
if _pc.exists() and re.search(r"^\s*\(\s*[\d.]+\s*,", _pc.read_text(), re.M):
    sys.exit("pause_cuts.py is not empty, so edl.json already has the gaps trimmed and this would "
             "regenerate an EMPTY list.\n  Use `lc rebuild`, which empties it, rebuilds, "
             "tightens and rebuilds again.")
OUT_FPS = 30
SHORT_CEILING = float(sys.argv[1]) if len(sys.argv) > 1 else 0.75
SHORT_TARGET = float(sys.argv[2]) if len(sys.argv) > 2 else 0.40
LONG_CEILING = float(sys.argv[3]) if len(sys.argv) > 3 else 4.00
LONG_TARGET = float(sys.argv[4]) if len(sys.argv) > 4 else 1.20
EDGE = 0.06          # never place a boundary exactly on a word
MIN_CUT = 0.20       # build_edl skips anything under 0.15 after snapping


# ---------------------------------------------------------------------------
# Rule 151. Do not trust the measured word extents at the boundary: LISTEN.
#
# `measure_tokens.py` picks the audible run inside a Scribe token, and on one
# lesson it picked the WRONG one. «إذا» is logged 118.380-122.440 and it recorded
# 118.380-119.560, but the actual utterance is at 122.30-122.44 (measured: -20 dB
# there, against -80 dB at 119.6). So a cut authored at 122.400 sat squarely on
# the word. `build_edl`'s clear_audible_window() could not save it either, because
# that function only ever pushes an edge FORWARD and this edge was already past
# the extent it believed in. Two instruments agreeing on a wrong number.
#
# The cure is not a better estimator, it is a second opinion from the audio
# itself. Every boundary this tool emits is checked against the real RMS and
# nudged into silence; a cut with no quiet boundary is dropped rather than made.
HOP = 0.02
# Rule 153: use THE GATE'S OWN floor, with headroom. qc.py does not use a fixed
# dBFS number, it takes this source's 90th-percentile 50ms frame level minus
# 20 dB. A fixed -45 happened to land within 0.3 dB of it on one lesson, and a
# boundary measured -44.4: my generator called it quiet, the gate called it
# audible, and one clipped word survived a whole render. Same instrument, plus
# margin, so a boundary the generator accepts is one the gate cannot argue with.
SILENCE_MARGIN_DB = 6.0
_FLOOR = {}
_FLOOR_PARTS = {}
# How far above the source's own noise floor a boundary must sit to count as
# quiet. is_quiet() tests the MAX frame level in the window, not the mean, so
# the margin has to clear room tone's PEAKS, not its average. Measured on a
# camera take: room tone averages -33.9 dBFS but peaks at -29.5, and speech
# sits at -16. p20+10dB lands at -27.7, which is 1.8 dB clear of the peaks and
# 11 dB below speech. p20+6 landed at -33.1 and still failed every boundary.
NOISE_MARGIN_DB = 10.0


def speech_floor(src):
    """qc.py's own floor for this source: p90 of 50ms frames, minus 20 dB."""
    if src in _FLOOR:
        return _FLOOR[src]
    import subprocess
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(src), "-vn", "-ac", "1", "-ar", "8000",
         "-f", "s16le", "-"], capture_output=True).stdout
    a = np.frombuffer(raw, dtype=np.int16).astype(np.float64) / 32768.0
    n = 400
    a = a[:len(a) // n * n]
    if len(a) == 0:
        _FLOOR[src] = 0.006
    else:
        lv = np.sqrt((a.reshape(-1, n) ** 2).mean(axis=1))
        # p90 - 20dB is qc.py's floor, and it assumes the quiet parts of the
        # source are near digital silence. That holds for a screen recording and
        # is FALSE for a camera in a live room: on a camera take the
        # room tone sits at -33.9 dBFS against speech at -14, so p90-26 landed at
        # -36.3, BELOW the room tone, and every one of the 72 candidate cuts was
        # dropped as "no quiet boundary". Same shape as rule 150: a constant
        # calibrated on one kind of source, silently wrong on another.
        #
        # So the floor is now the LOUDER of two source-derived numbers: qc.py's,
        # and the source's own noise floor (p10) plus a margin. On a screen
        # recording p10 is far below, the max() picks qc.py's number and nothing
        # changes; on a camera source it lifts the floor above the room tone.
        relative = float(np.percentile(lv, 90)) * (10 ** (-20.0 / 20))
        noise = float(np.percentile(lv, 20)) * (10 ** (NOISE_MARGIN_DB / 20))
        _FLOOR[src] = max(relative, noise)
        _FLOOR_PARTS[src] = (relative, noise)
    return _FLOOR[src]


SILENCE_RMS = None   # set per source in main(), from speech_floor() minus the margin
_PROFILE = {}


def rms_profile(src):
    """RMS every 20ms across the whole source, cached."""
    if src in _PROFILE:
        return _PROFILE[src]
    import subprocess
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(src), "-vn", "-ac", "1", "-ar", "16000",
         "-f", "s16le", "-"], capture_output=True).stdout
    a = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    n = int(HOP * 16000)
    frames = len(a) // n
    prof = np.sqrt((a[:frames * n].reshape(frames, n) ** 2).mean(axis=1) + 1e-12)
    _PROFILE[src] = prof
    return prof


def is_quiet(prof, t, half=0.06):
    """Is the audio quiet across +/- `half` seconds of t? qc.py asks it this way."""
    lo = max(0, int((t - half) / HOP))
    hi = min(len(prof), int((t + half) / HOP) + 1)
    if hi <= lo:
        return False
    # MAX, not mean. qc.py averages over its window, and an average hides a loud
    # tail: the boundary this caught on one lesson measured -34.6 dB as a mean
    # and -19.7 dB at its loudest frame, 40ms before «إذا» is actually spoken.
    # A boundary is safe only if NO frame under it is loud.
    return float(prof[lo:hi].max()) < SILENCE_RMS


def nudge(prof, t, lo, hi):
    """Move t to the nearest quiet point inside [lo,hi]; None if there is none."""
    if is_quiet(prof, t):
        return t
    step = HOP
    for k in range(1, int((hi - lo) / step) + 1):
        for cand in (t - k * step, t + k * step):
            if lo <= cand <= hi and is_quiet(prof, cand):
                return round(cand, 3)
    return None


def quantised(d):
    return math.ceil(round(d * OUT_FPS, 6)) / OUT_FPS


SPEECH_ABOVE_FLOOR_DB = 6.0   # "speech-level": this far above the speech floor
SPEECH_WINDOW_S = 0.50        # within any half second...
SPEECH_DENSE_S = 0.20         # ...at least this much of it at speech level


RING_S = 0.80                 # a word's sound can ring this long past its measured end


def unaccounted_mask(prof_len, words, kept_spans):
    """Frames NOT explained by any transcript word.

    A REMOVED word (a filler the cut takes out) rings well past its measured end
    (0.6-0.8s measured on a real lesson), and trimming that ring is exactly what
    the cut is for, so sound up to RING_S after a removed word is that word's.
    A KEPT word gets only a short pad: its audible end was already measured, and
    giving it the ring made the check blind to a missed word said right after it.
    """
    kept = {(round(a, 3), round(b, 3)) for a, b in kept_spans}
    free = np.ones(prof_len, dtype=bool)
    for w in words:
        is_kept = (round(w["start"], 3), round(w["end"], 3)) in kept
        tail = 0.10 if is_kept else RING_S
        a = max(0, int((w["start"] - 0.10) / HOP))
        b = min(prof_len, int((max(w["end"], w.get("logged_end", w["end"])) + tail) / HOP) + 1)
        free[a:b] = False
    return free


def holds_speech(prof, lo, hi, level, free=None):
    """Does [lo, hi] contain speech-level audio?

    A "wordless gap" is only wordless according to the transcript. When the
    recogniser missed words (routine with local whisper on mixed-language
    speech, and it happens with any recogniser), the gap between two logged
    words can hold real speech, and trimming it deleted that speech with no
    check able to see it afterwards, because every check reads the transcript.
    So the interior of every cut is measured, not just its edges, counting only
    sound no transcript word accounts for (see unaccounted_mask).

    Density, not a continuous run: a short word is two syllables with a dip
    between them (measured: 0.20s loud, 40ms quiet, 0.10s loud), so no single
    run reaches even 0.3s. A keyboard or mouse click is one or two 20ms frames,
    far under 0.2s in any half second.
    """
    i0, i1 = max(0, int(lo / HOP)), min(len(prof), int(hi / HOP))
    if i1 <= i0:
        return False
    loud = prof[i0:i1] > level
    if free is not None:
        loud = loud & free[i0:i1]
    loud = loud.astype(int)
    w = max(1, int(round(SPEECH_WINDOW_S / HOP)))
    need = int(round(SPEECH_DENSE_S / HOP))
    if len(loud) <= w:
        return int(loud.sum()) >= need
    csum = np.concatenate([[0], np.cumsum(loud)])
    return bool((csum[w:] - csum[:-w]).max() >= need)


def busiest(a, b, target):
    """Where in [a,b] is the screen doing the most? Long waits only."""
    n = max(2, int(round(b - a)) + 1)
    f = picture.frames(a, n, fps=1.0)
    counts = [picture.blocks_changed(f[i], f[i + 1]) for i in range(len(f) - 1)]
    k = max(1, int(round(target)))
    if len(counts) <= k:
        return a
    sums = [sum(counts[i:i + k]) for i in range(len(counts) - k + 1)]
    return a + int(np.argmax(sums))


def main():
    edl = json.loads((HERE / "edl.json").read_text())
    words = {n: json.loads((HERE / "transcripts" / f"{n}.audible.json").read_text())
             for n in edl["sources"]}

    # Kept words AND the kept source intervals, in delivery order.
    kept_words, kept_iv = [], []
    for r in edl["ranges"]:
        kept_iv.append((r["start"], r["end"]))
        for w in words[r["source"]]:
            if r["start"] <= w["start"] and w["end"] <= r["end"]:
                kept_words.append((w["start"], w["end"]))
    kept_words.sort(); kept_iv.sort()

    def kept_between(a, b):
        """The source intervals still in the cut between two kept words.

        A gap can SPAN A JOIN: half of it is the tail of one range and half the
        head of the next, with a cut in between. Measuring `b - a` in source
        seconds would then report a gap that is not what the viewer hears, and
        would emit a cut across material that is already gone. The delivered gap
        is the sum of what survives.
        """
        out = []
        for x, y in kept_iv:
            lo, hi = max(x, a), min(y, b)
            if hi - lo > 0.001:
                out.append([lo, hi])
        return out

    srcpath = Path(edl['sources'][edl['ranges'][0]['source']])
    prof = rms_profile(srcpath)
    global SILENCE_RMS
    SILENCE_RMS = speech_floor(srcpath) * (10 ** (-SILENCE_MARGIN_DB / 20))
    rel, noi = _FLOOR_PARTS.get(srcpath, (None, None))
    if rel is not None:
        which = "room-tone" if noi >= rel else "qc-relative"
        print(f"  silence floor: {20 * np.log10(SILENCE_RMS):.1f} dBFS "
              f"[{which}]  (qc-relative {20*np.log10(rel):.1f}, "
              f"room-tone+{NOISE_MARGIN_DB:.0f}dB {20*np.log10(noi):.1f})")
    else:
        print(f"  silence floor: {20 * np.log10(SILENCE_RMS):.1f} dBFS")
    cuts, dropped, short_n, long_n, whole_n = [], [], 0, 0, 0
    held = []          # cuts NOT made because the gap holds speech no word covers
    SPEECH_LEVEL = speech_floor(srcpath) * (10 ** (SPEECH_ABOVE_FLOOR_DB / 20))
    FREE = unaccounted_mask(len(prof), words[edl["ranges"][0]["source"]], kept_words)
    for i in range(len(kept_words) - 1):
        a, b = kept_words[i][1], kept_words[i + 1][0]
        iv = kept_between(a, b)
        delivered = sum(y - x for x, y in iv)
        if delivered < SHORT_CEILING or not iv:
            continue
        if any(a < pe and ps < b for ps, pe in PROTECT):
            continue
        if delivered >= LONG_CEILING:
            target, tag = LONG_TARGET, f"{delivered:.1f}s wait"
            long_n += 1
            # Keep the busiest slice of the LARGEST surviving interval.
            big = max(iv, key=lambda p: p[1] - p[0])
            ka = busiest(big[0], big[1], target) if big[1] - big[0] > target else big[0]
            keep = [(ka, min(big[1], ka + target))]
        else:
            target, tag = SHORT_TARGET, f"{delivered:.2f}s wordless"
            short_n += 1
            # Keep the target from the MIDDLE of the largest surviving interval.
            big = max(iv, key=lambda p: p[1] - p[0])
            mid = (big[0] + big[1]) / 2.0
            ka = max(big[0], mid - target / 2)
            keep = [(ka, min(big[1], ka + target))]

        _made = len(cuts) + len(dropped) + len(held)
        for x, y in iv:
            sub = [(x, y)]
            for ka, kb in keep:
                nxt = []
                for lo, hi in sub:
                    if not (lo < kb and ka < hi):
                        nxt.append((lo, hi)); continue
                    if lo < ka: nxt.append((lo, min(hi, ka)))
                    if hi > kb: nxt.append((max(lo, kb), hi))
                sub = nxt
            for lo, hi in sub:
                lo = lo + EDGE if abs(lo - a) < 0.001 else lo
                hi = hi - EDGE if abs(hi - b) < 0.001 else hi
                if hi - lo < MIN_CUT:
                    continue
                # Rule 151: both edges must sit in real silence, not in a silence
                # the extents merely believe in.
                nlo = nudge(prof, lo, a, b)
                nhi = nudge(prof, hi, a, b)
                if nlo is None or nhi is None or nhi - nlo < MIN_CUT:
                    dropped.append((round(lo, 2), round(hi, 2)))
                    continue
                if holds_speech(prof, nlo, nhi, SPEECH_LEVEL, FREE):
                    held.append((round(nlo, 2), round(nhi, 2)))
                    continue
                cuts.append((round(nlo, 2), round(nhi, 2),
                             f"rule 150: {tag}, trimmed to {target}s", 0.0, False, False))
        if len(cuts) + len(dropped) + len(held) == _made:
            # Each side piece must be at least MIN_CUT after keeping EDGE beside
            # the word, so a gap shorter than about target + 2*EDGE + 2*MIN_CUT
            # has nothing safe to remove. It stays whole; say so.
            whole_n += 1

    # Subtract SPEECH_CUTS so the two lists never declare the same second twice.
    out = []
    for a, b, why, kt, rs, re_ in cuts:
        seg = [(a, b)]
        for sa, sb, *_ in SPEECH_CUTS:
            nxt = []
            for x, y in seg:
                if not (x < sb and sa < y):
                    nxt.append((x, y)); continue
                if x < sa: nxt.append((x, min(y, sa)))
                if y > sb: nxt.append((max(x, sb), y))
            seg = nxt
        for x, y in seg:
            if y - x >= MIN_CUT:
                out.append((round(x, 2), round(y, 2), why, kt, rs, re_))
    out.sort()
    merged = []
    for c in out:
        if merged and c[0] <= merged[-1][1] + 0.001:
            merged[-1] = (merged[-1][0], max(merged[-1][1], c[1]), merged[-1][2],
                          merged[-1][3], merged[-1][4], merged[-1][5])
        else:
            merged.append(c)

    p = HERE / "pause_cuts.py"
    p.write_text(
        "# generated by tighten_gaps.py: EVERY wordless gap on the\n"
        "# DELIVERED timeline is trimmed, not just the ones over 2 seconds, and the\n"
        "# gap is measured across joins rather than in raw source seconds.\n"
        f"# short bar {SHORT_CEILING}s -> {SHORT_TARGET}s; waits over {LONG_CEILING}s keep\n"
        f"# {LONG_TARGET}s of their busiest picture. Regenerate with `lc rebuild`,\n"
        "# which empties this file first. Running tighten_gaps over an EDL that\n"
        "# already contains these cuts would write an empty list.\n"
        "PAUSE_CUTS = [\n"
        + "".join(f"    ({a:8.2f}, {b:8.2f}, {why!r}, {kt}, {rs}, {re_}),\n"
                 for a, b, why, kt, rs, re_ in merged)
        + "]\n")
    print(f"{short_n} short gap(s) + {long_n} long wait(s) -> {len(merged)} cuts, "
          f"{sum(b - a for a, b, *_ in merged):.1f}s removed")
    if held:
        print(f"  {len(held)} cut(s) NOT made: the gap holds speech-level audio with no word "
              f"under it (a word the transcript missed, or a murmur). Listen, then cut it "
              f"deliberately or leave it. See `lc untranscribed`. First few: {held[:4]}")
    if whole_n:
        print(f"  {whole_n} gap(s) kept whole: too short to trim safely "
              f"(under about {SHORT_TARGET + 2 * EDGE + 2 * MIN_CUT:.2f}s)")
    if dropped:
        print(f"  {len(dropped)} cut(s) DROPPED: no quiet boundary in the gap. "
              f"First few: {dropped[:4]}")


if __name__ == "__main__":
    main()
