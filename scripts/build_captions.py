#!/usr/bin/env python3
"""Build master.ass: native-resolution captions for this project.

Style comes from the project's project.json ("captions"), with the proven
landscape-course values as defaults (tuned for Arabic); per-take vocabulary
(CORRECTIONS, NO_SPLIT) comes from the project's captions_project.py. The operator's rule
behind the defaults: caption style must match across every video, so a project
changes its canvas, never the constants. ASS rather than SRT because libass
renders at the declared canvas and scales it to the real frame. A caption line
that contains right-to-left letters is wrapped in a right-to-left embedding; a
line without any (an English take, a Latin line in an Arabic one) is not.

Usage: lc build_captions .       (from the project or its edit/ dir)
"""
import json
import re
import sys
import unicodedata
from pathlib import Path

import lcenv

# Every style constant below is the LITERAL proven value for a landscape course
# lesson, and stays the default. A project overrides any of them in its own
# `project.json` under "captions", which is how one plugin serves a 2560x1440
# course canvas and a 1080x1920 Reel canvas without either set of numbers being
# rescaled per project. The two are not convertible: FontSize is a fraction of
# the AUTHORING canvas, and MarginV was calibrated against a specific frame.
_EDIT = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else lcenv.edit_dir(__file__)
_ALL = lcenv.project_config(_EDIT)
_CFG = _ALL.get("captions", {})


def _c(key, default):
    return _CFG.get(key, default)


FONT = _c("font", "Almarai ExtraBold")
FONT_SIZE = _c("font_size", 72)
OUTLINE = _c("outline", 4.4)
SHADOW = _c("shadow", 0.4)            # the operator, 2026-08-11: "a slight shadow, a very small one" (was 1.2)
MARGIN_V = _c("margin_v", 80)            # the operator, 2026-08-11: 420 read as "way in the middle" on this
                          # landscape/1440-tall frame; that value was the portrait-Reels
                          # bottom-UI clearance figure, not a resolution-independent constant.
                          # 80px keeps captions genuinely near the bottom edge here.
MARGIN_H = _c("margin_h", 110)
# AUTHORING canvas, deliberately NOT the render resolution.
# libass scales an ASS from PlayRes up to the actual frame, so PlayRes is what
# fixes the caption's APPARENT size. Authoring at the render's own 3840x2160
# with the literal FontSize 66 gives 3.06% of frame height, against 4.58% in
# an earlier lesson of the same course (same presenter, same genre), so the two
# would sit side by side in the course with visibly different captions.
# Rule 38 is explicit that this is unacceptable. Authoring at 1440 and letting
# libass scale 1.5x keeps every style constant literal (rule 42) AND lands the
# same on-screen proportion as that earlier lesson.
PLAY_W, PLAY_H = _c("play_w", 2560), _c("play_h", 1440)

# Character cap is a first-pass heuristic only (qc.py caption-px is the real
# gate). It is not a style constant: at a FIXED 66pt glyph size the usable
# width is PLAY_W - 2*MARGIN_H, so a wider frame simply fits more characters
# on the same-sized line. 25 chars was calibrated at 2560px
# (usable 2340px) -> 25 * (3840-220)/(2560-220) = 38.7 -> 38 here.
MAX_CHARS_PER_LINE = _c("max_chars_per_line", 23)
MAX_LINES = _c("max_lines", 2)
MAX_CHARS_TOTAL = MAX_CHARS_PER_LINE * MAX_LINES
GAP_BREAK = 0.55
MIN_CUE = 0.55
# rule 71/77 (2026-08-17, second-reviewer pass): Scribe extends a word's START back
# across silence, so one token can be tens of seconds long. One lesson carried a
# 48.66s `سؤال`, which this builder faithfully turned into a 51.8s cue sitting
# frozen on screen. The END lands on the real utterance, so trust it and pull
# the start forward; cap the finished cue as a second, independent backstop.
# The DELIVERED timeline is not the EDL timeline (2026-08-29, ledger rule 136).
#
# render.py extracts each range with `-t <dur> -r 30`, and ffmpeg emits
# ceil(dur * fps) frames, so a rendered segment is up to one frame LONGER than
# the range it came from (measured mean about +14 ms per segment; a range whose
# duration is already a whole number of frames is exact). The segment's AUDIO is
# exact, but the concat demuxer lays the file out on the VIDEO timeline, so every
# join pushes the content a little later than the EDL predicts. Captions placed
# on raw EDL offsets therefore run progressively EARLY: measured on one lesson
# at about -0.2 s after a minute and a half and about -1.1 s after seventeen
# minutes, a straight line (r = -0.99).
#
# The operator caught it by ear: "I feel like the caption is faster than my voice."
# The same symptom in his words appears in render.py's own A/V-sync comment,
# where it was diagnosed as a constant start offset and closed with
# "constant, NOT accumulating (identical at 2 and 6 segments)". At 6 segments the
# accumulation is under a tenth of a second, which is indistinguishable from a
# constant. At 80 segments it passes a second, and at 200 it nears three.
#
# So accumulate what the RENDERER will actually produce, not what the EDL says.
# MUST match the --fps the render is invoked with; a mismatch here silently
# re-creates the drift it exists to remove.
OUTPUT_FPS = float(_ALL.get("render", {}).get("fps", 30.0))


