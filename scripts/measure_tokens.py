#!/usr/bin/env python3
"""Measure every word's ACTUALLY AUDIBLE extent and cache it.

Ledger rules 71/77 came from tokens whose logged span was tens of seconds longer
than the utterance, and both the caption builder and the cut builder handled that
with the same heuristic: assume the real speech sits at the END of the token and
pull its START forward (`MAX_WORD_S`). On this take that assumption is wrong 12
times out of 14. Scribe padded the token's END, not its start:

    «الطبقة.»   logged 284.64-287.32   audible 284.62-285.02   -> 2.30s of TAIL
    «الرئيسي.»  logged 1370.28-1372.86 audible 1370.28-1370.74 -> 2.12s of TAIL

The operator heard the first one at output 02:20: "there is a silence that shouldn't
be there because my face looks down, and it feels like I'm reading from
something." The cut had deferred to the token's end to keep the word captioned.

A heuristic that has to guess a direction is the wrong tool when the answer is
one cheap measurement. This writes `transcripts/take1.audible.json`, which both
builders load, so they agree on where every word begins and ends.

    lc measure_tokens
"""
import json
import subprocess
import re
import sys
from pathlib import Path

import numpy as np

import lcenv                       # plugin: the tools live outside the project
HERE = lcenv.edit_dir(__file__)
# Which take this run works on (see build_edl.py). A lesson recorded in two
# sittings is a normal case; every cutting tool has to be pointable at the take
# being cut, because a timestamp only means something against its own take.
#   lc measure_tokens --source take2 ...
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
HOP = 0.02
ADJUST_IF = 0.20          # only rewrite a span that is padded by more than this

words = [w for w in json.loads((HERE / "transcripts" / f"{SOURCE}.json").read_text())["words"]
         if w.get("type") == "word" and w.get("start") is not None]

raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(SRC), "-vn", "-ac", "1",
                      "-ar", "8000", "-f", "s16le", "-"], capture_output=True).stdout
a = np.frombuffer(raw, dtype=np.int16).astype(np.float64) / 32768.0
n = int(8000 * HOP)
a = a[:len(a) // n * n]
P = np.sqrt((a.reshape(-1, n) ** 2).mean(axis=1))
# A threshold derived only from the loud end of the distribution can land within
# a few dB of the room tone. On a camera take (noise floor ~0.015, p90 0.219)
# the -20dB point is 0.0219 -- 3 dB of margin -- so three isolated 20ms frames of
# room tone inside a 20.3s pause read as speech, and the token «المدير» measured
# as starting 17 SECONDS before he says it. The cut end then snapped back to that
# phantom onset and restored the whole pause. Same shape as rule 78: floor the
# threshold on the file's OWN quiet level as well, and require the energy to be
# SUSTAINED (60ms) rather than trusting a single frame.
FLOOR = float(np.percentile(P, 10))
THR = max(float(np.percentile(P, 90)) * (10 ** (-20.0 / 20)), FLOOR * 1.8)
K = 3
LONG_TOKEN_S = 1.5
BRIDGE_S = 0.30
PS = np.convolve(P, np.ones(K) / K, mode="same")

out, adjusted = [], 0
for w in words:
    s, e = float(w["start"]), float(w["end"])
    i0, i1 = int(s / HOP), min(int(e / HOP) + 1, len(P))
    seg = PS[i0:i1]
    loud = np.where(seg > THR)[0]
    if len(loud) and (e - s) > LONG_TOKEN_S:
        # A token padded across many seconds is mostly room tone, so first-to-last
        # is the wrong reduction: one stray frame anywhere in the pause stretches
        # the "audible" span across the whole hole. The utterance is ONE
        # continuous thing, so take the longest contiguous run instead (bridging
        # gaps up to BRIDGE_S, which is shorter than any real inter-word pause a
        # single token could contain). On «المدير» -- logged 220.68-240.98, spoken
        # at 240.60 -- first-to-last gave 228.12 and the cut end snapped back to
        # it, restoring 12s of the pause it was written to remove.
        runs, st = [], loud[0]
        for x, y in zip(loud, loud[1:]):
            if y - x > int(BRIDGE_S / HOP):
                runs.append((st, x))
                st = y
        runs.append((st, loud[-1]))
        a0, a1 = max(runs, key=lambda r: r[1] - r[0])
        aud_s = (i0 + a0) * HOP
        aud_e = (i0 + a1 + 1) * HOP
    elif len(loud):
        aud_s = (i0 + loud[0]) * HOP
        aud_e = (i0 + loud[-1] + 1) * HOP
    else:
        # the whole token measures silent (a held hesitation). Keep a token-sized
        # sliver at the END so it still lands in exactly one range.
        aud_s, aud_e = max(s, e - 0.10), e
    ns = aud_s if aud_s - s > ADJUST_IF else s
    ne = aud_e if e - aud_e > ADJUST_IF else e
    if ne <= ns:
        ns, ne = s, e
    if (ns, ne) != (s, e):
        adjusted += 1
    out.append({"text": w["text"], "start": round(ns, 3), "end": round(ne, 3),
                "logged_start": s, "logged_end": e})

(HERE / "transcripts" / f"{SOURCE}.audible.json").write_text(
    json.dumps(out, ensure_ascii=False))
print(f"{len(out)} words, {adjusted} spans trimmed to their audible extent "
      f"(threshold {THR:.5f}, floor {FLOOR:.5f}, {K*HOP*1000:.0f}ms sustained)")
pad_tail = sum(1 for w, o in zip(words, out) if w["end"] - o["end"] > 0.2)
pad_head = sum(1 for w, o in zip(words, out) if o["start"] - w["start"] > 0.2)
print(f"  the recogniser padded the END on {pad_tail}, the START on {pad_head}")
