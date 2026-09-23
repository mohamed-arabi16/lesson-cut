#!/usr/bin/env python3
"""Build the take's EDL, validating every boundary against audio (rule 71).

Each entry below is a span to REMOVE, in source seconds. The script does not
trust those numbers: for every cut it measures RMS either side and reports the
true speech offset before the cut and onset after it, then places the boundary
at (last speech + PAD) -> (next speech - PAD).

Boundary snapping is ASYMMETRIC, and that is deliberate (see snap_out_of_words):
this take contains a 12.24s token and a 22.20s token, so the two directions
cannot use the same notion of "inside a word".

The cut list itself lives in cutlist.py: pauses generated from the per-second
screen classification, speech cuts authored by hand. Everything below is the
validation machinery carried forward unchanged from earlier edits -- boundary
refinement against audio RMS, asymmetric word snapping, round-then-recheck, and
the two post-conditions that refuse to write an EDL which drops a word outside a
declared cut span.

Run:  lc build_edl           # measure and report only
      lc build_edl --write   # measure, then write edl.json
"""
import json
import re
import subprocess
import sys
from pathlib import Path

import numpy as np

import lcenv                       # plugin: the tools live outside the project
HERE = lcenv.edit_dir(__file__)
# Which take this run cuts. A lesson recorded in two sittings is a NORMAL case,
# not an exception: two of the lessons this kit was built on needed one.
# Everything downstream is already multi-source (render.py resolves
# `sources[r["source"]]` and applies a per-source `av_offset_s`; build_captions.py
# loads a transcript per source), so this file was the only thing hardcoding a
# single take.
#
#   lc build_edl --write                       # take1 -> edl.json
#   lc build_edl --source take2 --write        # take2 -> edl-take2.json
#
# The cut list follows the source name (`cutlist.py` for take1, `cutlist_take2.py`
# for take2), so the two takes' cuts never sit in one file arguing about which
# timeline a number belongs to. Merge with merge_edl.py once both are written.
SOURCE = "take1"
for _i, _a in enumerate(sys.argv):
    if _a == "--source" and _i + 1 < len(sys.argv):
        SOURCE = sys.argv[_i + 1]
if not re.fullmatch(r"take\d+", SOURCE):
    sys.exit(f"--source must look like take1/take2, got {SOURCE!r}")
_cand = [HERE.parent / f"{SOURCE}{e}" for e in (".mov", ".mp4", ".MOV", ".MP4")]
SRC = next((c for c in _cand if c.exists()), _cand[0])
# Rule 154: on a STITCHED lesson `edl.json` is merge_edl.py's OUTPUT, not this
# script's. Writing take1's EDL over it silently deletes every range belonging to
# take2, and no post-condition here can notice: take1's ranges validate perfectly
# against take1's transcript, so the straddle check and the dropped-word check
# both report zero while half the lesson is gone. Once this threw away more than
# half of a stitched lesson's ranges and nearly two thirds of its runtime, and
# printed "0 violation(s)" doing it. Detect the stitched case and write the
# per-take file.
# The discriminator must be EVIDENCE OF A SECOND TAKE, not the presence of a
# tool. The first version of this guard also fired on `merge_edl.py` existing,
# and merge_edl.py then shipped in the kit EVERY project was copied from, so it
# declared a single-take shoot stitched, wrote edl-take1.json, and every
# downstream step failed on a missing edl.json. A guard that cannot tell the
# case it protects from the ordinary case is a new defect, not a fix.
_sources = [q for q in HERE.parent.glob("take*") if q.suffix.lower() in (".mov", ".mp4")]
_explicit_source = "--source" in sys.argv
_STITCHED = (any(HERE.glob("edl-take*.json"))     # a per-take EDL already exists
             or len(_sources) > 1                  # more than one take on disk
             or _explicit_source)                  # caller asked for one take by name
if _STITCHED:
    OUT_NAME = f"edl-{SOURCE}.json"
else:
    OUT_NAME = "edl.json" if SOURCE == "take1" else f"edl-{SOURCE}.json"
HOP = 0.02
PAD = 0.12
# Must match build_captions.py's MAX_WORD_S. The caption builder pulls a long
# token's START forward to end-MAX_WORD_S; if this file used a different number
# the cut and the caption would disagree about where a word begins.
MAX_WORD_S = 1.0

