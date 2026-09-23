#!/usr/bin/env python3
"""Turn editorial cut decisions into cutlist.py SPEECH_CUTS lines.

Input JSON: [{"rm": first_removed_word_start, "keep": first_kept_word_start, "why": "..."}]
  rm   = start (logged) of the first word to REMOVE
  keep = start (logged) of the first word to KEEP after the cut

Decisions are converted to WORD-INDEX ranges [i, j) and unioned, so two
readers' overlapping findings become one cut (build_edl refuses overlapping
spans). Edges then go into the silence around the removed words, using
MEASURED audible extents (rules 86/102):

  a = max(prev.end + min(0.03, gap/2), first_removed.start - 0.12)
  b = min(next.start - min(0.03, gap/2), last_removed.end + 0.12)

i.e. the WORDS are cut and the silence either side stays, so tighten_gaps.py
can measure the join the viewer hears and keep a beat of the busiest picture on
long waits. A head cut ends at the first kept word's onset - 0.25s, unless a
removed word ends inside that 0.25s. A keep time after the last word makes a
tail cut to the end of the source. Prints every dropped word so each cut can be
audited.

  lc mkcuts decisions.json > speech_cuts.txt

On one real lesson, about 240 verified reader findings collapsed to under 200
cuts. Two rules it encodes (ledger 159):
  * UNION BY WORD INDEX, not by time: two readers' overlapping findings become
    one cut, and build_edl never sees an overlapping list.
  * PAD = min(0.03, gap/2): a fixed 30ms pad puts the edge INSIDE a removed word
    whenever two words abut (20ms gaps are routine), and the caption builder,
    which assigns a word by its END, then keeps the word the cut removes.
The output goes into cutlist.py SPEECH_CUTS; read the "‖ [dropped] ‖" audit
lines before building.
"""
import json
import sys
from pathlib import Path

import lcenv                       # plugin: the tools live outside the project
EDIT = lcenv.edit_dir(__file__)          # run from a project's edit/ dir
AUD = json.loads((EDIT / "transcripts/take1.audible.json").read_text())


def idx_at(t):
    """First word whose logged start is at or after t (60ms tolerance). Readers
    sometimes give a gap point rather than an exact word start."""
    for i, w in enumerate(AUD):
        if w["logged_start"] >= t - 0.06:
            if w["logged_start"] - t > 1.5:
                print(f"# !! {t}: next word «{w['text']}» starts {w['logged_start']}",
                      file=sys.stderr)
            return i
    # Past the last word: there is no next word to keep. Returning the last
    # word's index here used to keep that word silently, so a tail cut could
    # never remove the final word of a take.
    return len(AUD)


TAIL_END = 99999.0                      # "to the end of the source"; build_edl clips it

if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
    sys.exit(__doc__)
decisions = json.loads(Path(sys.argv[1]).read_text())
ranges = []
def _k(d, *names):
    for n in names:
        if n in d:
            return d[n]
    sys.exit(f"decision is missing '{names[0]}': {d}")


for d in decisions:
    if str(d.get("kind", "")) == "accuracy_flag":
        sys.exit("a decision marked accuracy_flag is a FLAG for the operator, not a cut: "
                 f"remove it from this file ({d.get('id') or d.get('why') or d.get('reason')})")
    # the short keys, or the editorial workflow's own (so its `surviving` list
    # can be passed in unchanged)
    d = {"rm": _k(d, "rm", "first_removed_word_start"),
         "keep": _k(d, "keep", "first_kept_word_start"),
         "why": str(d.get("why") or d.get("reason") or d.get("id") or "")}
    i, j = idx_at(d["rm"]), idx_at(d["keep"])
    if i >= len(AUD):
        sys.exit(f"rm ({d['rm']}) is after the last word of the take: {d['why']}")
    if j <= i:
        sys.exit(f"keep ({d['keep']}) is not after rm ({d['rm']}): {d['why']}")
    ranges.append([i, j, [d["why"]]])
ranges.sort()
merged = []
for r in ranges:
    if merged and r[0] <= merged[-1][1]:          # overlapping or touching
        merged[-1][1] = max(merged[-1][1], r[1])
        merged[-1][2] += r[2]
    else:
        merged.append(r)

out, problems, total = [], 0, 0.0
for i, j, whys in merged:
    prev = AUD[i - 1] if i > 0 else None
    nxt = AUD[j] if j < len(AUD) else None
    first_rm, last_rm = AUD[i], AUD[j - 1]
    if prev is None and nxt is None:
        sys.exit("these decisions remove every word in the take")
    # min(0.03, gap/2): when two words abut (a 20ms gap), a fixed 30ms pad
    # would put the edge INSIDE the removed word and the caption builder,
    # which assigns a word by its END, would keep it (found on a real take at
    # «Claude» 4514.78 / «بنلاقي» 4514.80).
    if prev is None:
        a = 0.0
    else:
        a = max(prev["end"] + min(0.03, (first_rm["start"] - prev["end"]) / 2),
                first_rm["start"] - 0.12)
    if nxt is None:
        b = TAIL_END                    # build_edl clips this to the source's end
    else:
        b = min(nxt["start"] - min(0.03, (nxt["start"] - last_rm["end"]) / 2),
                last_rm["end"] + 0.12)
        if prev is None and nxt["start"] - 0.25 >= last_rm["end"] + 0.01:
            # A head cut ends 0.25s before the first kept word's onset, so the
            # viewer hears a clean lead-in rather than a clipped first syllable.
            # Only when the removed word actually ends before that point: a
            # removed word closer than 0.25s to the kept one would otherwise
            # sit inside the kept range, and build_edl would keep it silently.
            b = nxt["start"] - 0.25
    if b - a < 0.05:
        print(f"# !! collapsed cut {a:.3f}-{b:.3f}: {whys}", file=sys.stderr)
        problems += 1
    total += (last_rm["end"] if nxt is None else b) - a   # a tail cut's TAIL_END is not real source
    dropped = " ".join(w["text"] for w in AUD[i:j])
    before = " ".join(w["text"] for w in AUD[max(0, i - 4):i])
    after = " ".join(w["text"] for w in AUD[j:j + 4])
    why = json.dumps(" | ".join(whys).replace("\n", " "), ensure_ascii=False)
    out.append(f'    ({a:.3f}, {b:.3f}, {why}, 0.0, False, False),\n'
               f'    #   …{before} ‖ [{dropped}] ‖ {after}…')
print("\n".join(out))
print(f"# {len(merged)} merged cuts from {len(decisions)} decisions, "
      f"{total:.1f}s of source removed by speech cuts, {problems} problems", file=sys.stderr)
