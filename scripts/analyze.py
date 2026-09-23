#!/usr/bin/env python3
"""Pre-cut analysis of a take. Every pass here is one of the ledger rules.

  dump      grouped transcript with timestamps (read this to plan the cut)
  tokens    Scribe word tokens that swallow silence (rule 71/77)
  deadair   audio-driven silence sweep, per-file relative + 1s smoothed (rule 78)
  instr     editor instructions spoken into the take (rule 60)
  repeats   n-gram repeats across the raw word sequence (rule 44)
  latin     every Latin token with its timestamp (rule 74)
"""
import json
import re
import subprocess
import sys
from pathlib import Path

import numpy as np

import lcenv                       # plugin: the tools live outside the project
HERE = lcenv.edit_dir(__file__)
# Which take this run works on (see build_edl.py). A lesson recorded in two
# sittings is a normal case; every cutting tool has to be pointable at the take
# being cut, because a timestamp only means something against its own take.
#   lc analyze --source take2 ...
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
W = [w for w in json.loads((HERE / "transcripts" / f"{SOURCE}.json").read_text())["words"]
     if w.get("type") == "word" and w.get("start") is not None]

AR = r"ء-ي"


def ts(t):
    return f"{int(t)//60:02d}:{t%60:05.2f}"


def cmd_dump():
    """Group into paragraphs on gaps >= 0.8s, print with src timestamps."""
    chunk = []
    for i, w in enumerate(W):
        chunk.append(w)
        nxt = W[i + 1] if i + 1 < len(W) else None
        gap = (nxt["start"] - w["end"]) if nxt else 99.0
        if gap >= 0.8 or len(" ".join(x["text"] for x in chunk)) > 220:
            a, b = chunk[0]["start"], chunk[-1]["end"]
            txt = " ".join(x["text"].strip() for x in chunk)
            print(f"[{a:8.2f}-{b:8.2f}] ({gap:5.2f}) {txt}")
            chunk = []
    if chunk:
        a, b = chunk[0]["start"], chunk[-1]["end"]
        print(f"[{a:8.2f}-{b:8.2f}] (  end) {' '.join(x['text'].strip() for x in chunk)}")


def cmd_tokens(thr=1.5):
    print(f"word tokens longer than {thr}s (silence swallowed inside a token):")
    for w in W:
        d = w["end"] - w["start"]
        if d >= thr:
            print(f"  {w['start']:8.2f}-{w['end']:8.2f}  {d:6.2f}s  «{w['text']}»")