# (cut_from, cut_to, reason, keep_tail, refine_start, refine_end) -- source seconds.
# Trailing fields may be omitted; defaults are keep_tail=0.0, both refines True.
#
# keep_tail preserves that many seconds immediately before speech resumes, for
# windows where the SCREEN is doing something worth seeing. Every wordless
# window in this take was classified per second with the webcam inset masked
# (rules 66/72) by picture.py; the block counts are quoted in the reasons.
#
# refine_start / refine_end say whether that edge is an AUDIO fact or a
# TRANSCRIPT fact, and getting this wrong is how an earlier lesson shipped a
# doubled «طيب» (rule 79). Three distinct cases, all present in this take:
#
#   * dead air between two utterances  -> refine BOTH. RMS knows where the
#     voice actually stops and starts; the token boundaries do not.
#   * a cut that REMOVES SPEECH (false start, retake, doubled word, an
#     instruction to the editor) -> refine NEITHER. Letting RMS place the start
#     walks it past the first word of the flub and leaves that word on both
#     sides of the join; letting RMS place the end walks it INTO the good take.
#     The first pass of this file did exactly that to «والموظف» and «مرة».
#   * a cut that keeps N seconds of silent screen at its HEAD (watch the model
#     start working, then jump) -> refine_start=False. Refinement would drag the
#     start back to the last spoken word and delete the very seconds intended to
#     be kept. It silently ate 3s of streaming at 464 and 1.9s of scroll at 1303.
CUTS = __import__("cutlist" if SOURCE == "take1" else f"cutlist_{SOURCE}").CUTS  # noqa: E402



def prof(start, dur):
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", f"{start}", "-t", f"{dur}", "-i", str(SRC),
         "-vn", "-ac", "1", "-ar", "16000", "-f", "s16le", "-"],
        capture_output=True).stdout
    a = np.frombuffer(raw, dtype=np.int16).astype(np.float64) / 32768.0
    n = int(16000 * HOP)
    a = a[:len(a) // n * n]
    return np.sqrt((a.reshape(-1, n) ** 2).mean(axis=1)) if len(a) else np.array([])


def total_duration():
    return float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
         str(SRC)], capture_output=True, text=True).stdout.strip())


# Measured audible extents (measure_tokens.py), not Scribe's logged spans. The
# two must be the same list the caption builder uses or the cut and the caption
# disagree about where a word is. See measure_tokens.py for why the old
# MAX_WORD_S heuristic was backwards on 123 of this take's words.
_AUD = HERE / "transcripts" / f"{SOURCE}.audible.json"
if not _AUD.exists():
    sys.exit(f"no {_AUD.relative_to(HERE)}: run `lc measure_tokens` first "
             "(lc intake does it for you). Cuts are placed on MEASURED word extents.")
WORDS = json.loads(_AUD.read_text())


def snap_out_of_words(t, forward):
    """Never cut inside a word (the studio's older hard rule, which audio-only
    refinement violates on its own -- rule 79). Iterate, because stepping out of
    one token can land inside the next.

    The two directions use DIFFERENT word extents, and that asymmetry is the
    point:

    * A cut's START uses the RAW extents. The caption builder assigns a word to
      the range containing its END, so if a cut begins before some word's end
      that word vanishes from the captions while staying in the audio. Raw
      extents push the start past the whole token, which is exactly right.

    * A cut's END uses CLAMPED extents (start = end - MAX_WORD_S), matching what
      build_captions.py does. Raw extents here would be catastrophic on this
      take: the 22.20s «بنلاحظ» token would swallow any end placed inside it and
      snap the cut back to 1254.8, restoring all 25 seconds of dead air. The
      real utterance occupies at most the last MAX_WORD_S of the token, so
      clamping is both safe and the same assumption the captions make.
    """
    # EPS matters: an edge deliberately placed ON a word's start or end is not
    # "inside" it. Without the tolerance, float round-trip through the transcript
    # made 878.91 test as strictly greater than «هلأ»'s own start of 878.91, so
    # the snapper walked three words forward and left the truncated «شغـ--» in
    # the cut -- and did the same to «والموظف», re-creating the exact doubled-word
    # defect this function exists to prevent.
    EPS = 0.01
    for _ in range(8):
        hit = None
        for w in WORDS:
            # WORDS now carries MEASURED extents, so both directions use the
            # same span. The old asymmetry existed only because the END was a
            # guess (rule 82); with a measurement there is nothing to guess.
            lo = w["start"]
            if lo + EPS < t < w["end"] - EPS:
                hit = w
                break
        if hit is None:
            return round(t, 2)
        t = (hit["end"] + 0.05) if forward else (hit["start"] - 0.05)
    return round(t, 2)


