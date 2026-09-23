#!/usr/bin/env python3
"""Build docs/lesson-cut-guide.pdf from GUIDE.md.

GUIDE.md is the single source. This turns it into designed HTML (a cover, a
linked contents page, long chapters starting a fresh page) and prints it through Chromium,
because Chromium shapes Arabic correctly (HarfBuzz) and Python PDF libraries do
not: the guide quotes Arabic words, and a reshaper-based PDF breaks them apart.

    python3 docs/build/build_pdf.py [--fonts DIR]

Needs: python `markdown`, node with `playwright-chromium` resolvable (set
NODE_PATH if it lives elsewhere), and, for the intended look, the Tajawal Arabic
font (SIL Open Font License 1.1, https://fonts.google.com/specimen/Tajawal).
No font ships with the repo. The font folder is --fonts DIR, else
$LESSON_CUT_PDF_FONTS, else docs/build/fonts/. Google Fonts file names
(Tajawal-Regular.ttf, Tajawal-Bold.ttf) and webfont-helper names
(tajawal-v12-arabic_latin-regular.ttf, ...-700.ttf) both match, in any letter
case. With no Tajawal there, the build says so and Arabic falls back to the
system's Arabic font. macOS only as written (system font paths).
"""
import argparse
import html
import os
import re
import subprocess
import sys
from pathlib import Path

import markdown

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SRC = ROOT / "GUIDE.md"
OUT_HTML = HERE / "guide.html"
OUT_PDF = ROOT / "docs" / "lesson-cut-guide.pdf"

DEFAULT_FONT_DIR = HERE / "fonts"
FONT_ENV = "LESSON_CUT_PDF_FONTS"


def font_dir(flag):
    """--fonts DIR, else $LESSON_CUT_PDF_FONTS, else docs/build/fonts."""
    chosen = flag or os.environ.get(FONT_ENV, "").strip()
    return Path(chosen).expanduser() if chosen else DEFAULT_FONT_DIR


def _tajawal(folder, weight):
    """The first Tajawal .ttf in `folder` whose name ends in one of `weight`'s
    spellings, ignoring letter case. The separator before the weight is what
    keeps "bold" from matching Tajawal-ExtraBold.ttf."""
    if not folder.is_dir():
        return None
    pat = re.compile(r"[-_ ](%s)$" % weight)
    for p in sorted(folder.iterdir()):
        stem = p.stem.lower()
        if p.suffix.lower() == ".ttf" and "tajawal" in stem and pat.search(stem):
            return p.resolve()
    return None


def arabic_font_face(folder):
    reg = _tajawal(folder, "regular|400")
    bold = _tajawal(folder, "bold|700")
    ranges = "U+0600-06FF, U+0750-077F, U+08A0-08FF, U+FB50-FDFF, U+FE70-FEFF, U+200C-200F"
    if not reg:
        print(f"note: no Tajawal regular .ttf in {folder} (pass --fonts DIR or set "
              f"{FONT_ENV}); Arabic falls back to the system font")
        return ""
    print(f"fonts: {reg.name}" + (f" + {bold.name}" if bold else "") + f" from {folder}")
    if not bold:
        print("note: no bold Tajawal found; bold Arabic will be synthesised from the regular")
    face = f"""@font-face {{ font-family: "LCArabic"; font-weight: 400;
  src: url("{reg.as_uri()}"); unicode-range: {ranges}; }}\n"""
    if bold:
        face += f"""@font-face {{ font-family: "LCArabic"; font-weight: 700;
  src: url("{bold.as_uri()}"); unicode-range: {ranges}; }}\n"""
    return face


