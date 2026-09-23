#!/usr/bin/env python3
"""Post-cut sweep on the KEPT word sequence. Exits non-zero on anything found.

Rule 99 says to sweep the delivered sequence before rendering, and on one lesson
that sweep caught defects the gate would otherwise have. On another it was
skipped, the render ran for over an hour, and the gate then failed on five
truncated words and three real repeats -- every one of which this would have
found in two seconds, before the render rather than after it.

So it is a script now, not a habit. Run it after build_edl and BEFORE render.

    lc post_cut_check          (no arguments; exits 1 on any finding)
"""
import json
import re
import sys
from pathlib import Path

import lcenv                       # plugin: the tools live outside the project
HERE = lcenv.edit_dir(__file__)
# No arguments: the n-gram windows below mirror qc.py's so the two agree.

edl = json.loads((HERE / "edl.json").read_text())
tr = HERE / "transcripts"

# ONE TRANSCRIPT PER SOURCE, and the kept sequence assembled RANGE BY RANGE in
# delivery order. This file used to take `sources.values()[0]` and test every
# range against that single transcript. On a single-take lesson that is correct
# and invisible; on a STITCHED one it silently reads take 2's ranges against take
# 1's words, and since the two takes' timestamps overlap it returns a full page of
# confident findings that are all artefacts. Caught on a stitched lesson because
# every "repeat" it reported was a span already cut out of take 1.
#
# Assembling in delivery order also fixes a second thing: the n-gram window now
# spans a take boundary the way the viewer experiences it, so a phrase repeated
# either side of the stitch is visible to the scan.
WORDS = {}
for key, srcpath in edl["sources"].items():
    stem = Path(srcpath).stem
    aud = tr / f"{stem}.audible.json"
    raw = tr / f"{stem}.json"
    if aud.exists():
        WORDS[key] = json.loads(aud.read_text())
    elif raw.exists():
        WORDS[key] = [w for w in json.loads(raw.read_text())["words"]
                      if w.get("type") == "word" and w.get("start") is not None]
    else:
        sys.exit(f"no transcript for source {key!r}")

kept, W = [], []
for r in edl["ranges"]:
    ws = WORDS[r["source"]]
    W.extend(ws) if r is edl["ranges"][0] and len(WORDS) == 1 else None
    kept.extend(w for w in ws if r["start"] < w["end"] <= r["end"])
W = [w for v in WORDS.values() for w in v]
R = [(r["start"], r["end"]) for r in edl["ranges"]]

accept = HERE / "qc-accept.json"
def _load_accepts(p):
    if not p.exists():
        return set()
    try:
        data = json.loads(p.read_text())
    except json.JSONDecodeError as e:
        sys.exit(f"qc-accept.json is not valid JSON: {e}")
    if not isinstance(data, list):
        sys.exit('qc-accept.json must be a JSON array: [{"phrase": "...", "reason": "..."}]')
    for a in data:
        if not isinstance(a, dict) or not str(a.get("phrase", "")).strip() \
                or not str(a.get("reason", "")).strip():
            sys.exit(f'every qc-accept.json entry needs "phrase" and a written "reason": {a}')
    return {re.sub(r"\s+", " ", a["phrase"]).strip() for a in data}


accepted = _load_accepts(accept)


def norm(s):
    s = re.sub(r"[ً-ْـ]", "", s)
    s = (s.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
          .replace("ى", "ي").replace("ة", "ه"))
    # NOTE (2026-08-28, rule 126): the character class used to be
    # `[^\w\u0600-\u06FF]`, which was meant to read "keep word characters and
    # Arabic". Python 3's `\w` is already Unicode-aware and matches Arabic
    # letters, so the extra range added nothing EXCEPT re-admitting the Arabic
    # punctuation that lives inside it: the comma U+060C, the semicolon U+061B
    # and the question mark U+061F. ASCII punctuation was stripped, Arabic
    # punctuation was not, so «ملخص،» never compared equal to «ملخص» and every
    # repeat check silently skipped any pair Scribe had punctuated differently.
    return re.sub(r"[^\w]", "", s).casefold()


fails = []
print(f"kept {len(kept)} of {len(W)} words across {len(R)} ranges")