def last_word_end_at_or_before(t):
    """End of the last word that finishes at or before t, or None."""
    ends = [w["end"] for w in WORDS if w["end"] <= t + 0.01]
    return max(ends) if ends else None


def settle(t):
    """Final value written to the EDL. Round FIRST, then re-check containment.

    Everything upstream can place an edge perfectly and the last `round()` can
    still ruin it: the cut authored at 790.166 sits exactly on «مراجع»'s start,
    the quantiser correctly declines to move it (it is not inside the word), and
    then rounding to 2dp writes 790.17 -- 4ms INSIDE the word, clipping its
    onset. Rule 84 was about a comparison inverting on float equality; this is
    the same defect committed by the write itself, and no amount of care further
    up the pipeline can prevent it.

    So: round to 3dp (10x the precision the transcript is quoted at), then run
    the containment check on the ROUNDED value, which is the number that will
    actually be written. An edge inside a word moves to just before that word,
    which is safe in both roles: as a range END it stops before a word that is
    being removed anyway, and as a range START it keeps the word whole.
    """
    t = round(t, 3)
    for _ in range(4):
        hit = next((w for w in WORDS if w["start"] < t < w["end"]), None)
        if hit is None:
            return t
        t = round(hit["start"] - 0.01, 3)
    return t


def clear_audible_window(t):
    """Keep an edge out of qc.py's audibility window.

    qc.py decides "is this boundary inside a word, and is the audio there
    audible" by taking the mean RMS over +/-60ms centred on the boundary. An
    edge placed on the last audible 20ms frame therefore still measures audible,
    because half of qc's window is real speech. The two tools are both right and
    they disagree by construction.

    Only fires when the edge sits inside a word's LOGGED span but after that
    word's MEASURED end, i.e. in the padding Scribe added. Pushes clear of the
    window without ever reaching the next word.
    """
    for w in WORDS:
        if w["logged_start"] < t < w["logged_end"] and t >= w["end"] - 0.001:
            want = w["end"] + 0.15
            nxt = min((x["start"] for x in WORDS if x["start"] > w["end"] + 0.001),
                      default=None)
            if nxt is not None:
                want = min(want, nxt - 0.05)
            return round(max(t, want), 3) if want > t else t
    return t


def refine(a, b, dur, keep_tail=0.0, refine_start=True, refine_end=True):
    """Move a cut's edges onto real speech offset/onset."""
    lo, hi = max(0.0, a - 5), min(dur, b + 5)
    p = prof(lo, hi - lo)
    if not len(p):
        return a, b
    thr = float(np.percentile(p, 95)) * (10 ** (-14.0 / 20))
    t = lambda i: lo + i * HOP
    loud = np.where(p > thr)[0]
    before = [i for i in loud if t(i) <= a + 0.25]
    after = [i for i in loud if t(i) >= b - 0.25]
    na = ((t(before[-1]) + PAD) if before else a) if refine_start else a
    nb = ((t(after[0]) - PAD - keep_tail) if after else b) if refine_end else b
    na, nb = min(na, b), max(nb, a)
    # A word's tail decays below any RMS threshold, so `before` can land on the
    # word's own START and the refiner then places the cut there. The straddle
    # assertion never fires (the edge is ON the boundary, not inside it) but the
    # caption builder assigns a word to the range holding its END -- so the word
    # vanishes from the burned captions while staying in the audio. That is rule
    # 79(b) at the other edge. Measured here: the cut authored at 716.40 refined
    # back to 715.75 and ate «يستخدمها».
    # A refined start may never precede the end of the last word before the cut
    # as AUTHORED. Cuts that deliberately remove speech are unaffected, because
    # their authored `a` already sits at or after the last kept word.
    # +0.03 rather than landing exactly ON the word end: the caption builder's
    # range test is `start < word.end <= end`, so an edge sitting on the
    # boundary is decided by float equality. 30ms is the low end of the ledger's
    # 30-200ms padding and is inaudible.
    floor = last_word_end_at_or_before(a)
    if floor is not None:
        want = floor + 0.03
        # ...but never past the START of the next word. The 30ms is a guard on
        # the PREVIOUS word's tail; when the gap to the next word is smaller than
        # the guard, applying it literally steps over the boundary it exists to
        # respect and lands inside the word the cut is meant to REMOVE. The
        # snapper then walks forward out of that word and the cut collapses to
        # nothing. On this take «friction» ends at 158.900 and «إني» starts at
        # 158.920 -- a 20ms gap against a 30ms guard -- and the cut that removes
        # the truncated «نضل--» was silently skipped twice because of it.
        nxt = min((w["start"] for w in WORDS if w["start"] >= floor - 0.001),
                  default=None)
        if nxt is not None:
            want = min(want, nxt - 0.005)
        na = max(na, want)
    # The cut list is typed to 2 decimals; the transcript is not. A cut end
    # authored as 879.97 to sit exactly on «مهام» lands 4ms INSIDE it (879.966),
    # which clips the word's attack and fails qc.py's mid-word check. build_edl's
    # own straddle assertion has a 10ms tolerance and waves it through, so the
    # two checks disagree by construction. Snap any end that is a hair past a
    # word's start back onto that start, minus 10ms of the silence in front.
    for w in WORDS:
        if w["start"] < nb < w["end"]:
            nb = w["start"] - 0.01
            break
    na, nb = snap_out_of_words(na, forward=True), snap_out_of_words(nb, forward=False)
    na, nb = clear_audible_window(na), clear_audible_window(nb)
    return (settle(na), settle(nb))