CSS = """
@page { size: A4; margin: 18mm 17mm 20mm 17mm; }
@page cover { margin: 0; }
:root {
  --navy: #0C1439; --teal: #009DB0; --teal2: #00ABAB; --sky: #B6DCE9; --mint: #E9F4F4;
  --ink: #1d2433; --muted: #5b6475; --rule: #d7e3ea;
}
* { box-sizing: border-box; }
html { font-size: 10.2pt; }
body { margin: 0; color: var(--ink); background: #fff;
  font-family: "LCArabic", -apple-system, system-ui, "Helvetica Neue", Arial, sans-serif;
  line-height: 1.5; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
p, li { orphans: 3; widows: 3; }
a { color: var(--teal); text-decoration: none; }

/* ---------- cover ---------- */
.cover { page: cover; height: 297mm; width: 210mm; background: var(--navy); color: #fff;
  padding: 34mm 22mm 24mm; display: flex; flex-direction: column; break-after: page; }
.cover .kicker { color: var(--teal2); letter-spacing: .18em; text-transform: uppercase;
  font-size: 9.5pt; font-weight: 700; }
.cover h1 { font-size: 44pt; line-height: 1.05; margin: 8mm 0 4mm; font-weight: 800;
  letter-spacing: -0.01em; }
.cover .sub { font-size: 15pt; color: var(--sky); max-width: 140mm; line-height: 1.4; }
.cover .flow { margin-top: 22mm; display: flex; flex-wrap: wrap; gap: 3mm 2mm; align-items: center; }
.cover .flow span.step { border: 1px solid rgba(182,220,233,.55); border-radius: 999px;
  padding: 1.6mm 4mm; font-size: 9.5pt; color: #fff; }
.cover .flow span.arrow { color: var(--teal2); font-size: 11pt; }
.cover .facts { margin-top: auto; display: grid; grid-template-columns: repeat(3, 1fr); gap: 6mm;
  border-top: 1px solid rgba(182,220,233,.35); padding-top: 7mm; }
.cover .facts b { display: block; font-size: 20pt; color: var(--teal2); line-height: 1.1; }
.cover .facts span { font-size: 9pt; color: var(--sky); }
.cover .meta { margin-top: 9mm; font-size: 9pt; color: var(--sky); display: flex;
  justify-content: space-between; }

/* ---------- contents ---------- */
.toc { break-after: page; }
.toc h2 { break-before: auto; }
.toc ol { list-style: none; padding: 0; margin: 6mm 0 0; columns: 1; }
.toc li { display: flex; align-items: baseline; gap: 3mm; padding: 1.55mm 0;
  border-bottom: 1px solid var(--rule); font-size: 10.4pt; }
.toc li .n { color: var(--teal); font-weight: 700; width: 9mm; }
.toc li a { color: var(--ink); }
.toc .readers { break-inside: avoid; margin-top: 6mm; display: grid; grid-template-columns: 1fr 1fr; gap: 4mm; }
.toc .readers div { background: var(--mint); border-radius: 3mm; padding: 3mm 4.5mm; font-size: 9.2pt; }
.toc .readers b { color: var(--navy); display: block; margin-bottom: 1mm; }

/* ---------- body ---------- */
h2 { break-before: auto; margin-top: 11mm !important; font-size: 19pt; color: var(--navy); margin: 0 0 5mm;
  padding-bottom: 3mm; border-bottom: 2.2px solid var(--teal); letter-spacing: -0.005em; }
h2.newpage { break-before: page; margin-top: 0 !important; }
h2 .num { color: var(--teal); margin-right: 1mm; }
h2, h3 { break-after: avoid; }
h3 { font-size: 12.2pt; color: var(--navy); margin: 6.5mm 0 2mm; break-after: avoid; }
h2 + p, h3 + p { margin-top: 0; }
p { margin: 0 0 2.6mm; }
ul, ol { margin: 0 0 3mm; padding-left: 5.5mm; }
li { margin: 0 0 1.2mm; }
strong { color: var(--navy); }
code { font-family: "LCArabic", "SF Mono", Menlo, monospace; font-size: 8.6pt;
  background: #f1f6f8; border: 1px solid #e3edf1; border-radius: 1.2mm; padding: 0 1mm; }
pre { font-family: "LCArabic", "SF Mono", Menlo, monospace; font-size: 7.45pt; line-height: 1.42;
  background: #0f1a33; color: #e6eef5; border-radius: 2.2mm; padding: 3.2mm 4mm; margin: 0 0 3.5mm;
  white-space: pre-wrap; word-break: break-word; break-inside: avoid; }
pre code { background: none; border: 0; padding: 0; font-size: inherit; color: inherit; }
table { width: 100%; border-collapse: collapse; margin: 1mm 0 4mm; font-size: 8.9pt; }
thead { display: table-header-group; }
tr { break-inside: avoid; }
th { text-align: left; background: var(--navy); color: #fff; font-weight: 700; padding: 1.8mm 2.4mm; }
td { padding: 1.7mm 2.4mm; border-bottom: 1px solid var(--rule); vertical-align: top; }
tbody tr:nth-child(even) td { background: #f7fbfc; }
td code, th code { font-size: 8pt; }
hr { display: none; }
.flowdiag { display: flex; flex-wrap: wrap; align-items: center; gap: 2.4mm 1.6mm; margin: 2mm 0 5mm;
  break-inside: avoid; }
.flowdiag .s { background: var(--mint); border: 1px solid var(--sky); border-radius: 2mm;
  padding: 2mm 3mm; font-size: 8.8pt; }
.flowdiag .s b { display: block; color: var(--navy); font-size: 9.4pt; }
.flowdiag .a { color: var(--teal); font-weight: 700; }
"""

FLOW = [("lc init", "move the take in"), ("lc intake", "transcribe, measure"),
        ("editorial read", "decide, verify"), ("lc mkcuts", "decisions to cuts"),
        ("lc rebuild", "EDL, gaps, captions"), ("checks", "each its own class"),
        ("delivered read", "read it as prose"), ("lc render", "gates, render, QC"),
        ("prove and report", "then stop")]


def flow_html():
    parts = []
    for i, (a, b) in enumerate(FLOW):
        if i:
            parts.append('<span class="a">&rarr;</span>')
        parts.append(f'<span class="s"><b>{html.escape(a)}</b>{html.escape(b)}</span>')
    return '<div class="flowdiag">' + "".join(parts) + "</div>"


AR = "\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF"
AR_RUN = re.compile(f"[{AR}]+(?:[ .\u060C\u061B\u061F]+[{AR}]+)*")


