#!/usr/bin/env python3
"""Word-level transcript lookup in a source-time window.

Readers need this because the utterance dump groups words, and a cut edge is decided between two
specific words. Columns: Scribe's logged span, the MEASURED audible span (rules 86/102, the one
every builder trusts), the gap before the word, and the text.

  lc words <from_s> <to_s> [edit_dir]

edit_dir defaults to $EDIT_DIR, then to the current directory.
"""
import json
import os
import sys
from pathlib import Path

lo, hi = float(sys.argv[1]), float(sys.argv[2])
import lcenv
edit = (Path(sys.argv[3]).resolve() if len(sys.argv) > 3
        else lcenv.edit_dir(__file__))

raw = [w for w in json.loads((edit / "transcripts/take1.json").read_text())["words"]
       if w.get("type") == "word" and w.get("start") is not None]
aud_path = edit / "transcripts/take1.audible.json"
aud = json.loads(aud_path.read_text()) if aud_path.exists() else None

prev_end = None
for i, w in enumerate(raw):
    a = aud[i] if aud and i < len(aud) else None
    s = a["start"] if a else w["start"]
    e = a["end"] if a else w["end"]
    if w["end"] < lo or w["start"] > hi:
        prev_end = e
        continue
    gap = "" if prev_end is None else f"{s - prev_end:5.2f}"
    print(f"{w['start']:8.2f} {w['end']:8.2f} | {s:8.2f} {e:8.2f} | {gap:>5} | {w['text']}")
    prev_end = e