def main():
    dur = total_duration()
    cuts = []
    print(f"source {SRC.name}  {dur:.2f}s\n")
    for entry in CUTS:
        a, b, why = entry[0], entry[1], entry[2]
        keep = entry[3] if len(entry) > 3 else 0.0
        ref_start = entry[4] if len(entry) > 4 else True
        ref_end = entry[5] if len(entry) > 5 else True
        b = min(b, dur)
        if a <= 0.0:
            na, nb = 0.0, refine(a, b, dur, keep, ref_start, ref_end)[1]
        elif b >= dur - 0.05:
            na, nb = refine(a, b, dur, keep, ref_start, ref_end)[0], dur
        else:
            na, nb = refine(a, b, dur, keep, ref_start, ref_end)
        if nb - na < 0.15:
            print(f"  cut {a:8.2f}-{b:8.2f}  ->  SKIPPED (no clean boundary, "
                  f"{nb-na:.2f}s)  {why[:44]}")
            continue
        print(f"  cut {a:8.2f}-{b:8.2f}  ->  {na:8.2f}-{nb:8.2f}  "
              f"({nb-na:6.2f}s)  {why[:70]}")
        cuts.append((na, nb, why))

    # The range walk below is a monotonic sweep: `pos = max(pos, nb)`. An entry
    # typed out of chronological order is therefore SILENTLY SWALLOWED -- its
    # start is already behind `pos`, so no range is emitted and the cut simply
    # does not happen, with no error anywhere. Three cuts added late in this
    # edit landed mid-list and one retake stopped being cut; the only symptom
    # was the runtime going UP by 3s after adding 5.8s of cuts. Sort, then
    # assert the cuts do not overlap, before building anything.
    cuts.sort(key=lambda c: c[0])
    # An earlier version exited here on any overlap. That was right for a
    # hand-typed list, where an overlap means a typo -- but the thing it actually
    # protected against was a cut being SILENTLY SWALLOWED by the monotonic walk
    # below, and the sort on the line above is what fixes that. Refinement
    # legitimately grows adjacent cuts into each other (a demo window's end moving
    # 0.3s right into the false start behind it), and exiting on that turns a
    # correct edit into an authoring puzzle: it happened twice in a row on one
    # lesson. Union them instead and SAY SO, so nothing is swallowed and nothing
    # is hidden.
    merged = []
    for c in cuts:
        if merged and c[0] < merged[-1][1] - 0.001:
            prev = merged[-1]
            print(f"  merged overlapping cuts {prev[0]:.2f}-{prev[1]:.2f} and "
                  f"{c[0]:.2f}-{c[1]:.2f} (refinement grew them together)")
            merged[-1] = (prev[0], max(prev[1], c[1]), f"{prev[2]} + {c[2]}")
        else:
            merged.append(c)
    cuts = merged

    # A kept piece shorter than MIN_SLIVER with no word in it is two or three
    # frames of picture between two cuts: it ships as a flash of a different
    # screen and says nothing. It is dropped, and counted. (27 of them were in
    # one long shipped lesson, every one invisible to the gate.)
    MIN_SLIVER = 0.10
    slivers = 0
    ranges, pos, n = [], 0.0, 0
    for na, nb, why in cuts:
        if na > pos + 0.05:
            wordless = not any(w["start"] < na and w["end"] > pos for w in WORDS)
            if na - pos < MIN_SLIVER and wordless:
                slivers += 1
            else:
                ranges.append({"source": SOURCE, "start": round(pos, 2), "end": round(na, 2),
                               "beat": f"SEG-{n:02d}",
                               "reason": f"Resumes after cutting: {why}"})
                n += 1
        pos = max(pos, nb)
    if slivers:
        print(f"  dropped {slivers} kept sliver(s) under {MIN_SLIVER:.2f}s with no word in them "
              f"(each would flash a frame or two of a different picture)")
    if pos < dur - 0.05:
        ranges.append({"source": SOURCE, "start": round(pos, 2), "end": round(dur, 2),
                       "beat": f"SEG-{n:02d}", "reason": "tail"})

    kept = sum(r["end"] - r["start"] for r in ranges)
    print(f"\n  {len(ranges)} ranges, {kept:.2f}s kept "
          f"({int(kept//60)}m{kept%60:04.1f}s) from {dur:.2f}s "
          f"-- removed {dur-kept:.2f}s")

    # rule 79: assert no transcript word straddles any range boundary. This is
    # the check that caught «الجاي» being clipped off a lesson's closing line.
    bad = 0
    for r in ranges:
        for edge in (r["start"], r["end"]):
            for w in WORDS:
                lo = w["start"]
                if lo + 0.01 < edge < w["end"] - 0.01:
                    print(f"  !! boundary {edge:.2f} sits inside «{w['text']}» "
                          f"({w['start']:.2f}-{w['end']:.2f})")
                    bad += 1
    print(f"  boundary/word straddle check: {bad} violation(s)")

    # every word must land in exactly one kept range, or it is dropped from the
    # captions while remaining in the audio (rule 79b)
    lost = [w for w in WORDS
            if not any(r["start"] < w["end"] <= r["end"] for r in ranges)]
    declared = [(e[0], min(e[1], dur)) for e in CUTS]
    stray = [w for w in lost
             if not any(a <= w["end"] <= b for a, b in declared)]
    print(f"  words dropped from captions by the cut: {len(lost)} "
          f"({len(stray)} NOT inside any declared cut span)")
    for w in stray:
        print(f"     !! UNINTENDED  {w['start']:8.2f}-{w['end']:8.2f}  «{w['text']}»")
    if stray:
        sys.exit(f"  {len(stray)} word(s) dropped outside the authored cuts -- refusing to write")

    if "--write" in sys.argv:
        edl = {
            "version": 1,
            "sources": {SOURCE: str(SRC)},
            # How far this source's AUDIO runs ahead of its picture, in seconds.
            # render.py takes the picture that much later. It is a property of
            # the recording rig, not of the tool: the value this kit was built
            # on was 0.24 (a screen recorder exporting with the audio early),
            # and stamping that onto anyone else's footage shifts their lips
            # 240ms off their voice. Set it per project in project.json as
            # render.av_offset_s, measured by eye on a frame where a hard sound
            # meets a visible action (a click, a clap, a plosive).
            "av_offset_s": {SOURCE: float(lcenv.project_config(HERE)
                                          .get("render", {}).get("av_offset_s", 0.0))},
            "grade": "",
            "ranges": ranges,
            "overlays": [],
            "subtitles": "master.ass",   # MUST be set: render.py burns nothing without it
            "total_duration_s": round(kept, 2),
        }
        (HERE / OUT_NAME).write_text(json.dumps(edl, ensure_ascii=False, indent=2))
        print(f"  wrote {HERE/OUT_NAME}")
        if _STITCHED:
            print("  STITCHED LESSON: edl.json is merge_edl.py's output and was NOT "
                  "touched.\n  Re-run:  lc merge_edl " +
                  " ".join(sorted(p.name for p in HERE.glob("edl-take*.json"))) + " --write")


if __name__ == "__main__":
    main()
