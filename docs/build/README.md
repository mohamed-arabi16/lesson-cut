# Building the PDF guide

`docs/lesson-cut-guide.pdf` is made from `GUIDE.md` by the two scripts in this folder. Rebuild it
whenever `GUIDE.md` changes; the plugin itself never runs them.

- `build_pdf.py` turns `GUIDE.md` into designed HTML (a cover, a linked contents page, long chapters
  starting a fresh page), writes it to `docs/build/guide.html` (ignored by git), and then runs
- `render_pdf.js`, which prints that HTML to PDF through Chromium, with page numbers and a
  clickable outline. Chromium shapes Arabic correctly (HarfBuzz); Python PDF libraries break the
  guide's Arabic words apart.

The version and date on the cover and in the footer come from the `Version X.Y.Z, YYYY-MM-DD` line
at the top of `GUIDE.md`, so keep that line in exactly that form.

## What it needs

- **Python 3.9 or newer, with `markdown`.** It is not in `requirements.txt`, because the plugin does
  not need it. The shipped PDF was built with markdown 3.9.
- **Node, with `playwright-chromium` where `require()` finds it**: through `NODE_PATH` (the setup
  below). A `node_modules` folder in `docs/build/` also works, but installing one there writes
  `package.json` and `package-lock.json` beside it, which git will list. The shipped PDF was built
  with playwright-chromium 1.59.1. Installing it also downloads a Chromium build.
- **The Tajawal font, for the Arabic** (optional). It is free under the SIL Open Font License 1.1
  from https://fonts.google.com/specimen/Tajawal, and no font ships in this repository. The build
  looks for its .ttf files in the folder given by `--fonts <dir>`, else in `$LESSON_CUT_PDF_FONTS`,
  else in `docs/build/fonts/`. Google Fonts file names (`Tajawal-Regular.ttf`, `Tajawal-Bold.ttf`)
  work. Keep the fonts outside the repository rather than in `docs/build/fonts/`, so they are never
  committed by accident. Without Tajawal, the build prints a note and the Arabic falls back to the
  system's Arabic font.

The build has only been run on macOS, and its styles are written for macOS system fonts.

## One-time setup

Keep the tools outside the repository, so the build adds nothing to `git status`:

```bash
TOOLS=~/.cache/lesson-cut-pdf
python3 -m venv "$TOOLS/venv"
"$TOOLS/venv/bin/python" -m pip install markdown==3.9
npm install --prefix "$TOOLS" playwright-chromium@1.59.1
```

## Build

From the repository root:

```bash
TOOLS=~/.cache/lesson-cut-pdf
NODE_PATH="$TOOLS/node_modules" "$TOOLS/venv/bin/python" docs/build/build_pdf.py --fonts ~/fonts/Tajawal
```

It prints the Tajawal files it found, the HTML path with its chapter count, then `pdf: <path>`.
It overwrites `docs/lesson-cut-guide.pdf` in place. Before committing, open it and check the cover's
version, the contents links and a page with Arabic on it;
`pdffonts docs/lesson-cut-guide.pdf | grep -i tajawal` confirms that Tajawal was embedded.