def isolate_arabic(html_text):
    """Wrap each Arabic run in <bdi>.

    Without isolation the bidi algorithm treats two Arabic words separated by
    ", " as one right-to-left run and flips their order («تمام», «آآآ» came out
    reversed), and in code it drags the punctuation and numbers after an Arabic
    word into its run. Isolated, each run reads right to left inside a line that
    still reads left to right. Only text is touched, never a tag.
    """
    parts = re.split(r"(<[^>]+>)", html_text)
    return "".join(p if p.startswith("<") else AR_RUN.sub(lambda m: f"<bdi>{m.group(0)}</bdi>", p)
                   for p in parts)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Build docs/lesson-cut-guide.pdf from GUIDE.md.")
    ap.add_argument("--fonts", metavar="DIR",
                    help=f"folder holding the Tajawal .ttf files (default: ${FONT_ENV}, "
                         f"then docs/build/fonts)")
    args = ap.parse_args(argv)
    fonts = font_dir(args.fonts)

    md = SRC.read_text(encoding="utf-8")
    version = re.search(r"Version ([\d.]+), (\d{4}-\d{2}-\d{2})", md)
    ver, date = (version.group(1), version.group(2)) if version else ("", "")

    # The cover and the contents page are built here, so drop the markdown's own
    # title block and contents list.
    body_md = md[md.index("\n## 1."):]
    body = markdown.markdown(body_md, extensions=["tables", "fenced_code", "sane_lists"])

    # Number and anchor every chapter heading.
    chapters = []
    def h2(m):
        text = re.sub(r"<[^>]+>", "", m.group(1))
        num, _, title = text.partition(". ")
        anchor = f"ch{num}"
        chapters.append((num, title))
        # The space after the number is real text, not only a CSS margin: the
        # PDF outline is built from the heading's text, where a margin does not
        # exist ("1What it does" instead of "1 What it does").
        return f'<h2 id="{anchor}"><span class="num">{num}</span> {html.escape(title)}</h2>'
    body = re.sub(r"<h2>(.*?)</h2>", h2, body)

    # A long chapter starts on a fresh page; a short one flows on after the
    # previous chapter instead of leaving most of a page empty.
    pieces = re.split(r'(?=<h2 id="ch)', body)
    body = "".join((p.replace('<h2 id="', '<h2 class="newpage" id="', 1)
                    if p.startswith('<h2 id="ch') and len(p) > 3500 else p) for p in pieces)
    body = isolate_arabic(body)

    # The ASCII flow chart reads badly in print; draw it instead.
    body = re.sub(r"<pre><code>\s*raw take.*?</code></pre>", flow_html(), body, flags=re.S)

    toc = "".join(f'<li><span class="n">{n}</span><a href="#ch{n}">{html.escape(t)}</a></li>'
                  for n, t in chapters)
    flow = "".join((f'<span class="arrow">&rarr;</span>' if i else "") +
                   f'<span class="step">{html.escape(a)}</span>' for i, (a, _) in enumerate(FLOW))

    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>lesson-cut: the complete guide</title>
<style>{arabic_font_face(fonts)}{CSS}</style></head><body>
<section class="cover">
  <div class="kicker">Claude Code plugin</div>
  <h1>lesson-cut</h1>
  <div class="sub">Cut a long recorded lesson down to a tight, captioned video that reads as one
  clean take, with every check run before the render.</div>
  <div class="flow">{flow}</div>
  <div class="facts">
    <div><b>1 h+ &rarr; under &frac12;</b><span>a real take of over an hour, cut to under half its length</span></div>
    <div><b>~200 cuts</b><span>retakes, repeats, fillers, dead air</span></div>
    <div><b>6 / 6</b><span>QC passes on the finished file</span></div>
  </div>
  <div class="meta"><span>The complete guide &middot; version {ver}</span><span>{date}</span>
  <span>Mohamed Khair Arabi &middot; MIT licensed</span></div>
</section>
<section class="toc">
  <h2 style="margin-top:0 !important">Contents</h2>
  <ol>{toc}</ol>
  <div class="readers">
    <div><b>New to it?</b>Read chapters 3, 4 and 5, then 6.</div>
    <div><b>An agent operating it?</b>Chapter 14 first, then 4, 6, 7 and 12.</div>
    <div><b>Something went wrong?</b>Chapter 13.</div>
    <div><b>Changing or sharing it?</b>Chapters 15 to 17.</div>
  </div>
</section>
<main>{body}</main>
</body></html>"""
    OUT_HTML.write_text(page, encoding="utf-8")
    # flush: node writes its "pdf:" line straight to the same stdout, and a
    # piped Python stdout is block-buffered, so without this it prints first.
    print(f"html: {OUT_HTML} ({len(chapters)} chapters)", flush=True)

    env = dict(os.environ)
    subprocess.run(["node", str(HERE / "render_pdf.js"), str(OUT_HTML), str(OUT_PDF), ver],
                   check=True, env=env)


if __name__ == "__main__":
    sys.exit(main())