def quantised(dur: float) -> float:
    """The on-screen duration ffmpeg gives a segment of `dur` at OUTPUT_FPS.

    round() before ceil() is load-bearing (rule 84): 71.700 * 30 evaluates to
    2151.0000000000002, and a bare ceil turns that into a whole extra frame.
    """
    import math
    return math.ceil(round(dur * OUTPUT_FPS, 6)) / OUTPUT_FPS


MAX_WORD_S = 1.0
MAX_CUE_S = 7.0
SENTENCE_END = set(".!؟?…")

# ASR fixes: the recogniser heard these wrong and the spoken audio is correct.
# They are per project, so they live in the project's own `captions_project.py`,
# loaded below. Two rules govern every entry:
#
#   * The SCREEN is the ground truth for a Latin token, never the ear. An ASR
#     renders an unfamiliar product or UI word as the nearest common English
#     word, and both readings sound right on replay. Grab the frame at the
#     token's timestamp and read the UI. This is how "the pro cover" became
#     "the pilot cover" and "either gap" became "neither gap".
#   * A correction that DELETES a token must clean up after itself, or it
#     strands the punctuation that the trailing-strip never sees.
CORRECTIONS = []


# Phrases that must stay inside one cue. Per project; see captions_project.py.
NO_SPLIT = []

STOPWORDS = {"في", "من", "على", "مع", "أو", "و", "هذا", "هذي", "هذه", "اللي", "أنت",
             "أنا", "يعني", "بس", "شي", "إن", "ما", "لا", "هو", "هي", "كل", "عن",
             "إذا", "لك", "له", "بعد", "قبل", "أن", "التي", "الذي"}

# A project supplies its own vocabulary in `captions_project.py`, beside
# `cutlist.py`: CORRECTIONS, NO_SPLIT, and STOPWORDS when the language differs.
# No file means "no corrections", which is the correct starting state for a take
# nobody has read yet.
_proj = _EDIT / "captions_project.py"
if _proj.exists():
    _ns: dict = {}
    exec(compile(_proj.read_text(), str(_proj), "exec"), _ns)
    CORRECTIONS = _ns.get("CORRECTIONS", CORRECTIONS)
    NO_SPLIT = _ns.get("NO_SPLIT", NO_SPLIT)
    STOPWORDS = _ns.get("STOPWORDS", STOPWORDS)


def norm(w: str) -> str:
    w = re.sub(r"[ً-ْـ]", "", w)          # harakat + tatweel
    w = w.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا").replace("ى", "ي").replace("ة", "ه")
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
    # Audited 2026-08-29 across every norm() in the toolchain.
    #
    # analyze.py is the repeat scanner used to AUTHOR the cut list, so this copy
    # of the bug was hiding repeats before a single cut was written.
    # build_captions.py uses norm() for NO_SPLIT matching and for the
    # caption/overlay dedup (rules 13 and 21), so a phrase followed by an Arabic
    # comma silently failed to match either.
    return re.sub(r"[^\w]", "", w).casefold()


def ass_ts(t: float) -> str:
    cs = int(round(t * 100))
    h, rem = divmod(cs, 360000)
    m, rem = divmod(rem, 6000)
    s, cs = divmod(rem, 100)
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"


# An Arabic definite article or preposition PREFIX carries no meaning on its own:
# «الـ», «بالـ», «للـ», «لـ», «بـ», «كـ» and bare «ال»/«و» exist only to attach to
# the next word. Breaking the line between one and its noun orphans it at the end
# of line 1, and in an RTL caption that reads as a dangling fragment -- «الهدف
# منها إنه الـ» / «graphic designer». It is rule 18's particle-aware break, which
# was written for TITLES and never applied to captions; one lesson shipped 15 of
# these in its first build. English nouns in Arabic speech make it common,
# because Scribe writes the Arabic article as its own token in front of an
# English word.
PREFIX_NO_BREAK = ("الـ", "بالـ", "للـ", "بـ", "لـ", "كـ", "وـ", "فـ", "ال", "و")


