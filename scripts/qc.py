#!/usr/bin/env python3
"""Multi-pass mechanical QC gate for a finished video.

Standing instruction (the operator, 2026-08-13): "I do not tolerate such mistakes.
I told you I don't need to go over the videos and find bugs like this, so you
have to do the quality control three or four times. Each time you check for a
different thing until I have a completely ready-to-publish video."

So QC is not one careful look. It is N independent passes, each hunting ONE
defect class, each mechanical wherever a machine can decide it. A pass that
depends on an agent noticing something is a pass that will eventually miss it.

Passes
  1 transcript  - words that survived a cut but should not have
  2 captions    - the .ass as data: artifacts, overlaps, timing, RTL
  3 caption-px  - the .ass as PIXELS: real rendered width vs the frame edge
  4 video       - the rendered frames: corner object, black/frozen frames
  5 audio       - seams, pops, residual dead air, loudness
  6 spec        - resolution/fps/duration/decode integrity vs the EDL

Usage
  lc qc all      --edit-dir <dir> --video <final.mp4>
  lc qc <pass>   --edit-dir <dir> --video <final.mp4>

Exit code is the number of FAILing passes, so it can gate a delivery.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import sys
import tempfile
import unicodedata
from pathlib import Path

import numpy as np
from PIL import Image

AR = r"ء-ي"
# Bidi controls, written as escapes: a literal bidi control in source is
# invisible, and it makes GitHub flag the file as possibly hiding code.
RLE, PDF = "\u202b", "\u202c"


# A right-to-left LETTER: a letter (Unicode category L*) whose bidi class is R
# or AL, which covers Hebrew, Arabic, Syriac, Thaana, NKo and the other
# right-to-left scripts. The Arabic comma (CS), Arabic-Indic digits (AN) and
# the Arabic question mark and semicolon (AL, but punctuation) are not, so an
# all-Latin line carrying one of them is a left-to-right line.
# build_captions.py holds the same test; change both together.
def has_rtl(s: str) -> bool:
    return any(unicodedata.bidirectional(ch) in ("R", "AL")
               and unicodedata.category(ch).startswith("L") for ch in s)


# Function words carry no signal about whether a line was restarted -- they
# recur constantly in ordinary speech, so they are excluded before comparing
# across a pause. Stored normalised (see norm()).
STOPWORDS = {norm_w for norm_w in (
    "في", "من", "على", "مع", "او", "و", "هذا", "هذي", "هذه", "اللي", "انت",
    "انا", "يعني", "بس", "شي", "ان", "ما", "لا", "هو", "هي", "كل", "عن",
    "اذا", "لك", "له", "بعد", "قبل", "التي", "الذي", "ترى", "زين", "شو",
    "هني", "هنا", "بعد", "عشان", "لأن", "لان", "أنه", "انه", "بتشوف", "خلني",
)}


# ---------------------------------------------------------------- utilities

class Result:
    def __init__(self, name: str):
        self.name = name
        self.problems: list[str] = []
        self.notes: list[str] = []

    def fail(self, msg: str) -> None:
        self.problems.append(msg)

    def note(self, msg: str) -> None:
        self.notes.append(msg)

    def report(self) -> bool:
        ok = not self.problems
        print(f"\n{'=' * 72}")
        print(f"PASS {self.name}: {'OK' if ok else 'FAIL (' + str(len(self.problems)) + ')'}")
        print("=" * 72)
        for n in self.notes:
            print(f"  . {n}")
        for p in self.problems:
            print(f"  X {p}")
        return ok


def video_stream_duration(video: Path) -> float:
    """The VIDEO stream's own length. The container reports its longest stream,
    so a file whose picture stops halfway through its sound looked complete."""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=duration:format=duration", "-of", "json", str(video)],
        capture_output=True, text=True, check=True)
    d = json.loads(out.stdout)
    st = (d.get("streams") or [{}])[0]
    try:
        return float(st["duration"])
    except (KeyError, TypeError, ValueError):
        return float(d["format"]["duration"])


def probe(video: Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height,r_frame_rate,codec_name,nb_read_packets",
         "-show_entries", "format=duration,size", "-of", "json", str(video)],
        capture_output=True, text=True, check=True,
    )
    return json.loads(out.stdout)


def load_edl(edit_dir: Path) -> dict:
    return json.loads((edit_dir / "edl.json").read_text())


def load_words(edit_dir: Path, edl: dict) -> dict[str, list[dict]]:
    tr = edit_dir / "transcripts"
    out = {}
    for key, src in edl["sources"].items():
        p = tr / f"{Path(src).stem}.json"
        if p.exists():
            out[key] = [w for w in json.loads(p.read_text()).get("words", [])
                        if w.get("type") == "word" and w.get("start") is not None]
    return out


def kept_words(edl: dict, words: dict) -> list[dict]:
    """Every word that survives into the output, with its output timestamp."""
    kept, offset = [], 0.0
    for r in edl["ranges"]:
        s, e = float(r["start"]), float(r["end"])
        for w in words.get(r["source"], []):
            if w["start"] >= s and w["end"] <= e:
                kept.append({**w, "out": w["start"] - s + offset, "seg": r.get("beat", ""),
                             "src": r["source"]})
        offset += e - s
    return kept


def norm(w: str) -> str:
    w = re.sub(rf"[ً-ْـ]", "", w)
    w = (w.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
          .replace("ى", "ي").replace("ة", "ه"))
    # NOTE (2026-08-28, rule 126): the character class used to be
    # `[^\w\u0600-\u06FF]`, which was meant to read "keep word characters and
    # Arabic". Python 3's `\w` is already Unicode-aware and matches Arabic
    # letters, so the extra range added nothing EXCEPT re-admitting the Arabic
    # punctuation that lives inside it: the comma U+060C, the semicolon U+061B
    # and the question mark U+061F. ASCII punctuation was stripped, Arabic
    # punctuation was not, so «ملخص،» never compared equal to «ملخص» and every
    # repeat check silently skipped any pair Scribe had punctuated differently.
    return re.sub(r"[^\w]", "", w).lower()


# English function words too: a lesson that mixes languages repeats "it will",
# "the", "a" constantly, and without them the restart check read «it will a» as
# three repeated CONTENT words and failed an ordinary parallel list ("And it will
# pick a route. / It will draft a response.").
STOPWORDS |= {
    "a", "an", "the", "and", "or", "but", "so", "to", "of", "in", "on", "at", "for", "with",
    "from", "by", "as", "is", "are", "was", "were", "be", "been", "it", "its", "this", "that",
    "these", "those", "i", "you", "we", "he", "she", "they", "me", "my", "your", "our", "their",
    "will", "would", "can", "could", "should", "do", "does", "did", "have", "has", "had",
    "not", "no", "if", "then", "just", "now", "here", "there", "what", "which", "who",
    "how", "all", "any", "some", "one", "okay", "ok", "yes", "like", "also", "very",
}

# The list above is written the way people type it; compare it the way the
# checks compare words. Without this, «على» (normalised علي) never matched.
STOPWORDS = {norm(w) for w in STOPWORDS}


# ------------------------------------------------------- 1. transcript pass

def pass_transcript(edit_dir: Path, video: Path) -> Result:
    """Words that survived the cut but should not have."""
    r = Result("1 transcript")
    edl = load_edl(edit_dir)
    words = load_words(edit_dir, edl)
    if not words:
        r.fail("no transcripts found - cannot verify content")
        return r
    kept = kept_words(edl, words)
    r.note(f"{len(kept)} words survive into the output across {len(edl['ranges'])} ranges")

    # (a) truncated words: Scribe marks a cut-off word with a trailing --
    trunc_accepted = {a["phrase"].strip() for a in
                      (json.loads((edit_dir / "qc-accept.json").read_text())
                       if (edit_dir / "qc-accept.json").exists() else [])}
    for w in kept:
        t = (w.get("text") or "").strip()
        # A truncated token can be genuinely uncuttable: when its end coincides
        # with the next word's start there is no boundary to place an edge on,
        # and build_edl is right to refuse. Accepting one is allowed ONLY with a
        # written reason, and only when it is absent from the delivered CAPTIONS
        # as well -- which is what rule 48 protects. Never on size alone.
        if t in trunc_accepted:
            continue
        if t.endswith("--") or t.endswith("-"):
            r.fail(f"truncated word '{t}' survived at output {w['out']:.2f}s "
                   f"(seg {w['seg']}) - speaker cut himself off, cut was missed")

    # (b) a cut that lands INSIDE a word (never cut mid-word)
    #
    # The reason this check exists is "do not clip audible speech" -- token
    # containment is only a proxy for it, and rule 71 is the case where the proxy
    # is wrong: Scribe can log a long pause INSIDE a word token (one take has a
    # `في` token 2.42s long, of which 1.35s is pure silence, because he began
    # the word, paused, then restarted). Starting a range in that silence is
    # correct and is exactly what removes the dead opening. So when a boundary
    # lands inside a token, measure the audio there: silence means nothing is
    # being clipped (rule 63 -- encode the reason, not the proxy).
    srcs = {k: ((edit_dir / v).resolve() if not Path(v).is_absolute() else Path(v))
            for k, v in edl["sources"].items()}

    # 2026-08-17 (rule 78, applied here too): the threshold has to be RELATIVE to
    # each source. The old absolute 0.006 was calibrated on the operator's screen
    # recordings; a camera take's audio after loudnorm has a noise floor around
    # 0.014-0.024, so deep silence measured "audible" and every rule-71 boundary
    # -- the whole point of the silent-token escape hatch below -- failed the
    # gate. Speech on these sources peaks around 0.19-0.31.
    _floor: dict[str, float] = {}

    def speech_floor(src_key: str, p: Path) -> float:
        if src_key not in _floor:
            raw = subprocess.run(
                ["ffmpeg", "-v", "error", "-i", str(p), "-vn", "-ac", "1",
                 "-ar", "8000", "-f", "s16le", "-"], capture_output=True).stdout
            a = np.frombuffer(raw, dtype=np.int16).astype(np.float64) / 32768.0
            n = 400                                        # 50ms frames
            a = a[:len(a) // n * n]
            if len(a) == 0:
                _floor[src_key] = 0.006
            else:
                lv = np.sqrt((a.reshape(-1, n) ** 2).mean(axis=1))
                # 20dB under this source's own speech level
                _floor[src_key] = float(np.percentile(lv, 90)) * (10 ** (-20.0 / 20))
        return _floor[src_key]

    def audible_at(src_key: str, t: float) -> bool:
        p = srcs.get(src_key)
        if p is None or not p.exists():
            return True                      # cannot measure -> assume the worst
        raw = subprocess.run(
            ["ffmpeg", "-v", "error", "-ss", f"{max(0.0, t - 0.06):.3f}", "-t", "0.12",
             "-i", str(p), "-ac", "1", "-ar", "16000", "-f", "s16le", "-"],
            capture_output=True,
        ).stdout
        if len(raw) < 320:
            return True
        a = np.frombuffer(raw, dtype=np.int16).astype(np.float64) / 32768.0
        return float(np.sqrt((a ** 2).mean())) > speech_floor(src_key, p)

    for rg in edl["ranges"]:
        s, e = float(rg["start"]), float(rg["end"])
        for w in words.get(rg["source"], []):
            if w["start"] < s < w["end"] - 0.02:
                if audible_at(rg["source"], s):
                    r.fail(f"range start {s:.3f} lands inside word '{w.get('text')}' "
                           f"({w['start']:.3f}-{w['end']:.3f}) and the audio there is "
                           f"AUDIBLE - this clips speech")
                else:
                    r.note(f"range start {s:.3f} is inside token '{w.get('text')}' "
                           f"({w['start']:.3f}-{w['end']:.3f}) but the audio there is "
                           f"silent - a pause inside the token, nothing clipped")
            if w["start"] + 0.02 < e < w["end"]:
                if audible_at(rg["source"], e):
                    r.fail(f"range end {e:.3f} lands inside word '{w.get('text')}' "
                           f"({w['start']:.3f}-{w['end']:.3f}) and the audio there is "
                           f"AUDIBLE - this clips speech")
                else:
                    r.note(f"range end {e:.3f} is inside token '{w.get('text')}' "
                           f"({w['start']:.3f}-{w['end']:.3f}) but the audio there is "
                           f"silent - a pause inside the token, nothing clipped")

    # Verified-deliberate repetitions are recorded per project rather than
    # silently loosening a detector. Loaded here rather than further down
    # because BOTH the restart check (b2) and the n-gram check (c) need it:
    # (b2)'s "the N words before the pause are repeated right after it" branch
    # cannot tell a fixed compound noun from a restart. «الذكاء الاصطناعي» is
    # one lexical unit and can be the subject of a whole lesson, so it legitimately
    # closes one sentence and opens the next; as a 2-word run it looks identical
    # to a trail-off. The detector is not relaxed -- the judgement is written
    # down, dated and reviewable, which is what this file is for (rule 63).
    accept_path = edit_dir / "qc-accept.json"
    accepted = json.loads(accept_path.read_text()) if accept_path.exists() else []
    # An accept entry without a written reason is not an accept, it is a silent
    # whitelist (rule 90). Refuse it here with a clear message rather than
    # KeyError-ing later while printing the justification -- which is what
    # happened on a real project, where the file used "why" instead of "reason" and
    # took the whole transcript pass down with it. Rule 67: a pass that crashes
    # is a pass that did not run, and this one crashed AFTER deciding.
    for a in accepted:
        if not a.get("reason"):
            raise SystemExit(
                f"qc-accept.json: entry for «{a.get('phrase','?')}» has no 'reason' "
                f"field (found keys: {sorted(a)}). Every accepted hit must say why.")
    acc_norm = [([norm(x) for x in a["phrase"].split()], a) for a in accepted]

    # (b2) THE RESTART PATTERN, in its general form.
    #      The operator, 2026-08-13: "make sure there are no repeated problems, as we
    #      fixed before, things like trails off mid-word, pauses, then cleanly
    #      restarts the same line right after."
    #      Check (a) only catches it when Scribe marked the abandoned word with
    #      "--", and check (c) only when the restart is near-verbatim. Neither
    #      fires when he trails off cleanly and restarts with different wording.
    #      The invariant that does hold is structural: a pause, with the words
    #      after it re-saying the words before it. So look at every pause in the
    #      DELIVERED audio and compare across it.
    RESTART_GAP = 0.8
    for i in range(len(kept) - 1):
        cur, nxt = kept[i], kept[i + 1]
        gap = nxt["out"] - (cur["out"] + (cur["end"] - cur["start"]))
        # The pause that matters is the one the SPEAKER made, in the take. The
        # tightener trims every delivered gap to about 0.3s, so measured on the
        # delivered timeline almost no pause reached 0.8s and this check went
        # silent on every tightened cut (587 source pauses on one lesson, 89
        # left after tightening). Two kept words from the same source keep
        # their source timing, and that gap is what a restart leaves behind.
        if cur.get("src") == nxt.get("src"):
            gap = max(gap, nxt["start"] - cur["end"])
        if gap < RESTART_GAP:
            continue
        before = [norm((w.get("text") or "")) for w in kept[max(0, i - 9):i + 1]]
        after = [norm((w.get("text") or "")) for w in kept[i + 1:i + 11]]
        if not before or not after:
            continue
        why = None

        # a truncated word and its completed form share a stem ("هالبرام" / "هالبرنامج")
        #
        # `run` is set HERE, not left for the block below to reset (2026-08-28,
        # rule 130). This is rule 120's defect in a second branch of the same
        # function: the branch set `why` and then `run = None` executed two lines
        # later, so the accept lookup -- which is keyed on `run` -- could never
        # match and this finding was IMPOSSIBLE to accept by construction. A stem
        # test cannot tell a truncation from two real words that share a stem:
        # «تمامًا» (completely) and «تمام؟» (okay?) are different words, and on
        # one lesson that pair failed the gate with no way to write it down.
        # Keyed on the PAIR, so accepting one stem collision never accepts another.
        run = None
        a_last, b_first = before[-1], after[0]
        if (len(a_last) >= 4 and len(b_first) >= 4 and a_last != b_first
                and (b_first.startswith(a_last) or a_last.startswith(b_first))):
            why = f"'{cur.get('text')}' looks like a truncated form of '{nxt.get('text')}'"
            run = [a_last, b_first]

        # the line is restarted: a run of words before the pause reappears after it
        if why is None:
            for j in range(4, 1, -1):
                if len(before) >= j and before[-j:] in [after[k:k + j] for k in range(4)]:
                    why = f"the {j} words before the pause are repeated right after it"
                    run = before[-j:]
                    break

        # a non-verbatim restart: the same content words come back IN THE SAME
        # ORDER. Order is what separates a restart from ordinary continuation --
        # a lesson naturally re-says its topic words ("AI", "Short cut") right
        # after a pause, but it does not re-say them in the same sequence. An
        # unordered bag-of-words test flags both and gets ignored; requiring an
        # ordered run of 3 keeps the real case (which repeated 4 in order).
        if why is None:
            ba = [w for w in before[-6:] if w and w not in STOPWORDS]
            aa = [w for w in after[:6] if w and w not in STOPWORDS]
            best = [[0] * (len(aa) + 1) for _ in range(len(ba) + 1)]
            for x in range(len(ba) - 1, -1, -1):
                for y in range(len(aa) - 1, -1, -1):
                    best[x][y] = (best[x + 1][y + 1] + 1 if ba[x] == aa[y]
                                  else max(best[x + 1][y], best[x][y + 1]))
            if best[0][0] >= 3:
                shared = [w for w in ba if w in aa]
                why = (f"{best[0][0]} content words repeat in the same order "
                       f"across the pause ({' '.join(shared[:6])})")
                # This branch used to leave `run` as None, which made its finding
                # IMPOSSIBLE to accept: the accept lookup below is keyed on `run`,
                # so a legitimate parallel list (the same two-word opener
                # introducing two different items) failed the gate for ever, or forced a cut that
                # removed real content. Set it to exactly the words the message
                # prints, so the failure text tells you what to write in
                # qc-accept.json.
                run = shared[:6]

        if why:
            # STRUCTURAL GUARD (rule 130). Every branch above that sets `why` must
            # also set `run`, because `run` is the key the written accept is looked
            # up by: a finding with no key cannot be accepted, and the only exits
            # left are cutting real speech or failing the gate for ever. That has
            # now shipped twice, in two different branches of this one function
            # (rules 120 and 130), each time silently. Fail loudly instead, so the
            # NEXT branch someone adds cannot reintroduce it.
            assert run is not None, (
                f"qc.py restart detector set why={why!r} without setting `run`. "
                "Every branch must set the accept key.")
            ctx_b = " ".join((w.get("text") or "") for w in kept[max(0, i - 6):i + 1])
            ctx_a = " ".join((w.get("text") or "") for w in kept[i + 1:i + 8])
            # Match the accept against the REPEATED RUN itself, never against
            # the surrounding context. «الذكاء الاصطناعي» can occur all through a
            # lesson, so a context-window match would silently accept every
            # future trail-off that happened to have it nearby -- which is the
            # "relaxed the detector" failure rule 63 is about.
            match = (next((e for g, e in acc_norm if g and g == run), None)
                     if run is not None else None)
            if match:
                r.note(f"accepted restart-shape at {cur['out']:.2f}s "
                       f"(\"{match['phrase']}\") - {match['reason']}")
                continue
            r.fail(f"possible trail-off/restart at output {cur['out']:.2f}s "
                   f"({gap:.2f}s pause) - {why}\n"
                   f"        before: ...{ctx_b}\n"
                   f"        after : {ctx_a}...")

    # (c) n-gram repeats surviving in the kept sequence (the phrase-boundary
    #     retake that a phrase-by-phrase read misses)
    #     Window is n-dependent on purpose. A real retake sits almost on top of
    #     itself -- the two confirmed cases (the "بالإنجليزي" mispronunciation and
    #     the "هالبرام--" truncation) were 3 and 4 words apart. A wide window on
    #     short n-grams instead flags ordinary topical repetition ("مع الذكاء
    #     الاصطناعي" twice in a lesson about AI), and a check that cries wolf
    #     gets ignored, which is how a real one slips through.
    seq = [norm((w.get("text") or "")) for w in kept]
    WINDOW = {3: 8, 4: 15, 5: 25, 6: 40}
    hits = []
    for n in (6, 5, 4, 3):
        seen: dict[tuple, int] = {}
        for i in range(len(seq) - n + 1):
            g = tuple(seq[i:i + n])
            if "" in g or len(set(g)) < max(2, n - 2):
                continue
            if g in seen and i - seen[g] <= WINDOW[n]:
                a, b = seen[g], i
                if not any(abs(a - x) < 8 for x, _, _ in hits):
                    hits.append((a, b, n))
            seen[g] = i
    # Verified-deliberate repetitions are recorded per project rather than
    # silently loosening the detector. A green gate has to mean "nothing left
    # to look at", so every accepted hit carries a written reason.

    flagged = 0
    for a, b, n in hits[:25]:
        txt = " ".join((kept[i].get("text") or "") for i in range(a, min(a + n, len(kept))))
        gram = [norm(x) for x in txt.split()]
        # At least two words must match: a one-word phrase (or a truncation
        # accept that normalises to one word) used to accept any repeat that
        # merely started with it.
        match = next((e for g, e in acc_norm
                      if len(g) >= 2 and (g == gram[:len(g)] or gram == g[:len(gram)])), None)
        if match:
            r.note(f"accepted repetition \"{txt.strip()}\" at {kept[a]['out']:.2f}s "
                   f"- {match['reason']}")
            continue
        flagged += 1
        r.fail(f"possible surviving repeat ({n}-gram, {b - a} words apart) at output "
               f"{kept[a]['out']:.2f}s and {kept[b]['out']:.2f}s: \"{txt}\"")
    if not flagged:
        r.note(f"n-gram repeat scan clean ({len(hits)} candidate(s), all verified deliberate)")
    return r


# --------------------------------------------------------- 2. caption pass

def parse_ass(ass: Path) -> tuple[list[dict], dict]:
    style: dict = {}
    cues: list[dict] = []
    for ln_no, line in enumerate(ass.read_text(encoding="utf-8").splitlines(), 1):
        if line.startswith("PlayResX:"):
            style["w"] = int(line.split(":")[1])
        elif line.startswith("PlayResY:"):
            style["h"] = int(line.split(":")[1])
        elif line.startswith("Style: "):
            f = line[len("Style: "):].split(",")
            style["name"] = f[0]
            style["font"] = f[1]
            style["size"] = float(f[2])
            style["outline"] = float(f[16])
            style["shadow"] = float(f[17])
            style["marginL"] = int(f[19])
            style["marginR"] = int(f[20])
            style["marginV"] = int(f[21])
        elif line.startswith("Dialogue:"):
            body = line[len("Dialogue:"):].split(",", 9)
            # Rule 155: an ASS Dialogue line has 9 header fields then the text.
            # A hand-edited .ass can lose fields (splitting on the ",," that
            # occurs at «Cap,,0» inside the header drops MarginL/R/V+Effect), and
            # libass then silently renders NOTHING. This used to raise IndexError
            # on body[9], which the runner reported as "pass crashed" -- reading
            # like a broken tool rather than a broken file, on the one check that
            # stands between us and shipping a caption-less render (rule 80).
            # A parser that cannot read its input HAS found a defect in the input.
            if len(body) != 10:
                raise ValueError(
                    f"master.ass line {ln_no} has {len(body)} fields, expected 10 "
                    f"(Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text). "
                    f"libass will render NOTHING for it. Line: {line[:80]!r}")
            def ts(x: str) -> float:
                h, m, s = x.strip().split(":")
                return int(h) * 3600 + int(m) * 60 + float(s)
            cues.append({"start": ts(body[1]), "end": ts(body[2]), "text": body[9]})
    return cues, style


def pass_captions(edit_dir: Path, video: Path) -> Result:
    r = Result("2 captions (data)")
    ass = edit_dir / "master.ass"
    if not ass.exists():
        r.fail("master.ass missing")
        return r
    cues, style = parse_ass(ass)
    r.note(f"{len(cues)} cues, {style.get('font')} {style.get('size')}pt @ "
           f"{style.get('w')}x{style.get('h')}, MarginV {style.get('marginV')}, "
           f"Outline {style.get('outline')}, Shadow {style.get('shadow')}")

    dur = float(probe(video)["format"]["duration"])

    # (a0) is the caption timeline on the DELIVERED grid? (rule 136)
    #
    # render.py extracts each range with `-t <dur> -r <fps>` and ffmpeg emits
    # ceil(dur*fps) frames, so a rendered segment is up to one frame LONGER than
    # its EDL range while its audio stays exact. The concat lays the file out on
    # the VIDEO timeline, so captions built on raw EDL offsets run progressively
    # early: over a second by the seventeen-minute mark on one lesson, and nearly
    # 3s on another lesson with about 200 ranges.
    # The operator heard it before any check did, twice.
    #
    # build_captions.py stamps the offset total it ACTUALLY accumulated into the
    # .ass header; this recomputes the same number from the EDL and compares.
    # The stamp is a byproduct of the real computation, so a builder that applied
    # raw offsets stamps the raw total and is caught, as is a stale .ass (no
    # stamp at all) and an OUTPUT_FPS that disagrees with the render.
    #
    # The FIRST version of this check compared the last cue's END against the
    # file total. That quantity depends on how much lesson runs after the final
    # word, not on the grid: it passed one lesson (0.06s of trailing content) and
    # failed two others (1.80s and 1.66s) with two good renders already on disk. A
    # check must measure the thing it is named after.
    try:
        _edl = load_edl(edit_dir)
        _pv = probe(video)["streams"][0]["r_frame_rate"].split("/")
        _fps = float(_pv[0]) / float(_pv[1])
        _q = sum(math.ceil(round((x["end"] - x["start"]) * _fps, 6)) / _fps
                 for x in _edl["ranges"])
        _txt = (edit_dir / "master.ass").read_text(encoding="utf-8", errors="replace")
        _m = re.search(r"^;\s*grid-offset-total:\s*([\d.]+)", _txt, re.M)
        _mf = re.search(r"^;\s*grid-fps:\s*([\d.]+)", _txt, re.M)
        if not _m:
            r.fail("master.ass carries no 'grid-offset-total' stamp, so it was built by a "
                   "build_captions.py from before the frame-grid fix. Its cues sit on the raw EDL grid "
                   "and run progressively early. Rebuild it.")
        else:
            _stamped = float(_m.group(1))
            _sf = float(_mf.group(1)) if _mf else _fps
            if abs(_sf - _fps) > 0.01:
                r.fail(f"captions were built for {_sf:g}fps but the render is {_fps:g}fps; "
                       f"the caption grid cannot match. Rebuild with OUTPUT_FPS={_fps:g}.")
            elif abs(_stamped - _q) > 1.5 / _fps:
                _raw = sum(x["end"] - x["start"] for x in _edl["ranges"])
                r.fail(f"caption grid mismatch: master.ass accumulated {_stamped:.3f}s but the "
                       f"render delivers {_q:.3f}s over {len(_edl['ranges'])} ranges at {_fps:g}fps "
                       f"(raw EDL total {_raw:.3f}s). Captions run up to "
                       f"{(_q - _stamped) * 1000:.0f}ms early. Rebuild master.ass.")
            else:
                r.note(f"caption grid OK: master.ass accumulated {_stamped:.3f}s, EDL quantised "
                       f"to {_q:.3f}s at {_fps:g}fps over {len(_edl['ranges'])} ranges "
                       f"(raw total would have been "
                       f"{sum(x['end'] - x['start'] for x in _edl['ranges']):.3f}s)")
    except Exception as _e:                     # a check that cannot run is not a pass
        r.fail(f"caption-grid check could not run: {_e!r}")

    # (a) artifacts that must never render
    for c in cues:
        plain = c["text"].replace(RLE, "").replace(PDF, "").replace(r"\N", " ")
        if "--" in plain:
            r.fail(f"'--' artifact in cue at {c['start']:.2f}s: {plain!r}")
        for tok in plain.split():
            if len(tok) == 1 and re.fullmatch(rf"[{AR}]", tok) and tok != "و":
                r.fail(f"orphan single letter '{tok}' at {c['start']:.2f}s: {plain!r}")
        if plain.strip().endswith(("،", ",", ":", ";")):
            r.fail(f"trailing punctuation at {c['start']:.2f}s: {plain!r}")
        # rule 111: a CORRECTION that deletes a token strands its punctuation
        # («آآآ،» -> «،»), and the stranded mark is not trailing, so the test
        # above walks straight past it. It shows up as a mark-only token, and
        # when it lands first it renders at the visual right in RTL and reads
        # as a comma opening the sentence. Checked as a whole TOKEN, never by
        # character: «.claude» and «.md» begin with a mark and are filenames.
        for tok in plain.split():
            if re.fullmatch(r"[،,;:.!؟?…\-]+", tok):
                r.fail(f"stranded punctuation token '{tok}' at {c['start']:.2f}s: {plain!r}")

    # (b) RTL embedding exactly on the lines that carry RTL letters (bidi guard).
    #     A line with Arabic (or other right-to-left) letters and no RLE...PDF
    #     can resolve left-to-right and scramble its Arabic runs. The reverse is
    #     a defect too: a line with no RTL letters inside RLE...PDF renders a
    #     leading number or edge punctuation at the wrong end ("10 minutes
    #     later" shows as "minutes later 10"). An English test take passed this
    #     gate 6/6 with exactly that when every line was wrapped. The builder
    #     wraps the RTL lines and only those, so check both directions. The
    #     second is reported ONCE with a count: a master.ass built before this
    #     rule wraps every Latin line, and one "rebuild it" reads better than
    #     hundreds of copies of it.
    wrapped_ltr = []
    for c in cues:
        for seg in c["text"].split(r"\N"):
            if not seg.strip():
                continue
            rtl_here = has_rtl(seg)
            if rtl_here and not (seg.startswith(RLE) and seg.endswith(PDF)):
                r.fail(f"line missing RTL embedding at {c['start']:.2f}s: {seg!r}")
            elif not rtl_here and (RLE in seg or PDF in seg):
                wrapped_ltr.append(f"{c['start']:.2f}s {seg.replace(RLE, '').replace(PDF, '')!r}")
    if wrapped_ltr:
        r.fail(f"{len(wrapped_ltr)} line(s) with no right-to-left letters are wrapped in "
               f"RTL embedding, where a leading number or edge punctuation renders at "
               f"the wrong end (first: {'; '.join(wrapped_ltr[:3])}). This master.ass "
               f"predates RTL-only wrapping or was hand-edited: rebuild it "
               f"(lc build_captions).")

    # (c) timing sanity
    for i, c in enumerate(cues):
        if c["end"] <= c["start"]:
            r.fail(f"non-positive duration cue at {c['start']:.2f}s")
        if c["end"] > dur + 0.5:
            r.fail(f"cue at {c['start']:.2f}s runs past end of video ({dur:.2f}s)")
        if i + 1 < len(cues) and c["end"] > cues[i + 1]["start"] + 0.001:
            r.fail(f"cue overlap at {c['start']:.2f}s -> {cues[i + 1]['start']:.2f}s")

    # (d) more than 2 lines never allowed
    for c in cues:
        if len(c["text"].split(r"\N")) > 2:
            r.fail(f"{len(c['text'].split(chr(92) + 'N'))} lines at {c['start']:.2f}s (max 2)")

    if style.get("marginV", 0) < 40:
        r.fail(f"MarginV {style.get('marginV')} too low - captions at the frame edge")
    return r


# ----------------------------------------------- 3. caption PIXEL-width pass

def pass_caption_px(edit_dir: Path, video: Path) -> Result:
    """Render the .ass over black and measure REAL text extents in pixels.

    Character-count budgets are a proxy and proxies drift. This renders the
    actual subtitle track through libass -- the same path the delivery uses --
    and measures how close real glyphs come to the frame edge.
    """
    r = Result("3 captions (pixels)")
    ass = edit_dir / "master.ass"
    if not ass.exists():
        r.fail("master.ass missing")
        return r
    cues, style = parse_ass(ass)
    W = style.get("w", 1920)
    H = style.get("h", 1080)
    marginL, marginR = style.get("marginL", 110), style.get("marginR", 110)

    # one frame per cue, at the cue midpoint
    times = [(c["start"] + c["end"]) / 2 for c in cues]
    if not times:
        r.fail("no cues to measure")
        return r

    import lcenv                      # same directory; handles any path name
    escaped = lcenv.filter_safe_path(ass)
    worst_left, worst_right = W, 0
    worst_cue_l = worst_cue_r = None
    tall = 0

    with tempfile.TemporaryDirectory() as td:
        # batch: render black frames at the cue midpoints with subs burned in
        for idx, (t, c) in enumerate(zip(times, cues)):
            out = Path(td) / "c.png"
            subprocess.run(
                ["ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c=black:s={W}x{H}:d=0.1",
                 # setpts MUST come before ass: the ass filter renders whichever cue is
                 # live at the frame's CURRENT timestamp, so shifting PTS afterwards just
                 # relabels an already-rendered frame. With the old order every sample
                 # rendered whatever was on screen at t=0 -- and since the first cue of that
                 # lesson started at 0.08s, nothing rendered at all, xs.size was 0 for every
                 # cue, every measurement was skipped and the pass reported OK having measured nothing
                 # (the tell is a "text spans x=<W>..0" note, i.e. the untouched sentinels).
                 "-vf", f"setpts=PTS+{t}/TB,ass='{escaped}'",
                 "-frames:v", "1", "-update", "1", str(out)],
                check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            a = np.asarray(Image.open(out).convert("L"), dtype=np.int16)
            ys, xs = np.nonzero(a > 40)
            if xs.size == 0:
                continue
            l, rr = int(xs.min()), int(xs.max())
            top, bot = int(ys.min()), int(ys.max())
            if l < worst_left:
                worst_left, worst_cue_l = l, c
            if rr > worst_right:
                worst_right, worst_cue_r = rr, c
            if bot > H - 8:
                r.fail(f"caption touches bottom edge at {c['start']:.2f}s (y={bot})")
            if top < 8:
                r.fail(f"caption touches top edge at {c['start']:.2f}s (y={top})")

    r.note(f"measured {len(times)} cues; text spans x={worst_left}..{worst_right} "
           f"in a {W}px frame (margins L{marginL}/R{marginR})")

    SAFE = 24   # glyphs must not come within this many px of the frame edge
    if worst_left < SAFE:
        txt = worst_cue_l["text"] if worst_cue_l else ""
        r.fail(f"caption reaches x={worst_left} (< {SAFE}px from left edge) at "
               f"{worst_cue_l['start']:.2f}s: {txt!r}")
    if worst_right > W - SAFE:
        txt = worst_cue_r["text"] if worst_cue_r else ""
        r.fail(f"caption reaches x={worst_right} (< {SAFE}px from right edge) at "
               f"{worst_cue_r['start']:.2f}s: {txt!r}")

    # ---- are the captions actually IN THE DELIVERED PIXELS? ----
    # A real lesson once shipped a render with ZERO burned captions and this
    # gate passed it 6/6. Every caption pass until now read master.ass or
    # rendered it standalone; none looked at the delivered frames. The cause was
    # one EDL field (`"subtitles": None`), so the .ass was perfect and unused.
    # The operator found it by eye ("why is there no caption?"), which is exactly the
    # thing this gate exists to prevent.
    if cues and video.exists():
        # Probe the band the captions actually occupy: from the bottom margin up
        # through two lines of text, in canvas pixels. It used to be the bottom
        # 22% of the frame, which a portrait canvas's MarginV 420 sits above, so
        # every portrait render failed here with its captions plainly visible.
        _size = float(style.get("size", 60))
        _mv = int(style.get("marginV", 80))
        band_bot = min(H, H - _mv + int(0.6 * _size))
        band_top = max(0, H - _mv - int(2.8 * _size))
        band_h = max(80, band_bot - band_top)
        band_y = max(0, band_bot - band_h)
        probes = [c for c in cues if c["end"] - c["start"] > 0.8][:12]
        lit = 0
        for c in probes:
            t = (c["start"] + c["end"]) / 2.0
            raw = subprocess.run(
                ["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", str(video),
                 "-frames:v", "1", "-vf",
                 f"crop=iw:ih*{band_h}/{H}:0:ih*{band_y}/{H},format=gray",
                 "-f", "rawvideo", "-"], capture_output=True).stdout
            if not raw:
                continue            # counted below: no frame means no caption there
            a = np.frombuffer(raw, dtype=np.uint8)
            # burned house captions are near-white glyphs over a dark outline
            if float((a > 235).mean()) > 0.0015:
                lit += 1
        if probes:
            if lit == 0:
                r.fail(f"NO burned captions found in the video: sampled {len(probes)} "
                       f"cue mid-points and the caption band has no white glyphs at "
                       f"any of them. master.ass is fine; check the EDL's "
                       f"\"subtitles\" field is set to master.ass (None burns nothing)")
            elif lit < len(probes) * 0.5:
                r.fail(f"burned captions missing at {len(probes)-lit} of {len(probes)} "
                       f"sampled cue mid-points")
            else:
                r.note(f"burned captions confirmed in pixels at {lit}/{len(probes)} "
                       f"sampled cues")
    return r


# -------------------------------------------------------------- 4. video pass

def _edge_accept(edit_dir: Path, edge: str):
    """A written, dated ruling that a black bar on one edge ships as-is.
    Phrase must be exactly "black bar on <edge> edge"; anything else is ignored."""
    f = edit_dir / "qc-accept.json"
    if not f.exists():
        return None
    try:
        acc = json.loads(f.read_text())
    except Exception:
        return None
    want = f"black bar on {edge} edge"
    return next((a for a in acc if a.get("phrase", "").strip() == want), None)


def pass_video(edit_dir: Path, video: Path, n_frames: int = 40) -> Result:
    """The rendered frames themselves: corner object, black frames, freezes."""
    r = Result("4 video frames")
    _edge_noted: set[str] = set()
    info = probe(video)
    dur = float(info["format"]["duration"])
    st = info["streams"][0]
    W, H = st["width"], st["height"]
    r.note(f"{W}x{H}, {st['codec_name']}, {st['r_frame_rate']}, {dur:.1f}s, "
           f"{int(info['format']['size']) / 1e6:.0f}MB")

    # The corner-object check only makes sense where a crop was applied to
    # remove one. Tying it to the EDL's own `grade` keeps the check attached to
    # the reason it exists: no crop means nothing was being hidden, so a dark
    # patch at the right edge is just content. Running it unconditionally
    # failed two finished screen-recorded lessons 40/40 on their own dark app
    # windows, and no pixel heuristic can tell a dark UI panel from a black
    # flag -- only the edit's intent can.
    try:
        grade = str(load_edl(edit_dir).get("grade") or "")
    except Exception:
        grade = ""
    check_corner = "crop" in grade
    r.note("corner-object check: "
           + ("ON (this edit crops to hide one)" if check_corner
              else "OFF (no crop in the EDL, so nothing is being hidden)"))

    times = [dur * i / (n_frames - 1) for i in range(n_frames)]
    times = [min(t, dur - 0.2) for t in times]
    prev = None
    frozen = 0
    with tempfile.TemporaryDirectory() as td:
        for t in times:
            out = Path(td) / "f.png"
            subprocess.run(
                ["ffmpeg", "-y", "-ss", f"{t:.2f}", "-i", str(video), "-frames:v", "1",
                 "-update", "1", str(out)],
                check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            a = np.asarray(Image.open(out).convert("L"), dtype=np.int16)

            # (a) fully black / near-black frame
            if a.mean() < 8:
                r.fail(f"near-black frame at {t:.1f}s (mean luma {a.mean():.1f})")

            # (b) the top-right corner object must be gone.
            #
            # The naive version of this ("is the right edge dark in the top
            # band?") fires on every screen recording, because a screen capture
            # carries its own 1-2px dark line along the very top of the frame.
            # It failed all 40 sampled frames of two finished lessons that had
            # no corner object at all, and a check that cries wolf gets waved
            # through -- which is how the real one would eventually ship.
            #
            # Rule 53's discriminator, implemented: measure how much of the FULL
            # row width is dark. A capture edge spans essentially the whole row;
            # a physical object in the corner is a run anchored at the right
            # edge that stops well short of the left. Only the latter is a fail.
            EDGE_SPAN = 0.85          # >= this fraction of the row => capture edge
            OBJ_MIN_PX = 12           # ignore sub-visible specks
            for row in range(0, 320, 8) if check_corner else []:
                if int(a[row, W - 1]) >= 45:
                    continue          # right edge not dark on this row
                x = W - 1
                while x >= 0 and a[row, x] < 45:
                    x -= 1
                run = W - 1 - x
                if run / W >= EDGE_SPAN:
                    continue          # spans the frame: capture edge, not an object
                if run >= OBJ_MIN_PX:
                    r.fail(f"dark object in top-right corner at {t:.1f}s: "
                           f"{run}px run at row y={row} "
                           f"({run/W*100:.1f}% of width, so not a capture edge)")
                    break

            # (c) letterbox / pillarbox bars
            #
            # Accept path added 2026-09-01. A capture-area change mid-recording
            # can pad one edge with true black for part of a lesson, and that is
            # a fact about the FOOTAGE that no edit can undo: the operator's only
            # real choices are ship, reshoot, or crop the whole video. When he
            # rules "ship", the finding must stop being raised or the gate can
            # never go green and every later run drowns it out. Keyed per project
            # in qc-accept.json and per EDGE, so accepting a left bar on one
            # lesson neither accepts a top bar on the same lesson nor anything at
            # all on another. Same standard as every other accept here: a written,
            # dated reason, never a loosened threshold.
            if int(a[:, 0:4].max()) < 12:
                m = _edge_accept(edit_dir, "left")
                if m: _edge_noted.add("left")
                else: r.fail(f"black bar on left edge at {t:.1f}s")
            if int(a[0:4, :].max()) < 12:
                m = _edge_accept(edit_dir, "top")
                if m: _edge_noted.add("top")
                else: r.fail(f"black bar on top edge at {t:.1f}s")

            small = np.asarray(Image.open(out).convert("L").resize((64, 36)), dtype=np.int16)
            if prev is not None and np.abs(small - prev).mean() < 0.35:
                frozen += 1
            prev = small

    for _e in sorted(_edge_noted):
        _m = _edge_accept(edit_dir, _e)
        r.note(f"black bar on {_e} edge ACCEPTED - {_m.get('reason','')}")
    if frozen > 2:
        r.note(f"{frozen} near-identical consecutive samples - expected for a "
               f"static talking-head shot, not treated as a defect")
    return r


def frozen_check(video: Path, start: float, dur: float,
                 inset: tuple[int, int, int, int] | None = (0, 264, 88, 360)
                 ) -> tuple[int, int] | None:
    """How much of a silent stretch is the picture actually moving?

    Returns (seconds_the_screen_moved, seconds_measured) -- NOT a single score.

    Rule 54 asked "is the screen frozen?" and answered it with a block-max over
    the whole window. The operator caught the consequence on a real lesson: a 14s window
    where the screen was static for 12 seconds and flickered twice for about a
    second scored 153 and was kept whole, so the delivered lesson sat on a dead
    home screen for fourteen seconds. A single transition anywhere in a window
    does not justify keeping the window -- so measure SECOND BY SECOND and report
    the fraction that actually moved (rule 72).

    Two confounds this also has to dodge (rule 66):
      * the webcam inset -- the presenter's face never stops moving, so any
        whole-frame measure reports motion forever. `inset` blanks it (default
        is the bottom-left circle used on these screen recordings; pass None for
        footage without one).
      * the mouse cursor -- on a 640x360 downscale a pointer fills most of an
        8x8 block, so block-MAX reads a drifting cursor as activity. Counting how
        many blocks moved separates it: a cursor lights 1-3, real UI activity
        (spinner, streaming text, a window opening) lights 40-900.
    """
    n = max(2, int(dur) + 1)
    times = [start + i for i in range(n)]
    frames = []
    with tempfile.TemporaryDirectory() as td:
        for t in times:
            o = Path(td) / "s.png"
            rc = subprocess.run(
                ["ffmpeg", "-y", "-ss", f"{t:.2f}", "-i", str(video), "-frames:v", "1",
                 "-vf", "scale=640:360", "-update", "1", str(o)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            ).returncode
            if rc != 0 or not o.exists():
                continue
            frames.append(np.asarray(Image.open(o).convert("L"), dtype=np.float64))
    if len(frames) < 2:
        return None

    mask = np.ones((45, 80), dtype=bool)
    if inset:
        x0, y0, x1, y1 = inset
        mask[y0 // 8:y1 // 8, x0 // 8:x1 // 8] = False

    live = 0
    for a, b in zip(frames, frames[1:]):
        blocks = np.abs(a - b)[:360, :640].reshape(45, 8, 80, 8).mean(axis=(1, 3))
        if int((blocks[mask] > 8).sum()) > 4:
            live += 1
    return live, len(frames) - 1


# -------------------------------------------------------------- 5. audio pass

def pass_audio(edit_dir: Path, video: Path) -> Result:
    r = Result("5 audio")
    edl = load_edl(edit_dir)

    # (a) loudness in the social target band
    p = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(video),
         "-af", "loudnorm=I=-14:TP=-1:LRA=11:print_format=json", "-vn", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    m = re.search(r"\{[^{}]*input_i[^{}]*\}", p.stderr, re.S)
    if m:
        d = json.loads(m.group(0))
        i, tp = float(d["input_i"]), float(d["input_tp"])
        r.note(f"integrated {i:.2f} LUFS, true peak {tp:.2f} dBTP")
        if not (-16.5 <= i <= -11.5):
            r.fail(f"loudness {i:.2f} LUFS outside the -14 +/- 2.5 delivery band")
        if tp > 0.5:
            r.fail(f"true peak {tp:.2f} dBTP is clipping")
    else:
        r.fail("could not measure loudness")

    # (b) residual long silences in the DELIVERED file
    #
    # Floor is 2.0s, not the original 4.0s. The operator found dead stretches of 3.4s
    # and 2.2s by watching, after two rounds of "fixed" renders -- anything the
    # gate does not look at is something he has to find, which is the whole point
    # of the gate (rule 73). The per-second classifier below is what makes a low
    # floor affordable: a 2s pause with the screen working is kept and reported,
    # not failed, so dropping the floor adds coverage without adding noise.
    SILENCE_FLOOR = 2.0
    p2 = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(video),
         "-af", f"silencedetect=noise=-40dB:d={SILENCE_FLOOR}", "-vn", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    sils = re.findall(r"silence_start: ([\d.]+)[\s\S]*?silence_duration: ([\d.]+)", p2.stderr)
    long_sils = [(float(a), float(b)) for a, b in sils if float(b) >= SILENCE_FLOOR]
    if not long_sils:
        r.note(f"no silence >= {SILENCE_FLOOR}s remains in the delivered audio")
    else:
        # Silence is only a defect if the PICTURE is also dead. On a screen
        # recording, watching the AI work IS the content, and those stretches
        # are legitimately wordless -- rule 54. Judging by duration alone failed
        # two finished lessons on demonstration footage, so decide it visually.
        #
        # A global mean frame delta is the wrong instrument: a spinner or a
        # populating file list barely moves it. Counting CHANGED BLOCKS does,
        # because the change is real but localised -- and unlike a block max it
        # is not fooled by a drifting mouse cursor (rule 66).
        #
        # Measured per second, and a window has to be mostly alive to be kept:
        # The operator caught a 14s window that was static for 12s but flickered
        # twice, which the old max-over-window test scored 153 and kept whole
        # (rule 72). Two thirds dead is dead.
        for s, d in long_sils:          # every one: dead air past #20 used to pass unjudged
            moved = frozen_check(video, s, d)
            if moved is None:
                r.fail(f"{d:.1f}s of silence at {s:.1f}s - could not sample the picture")
                continue
            live, total = moved
            if total == 0:
                r.fail(f"{d:.1f}s of silence at {s:.1f}s - could not sample the picture")
            elif live <= total / 3:
                r.fail(f"{d:.1f}s of silence at {s:.1f}s and the screen moved in only "
                       f"{live}/{total}s - {total - live}s of real dead air, cut it")
            else:
                r.note(f"{d:.1f}s wordless at {s:.1f}s but the screen moved in "
                       f"{live}/{total}s - demonstration, kept")

    # (c) audio and video durations agree
    ap = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0",
         "-show_entries", "stream=duration", "-of", "csv=p=0", str(video)],
        capture_output=True, text=True,
    )
    try:
        adur = float(ap.stdout.strip())
        vdur = video_stream_duration(video)
        if abs(adur - vdur) > 0.5:
            r.fail(f"audio ({adur:.2f}s) and video ({vdur:.2f}s) durations disagree")
        else:
            r.note(f"audio/video durations agree ({adur:.2f}s)")
    except ValueError:
        r.fail("could not read audio duration")

    # (d) A/V SYNC: both streams must start at the same instant.
    # The concat demuxer returns a base whose video starts ~0.021-0.040s late
    # (AAC priming at the segment joins) while audio starts at 0, so the picture
    # lags the voice for the whole runtime. The operator caught this by eye on a
    # delivered lesson -- "the voice is coming a little bit faster than my mouth
    # movement" -- which is exactly the asymmetry to expect: audio leading video
    # is far more detectable to a viewer than the reverse. render.py now
    # normalises it, and this pass makes sure a file that predates that fix, or
    # any future regression, cannot ship silently.
    st = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,start_time",
         "-of", "json", str(video)],
        capture_output=True, text=True,
    )
    try:
        starts = {s["codec_type"]: float(s.get("start_time", 0.0))
                  for s in json.loads(st.stdout)["streams"]}
        # A LATER video start means the picture is held back relative to the
        # sound, i.e. the audio LEADS. Getting this sign backwards made the
        # check pass a file that was already known-bad, so state it explicitly:
        lead_ms = (starts.get("video", 0.0) - starts.get("audio", 0.0)) * 1000.0
        # ITU-R BT.1359: audio ahead of picture is objectionable from ~22ms,
        # behind it only from ~45ms. Hold to the tighter side.
        if lead_ms > 20.0:
            r.fail(f"audio leads video by {lead_ms:.0f}ms (video starts at "
                   f"{starts.get('video', 0):.3f}s, audio at {starts.get('audio', 0):.3f}s) "
                   f"- lip sync reads as early; re-render with the patched render.py")
        elif lead_ms < -45.0:
            r.fail(f"audio trails video by {-lead_ms:.0f}ms - re-render")
        else:
            r.note(f"A/V sync: audio leads by {lead_ms:+.0f}ms (within tolerance)")
    except Exception as exc:
        r.fail(f"could not verify A/V sync: {exc}")
    return r


# --------------------------------------------------------------- 6. spec pass

def pass_spec(edit_dir: Path, video: Path) -> Result:
    r = Result("6 spec + integrity")
    edl = load_edl(edit_dir)
    info = probe(video)
    st = info["streams"][0]
    W, H = st["width"], st["height"]
    dur = video_stream_duration(video)          # the picture, not the longest stream
    expect = float(edl.get("total_duration_s", 0))

    r.note(f"delivered {W}x{H} @ {st['r_frame_rate']}, {dur:.2f}s "
           f"(EDL expects {expect:.2f}s)")

    # Every segment is extracted to whole frames, so each one can round by up to
    # 1/fps and a long edit accumulates that. A long lesson can reach 200 ranges at
    # 30fps: up to 6.7s of legitimate drift against a flat 1.5s tolerance. Scale the
    # tolerance with the segment count rather than widening it blindly, so a real
    # mismatch on a short edit still fails.
    fps_n = st.get("r_frame_rate", "30/1").split("/")
    fps = float(fps_n[0]) / float(fps_n[1] or 1) if len(fps_n) == 2 else 30.0
    tol = max(1.5, len(edl["ranges"]) / max(fps, 1.0))
    if abs(dur - expect) > tol:
        r.fail(f"duration {dur:.2f}s does not match EDL total {expect:.2f}s")

    # The grade must not have quietly downscaled below the source's own frame.
    # This is the guard that keeps a delivered course at native resolution, so
    # it must never be skippable. Source paths are resolved relative to the EDIT
    # DIR (what render.py does, and what the EDL author means) rather than the
    # process CWD -- a relative path like "../take1.mov" used to crash this pass
    # from any other directory, and a crash here means the resolution check did
    # not run at all. Every source is checked, not just the first: a multi-source
    # EDL mixing resolutions could otherwise pass or fail on source ordering.
    srcs = [(k, (edit_dir / v).resolve() if not Path(v).is_absolute() else Path(v))
            for k, v in edl["sources"].items()]
    missing = [(k, p) for k, p in srcs if not p.exists()]
    for k, p in missing:
        r.fail(f"source '{k}' not found at {p} - resolution guard could not run")
    for k, p in [s for s in srcs if s[1].exists()]:
        sp = probe(p)["streams"][0]
        sw, sh = sp["width"], sp["height"]
        r.note(f"source '{k}' is {sw}x{sh}")
        if W < sw or H < sh:
            r.fail(f"OUTPUT {W}x{H} IS SMALLER THAN SOURCE '{k}' {sw}x{sh} - resolution was cut")

    # full decode: catches truncation, a missing moov, corrupt tail
    p = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(video), "-f", "null", "-"],
        capture_output=True, text=True,
    )
    errs = [l for l in p.stderr.splitlines() if l.strip()]
    if errs:
        for e in errs[:8]:
            r.fail(f"decode error: {e}")
    else:
        r.note("full decode clean end-to-end (no corrupt or truncated frames)")
    return r


PASSES = {
    "transcript": pass_transcript,
    "captions": pass_captions,
    "caption-px": pass_caption_px,
    "video": pass_video,
    "audio": pass_audio,
    "spec": pass_spec,
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("which", choices=["all", *PASSES])
    ap.add_argument("--edit-dir", type=Path, required=True)
    ap.add_argument("--video", type=Path, required=True)
    a = ap.parse_args()

    if not a.video.exists():
        sys.exit(f"video not found: {a.video}")

    names = list(PASSES) if a.which == "all" else [a.which]
    failed = 0
    for n in names:
        try:
            res = PASSES[n](a.edit_dir.resolve(), a.video.resolve())
        except Exception as exc:  # a crashing pass is a failing pass
            res = Result(n)
            res.fail(f"pass crashed: {type(exc).__name__}: {exc}")
        if not res.report():
            failed += 1

    print(f"\n{'=' * 72}")
    print(f"{len(names) - failed}/{len(names)} passes OK"
          f"{'  -- READY' if not failed else '  -- NOT READY'}")
    print("=" * 72)
    sys.exit(failed)


if __name__ == "__main__":
    main()