def rms_profile(hop=0.05):
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(SRC), "-vn", "-ac", "1", "-ar", "8000",
         "-f", "s16le", "-"], capture_output=True).stdout
    a = np.frombuffer(raw, dtype=np.int16).astype(np.float64) / 32768.0
    n = int(8000 * hop)
    a = a[:len(a) // n * n]
    return np.sqrt((a.reshape(-1, n) ** 2).mean(axis=1)), hop


def cmd_deadair(minlen=2.0):
    """Rule 78: threshold from the file's OWN 90th-percentile level, and smooth
    with a 1s moving average before extracting runs -- raw 50ms frames fragment
    one long hole into many unremarkable short ones."""
    p, hop = rms_profile()
    thr = float(np.percentile(p, 90)) * (10 ** (-20.0 / 20))
    k = int(round(1.0 / hop))
    sm = np.convolve(p, np.ones(k) / k, mode="same")
    quiet = sm < thr
    runs, i = [], 0
    while i < len(quiet):
        if quiet[i]:
            j = i
            while j < len(quiet) and quiet[j]:
                j += 1
            runs.append([i * hop, j * hop])
            i = j
        else:
            i += 1
    merged = []                                    # bridge gaps < 0.6s
    for r in runs:
        if merged and r[0] - merged[-1][1] < 0.6:
            merged[-1][1] = r[1]
        else:
            merged.append(r)
    print(f"threshold {thr:.5f} (p90={np.percentile(p,90):.4f})  "
          f"quiet runs >= {minlen}s:")
    tot = 0.0
    for a, b in merged:
        if b - a >= minlen:
            tot += b - a
            print(f"  {a:8.2f}-{b:8.2f}  {b-a:6.2f}s")
    print(f"  total {tot:.1f}s in quiet runs >= {minlen}s")


def cmd_instr():
    """Rule 60: he sometimes talks to the editor mid-take."""
    pat = re.compile(r"(احذف|امسح|اقطع|شيل|احذفي|امسحي|delete|cut|remove|عفو)")
    for i, w in enumerate(W):
        if pat.search(w["text"]):
            ctx = " ".join(x["text"] for x in W[max(0, i - 12):i + 14])
            print(f"  {w['start']:8.2f}  «{w['text']}»  ...{ctx}...")


def norm(s):
    s = re.sub(r"[ً-ْـ]", "", s)
    s = s.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا").replace("ى", "ي").replace("ة", "ه")
    # NOTE (2026-08-29, rule 126 -- third and fourth occurrence): the class was
    # `[^\w\u0600-\u06FF]`, meant to read "keep word characters and Arabic".
    # Python 3's `\w` already matches Arabic letters, so the extra range added
    # nothing EXCEPT re-admitting the Arabic punctuation inside it: the comma
    # U+060C, the semicolon U+061B and the question mark U+061F. ASCII
    # punctuation was stripped, Arabic punctuation was not.
    #
    # Fixed in qc.py and post_cut_check.py on 2026-08-28, and NOT here, in the
    # two siblings holding the identical function. Rule 130 for the third time:
    # a fix applied to the instance that surfaced it, neighbours never checked.
    # Audited 2026-08-29 across every norm() in the toolchain; the script checker
    # (a tool that does not ship here) has the same class but strips AR_PUNC
    # first, so it was already safe.
    #
    # analyze.py is the repeat scanner used to AUTHOR the cut list, so this copy
    # of the bug was hiding repeats before a single cut was written.
    # build_captions.py uses norm() for NO_SPLIT matching and for the
    # caption/overlay dedup (rules 13 and 21), so a phrase followed by an Arabic
    # comma silently failed to match either.
    return re.sub(r"[^\w]", "", s).casefold()


def cmd_repeats(n=4, window=70):
    """Rule 44: an n-gram recurring within `window` words is a candidate retake."""
    n, window = int(n), int(window)   # argv arrives as float; range() will not take it
    toks = [norm(w["text"]) for w in W]
    seen = {}
    for i in range(len(toks) - n):
        g = tuple(toks[i:i + n])
        if not all(g):
            continue
        if g in seen and i - seen[g] <= window:
            print(f"  {W[seen[g]]['start']:8.2f} -> {W[i]['start']:8.2f}  "
                  f"({i - seen[g]:3d} words)  «{' '.join(W[j]['text'] for j in range(i, i+n))}»")
        seen[g] = i


def cmd_latin():
    """Rule 74: every Latin token must be checked against the SCREEN."""
    seen = {}
    for w in W:
        for m in re.findall(r"[A-Za-z][A-Za-z0-9._-]*", w["text"]):
            seen.setdefault(m, []).append(w["start"])
    for k in sorted(seen, key=lambda x: -len(seen[x])):
        t = seen[k]
        print(f"  {len(t):3d}x  {k:<22} first {t[0]:8.2f}  "
              f"{' '.join(f'{x:.1f}' for x in t[:8])}")


if __name__ == "__main__":
    _cmds = sorted(k[4:] for k in globals() if k.startswith("cmd_"))
    if len(sys.argv) < 2 or f"cmd_{sys.argv[1]}" not in globals():
        sys.exit(f"usage: lc {Path(__file__).stem} <{'|'.join(_cmds)}> [args]")
    globals()[f"cmd_{sys.argv[1]}"](*[float(x) for x in sys.argv[2:]])