def _fix_prefix_breaks(lines):
    """Pull a dangling article down to the line its noun is on."""
    out = list(lines)
    for i in range(len(out) - 1):
        w = out[i].split()
        if w and w[-1] in PREFIX_NO_BREAK:
            out[i] = " ".join(w[:-1]).strip()
            out[i + 1] = (w[-1] + " " + out[i + 1]).strip()
    return [l for l in out if l]


# The mirror of the rule above, at the other end of the cue. A last line holding
# ONE short word -- «له», «أو», «the» -- reads as a dropped fragment rather than a
# line, because the eye finishes line 1 and finds a stub under it. Measured across
# two lessons: 18 of 401 two-line cues, of which the genuinely bad ones
# are the single particles. Pull one word down so line 2 is never alone.
# Rule 147 (2026-08-31). This runs AFTER _fix_prefix_breaks, which can itself
# create the case by moving an article down onto a line of its own.
ORPHAN_MAX_CHARS = 4


def _fix_orphan_tail(lines):
    """Never leave the final line holding a single short word."""
    if len(lines) < 2:
        return lines
    out = list(lines)
    tail = out[-1].split()
    prev = out[-2].split()
    if len(tail) == 1 and len(tail[0]) <= ORPHAN_MAX_CHARS and len(prev) >= 3:
        moved = f"{prev[-1]} {out[-1]}".strip()
        if len(moved) <= MAX_CHARS_PER_LINE:
            out[-2] = " ".join(prev[:-1]).strip()
            out[-1] = moved
    return [l for l in out if l]


_GLUE = "\x00"   # holds a NO_SPLIT phrase together through the line wrap


def wrap(text: str) -> str:
    # NO_SPLIT used to guard only the CUE break, so a protected phrase could
    # still be split across the two LINES of one cue («22 / أكتوبر»).
    for ph in NO_SPLIT:
        if " " in ph and ph in text:
            text = text.replace(ph, ph.replace(" ", _GLUE))
    words = text.split()
    lines, cur = [], ""
    for w in words:
        cand = f"{cur} {w}".strip()
        if len(cand) <= MAX_CHARS_PER_LINE or not cur:
            cur = cand
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    if len(lines) > MAX_LINES:                            # rebalance into MAX_LINES
        per = max(1, len(text) // MAX_LINES)
        lines, cur = [], ""
        for w in words:
            cand = f"{cur} {w}".strip()
            if len(cand) <= per or not cur or len(lines) == MAX_LINES - 1:
                cur = cand
            else:
                lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)
    lines = _fix_prefix_breaks(lines)
    lines = _fix_orphan_tail(lines)
    return r"\N".join(rtl(l.replace(_GLUE, " ")) for l in lines)


AR = r"ء-ي"