# Truncated tokens get the same written-accept path as the other checks. Some
# cannot be cut: a 30ms hesitation with ZERO gap to the next word collapses the
# cut below the snapper's minimum, and `build_edl.py` correctly refuses to place
# an edge inside a word. Those reach the delivered file as a sub-100ms sound and
# are already dropped from the CAPTIONS by clean()'s _dedash, which is what
# rule 48 is actually about. The accept must name the token, and the reason has
# to say why no cut exists -- never "it is small".
trunc = [w for w in kept if "--" in w["text"] or w["text"].strip().endswith("-")]
for w in trunc:
    if w["text"].strip() in accepted:
        continue
    fails.append(f"truncated «{w['text']}» survives at src {w['start']:.2f}")

# Adjacent duplicates get the SAME written-accept path the n-gram check has,
# for the same reason and to the same standard. Without one this sweep was
# stricter than the gate it exists to predict: `qc.py` already matches its
# accepts against the repeated run, so an idiomatic «كذا كذا كذا» passed the
# gate and failed here, which is rule 110's disagreement in the other
# direction. The accept is still a written, dated judgement in
# `qc-accept.json`, never a loosened detector -- and it must name the pair
# («كذا كذا»), so accepting one idiom does not silently accept every doubled
# word in the lesson.
for i in range(len(kept) - 1):
    if norm(kept[i]["text"]) == norm(kept[i + 1]["text"]) and len(norm(kept[i]["text"])) > 2:
        pair = re.sub(r"\s+", " ", f"{kept[i]['text']} {kept[i + 1]['text']}").strip()
        if pair not in accepted:
            fails.append(f"adjacent identical «{kept[i]['text']}» at src {kept[i]['start']:.2f}")

# TWO-WORD RESTART. The operator heard a two-word phrase said twice
# in a row («هون شرح، هون شرح لك الفكرة» is the shape) in a SHIPPED file. Neither test above sees it: the
# adjacent-duplicate check needs one identical word, and the n-gram scan below
# starts at THREE. A repeated TWO-word phrase falls exactly between them, and it
# is the single commonest shape of an abandoned restart in these takes.
#
# Deliberately narrow: only an IMMEDIATE restart, seq[i:i+2] == seq[i+2:i+4],
# with nothing in between. A 2-gram recurring later in a sentence is ordinary
# Arabic and is NOT flagged, which is why this does not need the n-gram scan's
# distance window.
for i in range(len(kept) - 3):
    a = (norm(kept[i]["text"]), norm(kept[i + 1]["text"]))
    b = (norm(kept[i + 2]["text"]), norm(kept[i + 3]["text"]))
    if "" in a or a != b or len(a[0]) + len(a[1]) < 5:
        continue
    phrase = re.sub(r"\s+", " ", " ".join(kept[k]["text"] for k in range(i, i + 2))).strip()
    if phrase in accepted:
        continue
    fails.append(f"2-word restart «{phrase}» at src {kept[i]['start']:.2f}")

# Mirror `qc.py`'s repeat scan EXACTLY -- same n range, same n-dependent
# window, same distinct-token rule, and crucially NO minimum token length
# (rule 110, third instance). This file used to require every token to be 3+
# characters, so «شي من الـ» and «بناءً على الـ» sailed past it and the gate
# failed the render on them an hour later. A pre-flight that uses "the same
# idea, tuned differently" is not a pre-flight.
seq = [norm(w["text"]) for w in kept]
WINDOW = {3: 8, 4: 15, 5: 25, 6: 40}
hits = []
for n in (6, 5, 4, 3):
    seen = {}
    for i in range(len(seq) - n + 1):
        g = tuple(seq[i:i + n])
        if "" in g or len(set(g)) < max(2, n - 2):
            continue
        if g in seen and i - seen[g] <= WINDOW[n]:
            a, b = seen[g], i
            if not any(abs(a - x) < 8 for x, _, _ in hits):
                hits.append((a, b, n))
        seen[g] = i
for a, b, n in hits:
    phrase = re.sub(r"\s+", " ", " ".join(kept[k]["text"] for k in range(b, b + n))).strip()
    if phrase in accepted:
        continue
    if any(re.sub(r"\s+", " ", " ".join(kept[k]["text"] for k in range(b, b + m))).strip() in accepted
           for m in range(2, n + 1)):
        continue
    fails.append(f"{n}-gram repeat «{phrase}» at src "
                 f"{kept[a]['start']:.2f} -> {kept[b]['start']:.2f}")

if fails:
    print(f"\n!! {len(fails)} finding(s) -- fix these BEFORE rendering:")
    for f in fails:
        print("   " + f)
    raise SystemExit(1)
print("post-cut sweep clean (truncations, adjacent duplicates, n-gram repeats)")