def clean(text: str) -> str:
    for a, b in CORRECTIONS:
        text = text.replace(a, b)
    # stutter artifacts: Scribe writes a false start as "ت-تجهز" / "م -مشروع"
    text = re.sub(rf"(?<![{AR}])[{AR}]\s*-\s*(?=[{AR}])", "", text)
    # cut-off word artifacts: Scribe marks a word the speaker visibly abandoned
    # mid-utterance with a trailing "--" (e.g. "فواتير--", "هالبرام--") or a
    # single trailing "-" (e.g. "زاو-", "اص-", "بال-"). If one of these survives
    # into a cue, it means a cut boundary should have excluded it as a false
    # start. This is a safety net, not the primary fix. Drop the whole token
    # rather than show a broken half-word with a trailing dash.
    #
    # A dash INSIDE an Arabic token is the same artifact with the completed
    # word attached ("ال-الجهاز", "نجت-نتجنب", "مـ-ملف"): keep only the part
    # after the last dash. Latin tokens are left alone (hyphens are real there).
    def _dedash(w: str) -> str:
        core = w.rstrip("،,;:.!؟?…")
        tail = w[len(core):]
        if "-" not in core:
            return w
        if not re.search(rf"[{AR}]", core):     # Latin/number token: real hyphen
            return w
        if core.endswith("-"):                  # abandoned mid-word
            return ""
        return core.rsplit("-", 1)[-1] + tail
    text = " ".join(x for x in (_dedash(w) for w in text.split()) if x)
    # orphan single letters left stranded by a stutter (و is a real word)
    text = " ".join(w for w in text.split()
                    if not (len(w) == 1 and re.fullmatch(rf"[{AR}]", w) and w != "و"))
    # A CORRECTION that DELETES a token strands its punctuation: «آآآ،» becomes
    # «،», which is no longer trailing, so the strip below never reaches the
    # real comma behind it and the cue ships as «... في عنا،» (rule 110).
    # Drop any token that is nothing but marks. This also removes a stranded
    # mark sitting at the START of a cue, which renders at the visual right in
    # RTL and reads as a comma opening the sentence.
    # A leading mark is NOT stripped by character, deliberately: «.claude» and
    # «.md» begin with one and are filenames, not punctuation.
    text = " ".join(w for w in text.split()
                    if not re.fullmatch(r"[،,;:.!؟?…\-]+", w))
    text = re.sub(r"\s+([،,;:.!؟?…])", r"\1", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text.rstrip("،,;:.!؟?…").strip()


# A right-to-left LETTER: a letter (Unicode category L*) whose bidi class is R
# or AL, which covers Hebrew, Arabic, Syriac, Thaana, NKo and the other
# right-to-left scripts. Not a code-point range: the Arabic block also holds
# the Arabic comma (bidi class CS), Arabic-Indic digits (AN) and the Arabic
# question mark and semicolon (AL, but punctuation), and an all-Latin line
# that merely carries one of those is a left-to-right line. Wrapping one such
# line ("allow for this task" and an Arabic comma) put its comma at the left.
# qc.py holds the same test for its RTL check; change both together.
def has_rtl(s: str) -> bool:
    return any(unicodedata.bidirectional(ch) in ("R", "AL")
               and unicodedata.category(ch).startswith("L") for ch in s)


# Written as escapes on purpose: a literal bidi control in source is
# invisible, and it makes GitHub flag the file as possibly hiding code.
RLE, PDF = "\u202b", "\u202c"     # RIGHT-TO-LEFT EMBEDDING ... POP DIRECTIONAL FORMATTING


def rtl(line: str) -> str:
    """Force RTL base direction for a caption line that contains RTL letters.

    A line mixing Arabic with a Latin token (Claude, Wispr Flow, dictation)
    can have its base direction resolved as LTR, which reorders the Arabic
    runs and scrambles the sentence. RLE...PDF pins the line to RTL and lets
    the Latin run render LTR inside it, the correct bidi result.

    A line with no RTL letters (an English take, or an all-Latin line inside
    an Arabic one, even one carrying an Arabic comma or question mark) is left
    alone. Inside RLE a leading number and edge punctuation move to the wrong
    end: "10 minutes later" renders as "minutes later 10", and "the key," as
    ",the key".
    """
    if not has_rtl(line):
        return line
    return RLE + line + PDF


def main() -> None:
    edit_dir = _EDIT
    edl = json.loads((edit_dir / "edl.json").read_text())
    tr_dir = edit_dir / "transcripts"

    transcripts = {}
    for key, src in edl["sources"].items():
        stem = Path(src).stem
        # Prefer the MEASURED audible extents (measure_tokens.py). The old
        # MAX_WORD_S clamp assumed Scribe pads a token's START; on the take where
        # this was measured, Scribe padded the END on over a hundred words and the
        # start on only two, so the clamp left cues sitting on screen for up to 2.3s
        # after the last sound -- and made the cut defer to the token end, which is
        # dead air the operator heard on playback. Measure, do not guess a direction.
        meas = tr_dir / f"{stem}.audible.json"
        if meas.exists():
            transcripts[key] = json.loads(meas.read_text())
            continue
        p = tr_dir / f"{stem}.json"
        if p.exists():
            transcripts[key] = [
                w for w in json.loads(p.read_text()).get("words", [])
                if w.get("type") == "word" and w.get("start") is not None
            ]
            for w in transcripts[key]:                      # fallback: rule 71/77
                if w["end"] - w["start"] > MAX_WORD_S:
                    w["start"] = w["end"] - MAX_WORD_S

    # ---- group words into cues on the output timeline ----
    no_split_norm = [[norm(x) for x in p.split()] for p in NO_SPLIT]
    raw = []
    offset = 0.0
    for r in edl["ranges"]:
        seg_start, seg_end = float(r["start"]), float(r["end"])
        # assign each word to the range containing its END: the end is the
        # trustworthy timestamp, it puts every word in exactly one range, and
        # it keeps a clamped word whose original start preceded the range
        words = [w for w in transcripts.get(r["source"], [])
                 if seg_start < w["end"] <= seg_end]

        chunk = []
        for i, w in enumerate(words):
            chunk.append(w)
            txt = (w.get("text") or "").strip()
            nxt = words[i + 1] if i + 1 < len(words) else None
            gap = (nxt["start"] - w["end"]) if nxt else 99.0
            joined = " ".join((x.get("text") or "").strip() for x in chunk)

            # never break inside a protected phrase
            tail = [norm(x) for x in joined.split()]
            protect = False
            for ph in no_split_norm:
                for k in range(1, len(ph)):
                    if tail[-k:] == ph[:k]:
                        protect = True
                        break
                if protect:
                    break

            # An article was kept off a LINE end, but a CUE could still end on
            # one («بضغط على الـ» / «usage…» in the next cue). Never break a cue
            # right after an article prefix.
            if nxt is not None and txt in PREFIX_NO_BREAK:
                protect = True

            hard = bool(txt) and txt[-1] in SENTENCE_END
            full = len(joined) >= MAX_CHARS_TOTAL
            if not protect and (hard or full or gap >= GAP_BREAK):
                raw.append((chunk, seg_start, offset))
                chunk = []
        if chunk:
            raw.append((chunk, seg_start, offset))
        offset += quantised(seg_end - seg_start)   # rule 136, NOT seg_end - seg_start

    cues = []
    for chunk, seg_start, off in raw:
        a = max(0.0, chunk[0]["start"] - seg_start) + off
        b = max(0.0, chunk[-1]["end"] - seg_start) + off
        text = clean(" ".join((w.get("text") or "").strip() for w in chunk))
        if text:
            b = min(b, a + MAX_CUE_S)                   # rule 77
            cues.append([a, max(b, a + MIN_CUE), text])

    cues.sort(key=lambda c: c[0])
    for i in range(len(cues) - 1):                        # no overlaps
        if cues[i][1] > cues[i + 1][0]:
            cues[i][1] = cues[i + 1][0]

    # ---- suppress cues that duplicate an on-screen card (only with a cards manifest) ----
    manifest = edit_dir / "animations" / "slot_titles" / "cards_manifest.json"
    dropped = 0
    if manifest.exists():
        cards = json.loads(manifest.read_text())
        windows = []
        for c in cards:
            words = {norm(w) for w in
                     (c["vars"].get("title", "") + " " + c["vars"].get("sub", "")).split()}
            windows.append((c["start"], c["start"] + c["dur"],
                            {w for w in words if w and w not in STOPWORDS},
                            c["vars"].get("kind")))
        kept = []
        for a, b, text in cues:
            drop = False
            for ws, we, cwords, kind in windows:
                if a < we and b > ws:                     # temporal overlap
                    cue_words = {w for w in (norm(x) for x in text.split())
                                 if w and w not in STOPWORDS}
                    if not cue_words:
                        continue
                    shared = len(cue_words & cwords)
                    if kind == "lowerthird":
                        if shared >= 1:                   # identity card: any name echo
                            drop = True
                    elif shared >= 2 or shared / len(cue_words) >= 0.6:
                        drop = True
                if drop:
                    break
            if drop:
                dropped += 1
            else:
                kept.append([a, b, text])
        cues = kept

    # Stamp the offset total this build ACTUALLY accumulated (rule 136). qc.py
    # recomputes the same number independently from the EDL and fails on a
    # mismatch, which catches a stale .ass, a raw-grid build, and an OUTPUT_FPS
    # that disagrees with the render. It is a byproduct of the real computation,
    # not a restatement of intent: a builder that applied raw offsets stamps the
    # raw total and is caught.
    #
    # The first version of that gate check compared the LAST CUE'S END against
    # the file total instead. That quantity depends on how long the lesson runs
    # after its final word, not on the grid, so it passed one lesson (0.06s of
    # trailing content) and failed two others (1.80s and 1.66s) with two
    # perfectly good renders on disk. A check has to measure the thing it is
    # named after.
    header = f"""[Script Info]
Title: {edit_dir.parent.name} captions
; grid-offset-total: {offset:.6f}
; grid-fps: {OUTPUT_FPS:g}
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709
PlayResX: {PLAY_W}
PlayResY: {PLAY_H}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{FONT},{FONT_SIZE},&H00FFFFFF,&H00FFFFFF,&H00101010,&H80000000,0,0,0,0,100,100,0,0,1,{OUTLINE},{SHADOW},2,{MARGIN_H},{MARGIN_H},{MARGIN_V},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header]
    for a, b, text in cues:
        lines.append(f"Dialogue: 0,{ass_ts(a)},{ass_ts(b)},Cap,,0,0,0,,{wrap(text)}")
    (edit_dir / "master.ass").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"master.ass: {len(cues)} cues ({dropped} suppressed as duplicate of a card), "
          f"font={FONT} @ {PLAY_W}x{PLAY_H}")


if __name__ == "__main__":
    main()
