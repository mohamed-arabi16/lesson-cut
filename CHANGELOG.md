# Changelog

Versions follow MAJOR.MINOR.PATCH. The version lives in `.claude-plugin/plugin.json`, and
`metadata.version` in `.claude-plugin/marketplace.json`, line 3 of `GUIDE.md` and the PDF guide
agree with it. An installed copy only updates when the version changes.

## 1.2.0 - 2026-09-23

The first public release. The versions below it were used privately and are summarised from their
release notes.

### Install and updates

- Install from GitHub: `/plugin marketplace add mohamed-arabi16/lesson-cut`, then
  `/plugin install lesson-cut@lesson-cut`, then `setup.sh` from the marketplace copy. The README,
  GUIDE.md and the PDF describe installing from GitHub or from a clone, and no longer tell anyone to
  install or share a zip.
- The update steps are corrected. `/plugin marketplace update lesson-cut` alone does not update an
  installed plugin; `/plugin update lesson-cut@lesson-cut` and a restart of Claude Code are needed
  too.
- Steps for moving from a zip (folder) install to the GitHub one: Claude Code will not switch an
  existing `lesson-cut` marketplace from a folder to GitHub until it is removed.
- The by-hand path to `lc` is the marketplace copy, with a warning never to alias or link into the
  versioned plugin cache.
- The plugin and marketplace manifests link to the repository and the author.

### Captions

- Right-to-left embedding now goes only on caption lines that contain right-to-left script. Every
  line used to be wrapped, so an English line that started with a number or ended in punctuation
  rendered in the wrong order, and the QC gate still passed it. The gate now checks both ways: an
  Arabic line without the embedding fails, and so does a line with no right-to-left script that
  has it.
- The embedding characters are written as escapes in the source, so no file carries invisible
  bidirectional control characters.
- A project started before 1.2.0: run `lc build_captions .` (or `lc rebuild`) in it once before its
  next render. Its `master.ass` wraps every line, and the QC gate now fails any wrapped line with no
  right-to-left script. `lc render` refuses such a file before it starts rather than after a render.

### Setup and messages

- `setup.sh` rebuilds a virtualenv that an earlier failed run left without pip, instead of failing
  on every run after it. Its uv fallback creates the virtualenv with pip. When Python cannot create
  one, it names the Debian/Ubuntu package that is missing (the `-venv` package for the Python it
  picked, such as `python3.12-venv`). It only ever clears a folder that is a virtualenv or empty: a
  `venv` folder holding anything else is refused, never deleted.
- The doctor's macOS ffmpeg hint names `ffmpeg-full`, since the plain formula cannot burn captions.
  Before setup has run, a missing Python module points at `setup.sh` instead of a pip install into
  the system Python.
- The doctor's key-file hint, and `lc intake`'s when it finds no key and no local recogniser,
  create the folder and a private file (`umask 077`), and point at `setup.sh --local-asr` for the
  local route.
- `lc init`'s next-step hint and `lc intake`'s missing-backend message print the full path to `lc`,
  since `lc` is on nobody's PATH.
- The doctor says where to get the default caption font (Almarai, free under the SIL Open Font
  License).

### Skill, agents and commands

- The editorial brief template no longer hands every reader the author's own brief. It has a field
  for the operator's own, which says whether the take contains spoken instructions to the editor.
- The window reader reads the filled brief in the shared scratch directory, not the blank template.
- Commands and templates quote the plugin path, so a path with a space in it works, and say that
  `lc` means the full path.
- The author's house style (lesson length, brand marks, a music bed) is no longer presented as each
  format's default, and a rule about web code left the video house rules.

### Documentation and repository

- The PDF build no longer defaults to a folder on the author's machine. It takes its font folder
  from `--fonts` or `LESSON_CUT_PDF_FONTS`, finds Tajawal under Google Fonts' file names too, and
  `docs/build/README.md` says what it needs. The PDF outline has a space after each chapter number.
- `LICENSE` is the plain MIT text, so GitHub recognises it. `THIRD_PARTY_NOTICES.md` pins the
  video-use commit the derived scripts came from, credits the helper `scripts/transcribe_local.py`
  reuses, and lists what lesson-cut uses without shipping.
- New: this file, `CONTRIBUTING.md`, `SECURITY.md`, a bug report template, `.gitattributes` (LF line
  endings everywhere) and a fuller `.gitignore`.
- Only the shell entry points are executable; the Python tools always run through `lc`.

## 1.1.1 - 2026-09-23

The consolidated correction round from the second round of independent testing (GUIDE.md
chapter 16).

- `lc render --out` renders to a temporary name and replaces the output only on success. It reads a
  relative `--out` from where you stand and refuses an existing file outside `edit/` or any source
  file: `--out take1.mp4` used to delete the raw take.
- The QC gate measures the video stream's own length, so a file whose picture stops halfway through
  its sound no longer passes. It judges every silence, needs two words for an n-gram accept, and
  measures a restart's pause in the take. English function words joined its stopword list.
- The final verdict re-runs `head_onset_check`, so `--accept-findings` cannot ship a clipped head or
  tail under a green gate. A malformed `qc-accept.json` stops the render, and the fps check is
  numeric.
- The doctor checks that ffmpeg has libass (Homebrew's plain ffmpeg does not, and the doctor used to
  say "ready"), reads a project's caption font from the project too, and matches fonts by prefix.
  Its libass check no longer races under `pipefail`.
- `tighten_gaps` gives the ring-out allowance only to removed words; for a kept word it hid a missed
  word said right after it.
- `build_edl` drops kept slivers under 0.1s with no word in them (two-frame flashes of picture).
- `lc rebuild` refuses a stitched lesson instead of wiping its pause cuts; `gapcheck --emit` works;
  `mkcuts` refuses an accuracy flag.
- `THIRD_PARTY_NOTICES.md` carries video-use's MIT notice for the three scripts derived from it.
- GUIDE.md corrected against two fact-checks, and the guide as a PDF (`docs/lesson-cut-guide.pdf`)
  with `docs/build/` to rebuild it.

## 1.1.0 - 2026-09-23

Fixes from the first round of independent testing, which ran on 1.0.1.

- `build_edl` no longer stamps a lip-sync offset measured on the author's own setup into every EDL;
  it is `render.av_offset_s` in `project.json`, default 0.
- `lc init` sets the render size from the source's long edge, so a portrait take no longer renders
  at 608x1080. It validates the source before creating or moving anything, never overwrites a take,
  and matches the caption canvas to the source's aspect ratio.
- The doctor's font check compares what libass actually resolved; it used to pass every font.
- `lc render` exits 1 on a failed QC gate, refuses stale or missing captions, and runs one render at
  a time. `--out` must be a .mp4 or .mov file: given a directory, it used to delete it.
- `tighten_gaps` measures each cut's interior for speech, so a word the transcript missed inside a
  quiet gap is held and reported instead of deleted. It refuses an EDL that already has pause cuts.
- New `lc rebuild` runs the cut list, EDL, gap tightening and captions in the one order that works.
- The QC gate's caption probe follows the caption style, so portrait renders pass. Project paths
  with an apostrophe render.
- `mkcuts` can remove a take's last word. `transcribe` prefers the environment key, never reads a
  key from inside the plugin or a project, needs no key for a cached transcript, and finds the key
  file under `LESSON_CUT_HOME` like the virtualenv.
- `delivered_read` and `untranscribed` report delivered time on the renderer's frame grid (they ran
  early on a long lesson); `gapcheck` uses the render's fps and checks the lead-in and tail;
  `capcheck` samples each cue at its midpoint on the delivered frame; `waitbeats` no longer fails a
  lesson that has no long waits.
- A caption phrase marked as unsplittable stays whole at a line break too, and a cue never ends on
  an article.
- A crop tool hard-wired to one recording was removed.

## 1.0.1 - 2026-09-22

- The virtualenv moved to `~/.lesson-cut/venv`, outside the plugin, because a virtualenv does not
  survive Claude Code copying an installed plugin into its cache. `LESSON_CUT_HOME` moves it.
- The doctor's Python floor is 3.9, the version the whole chain was run on, matching `setup.sh`.
- `claude plugin validate --strict` passes on the marketplace, the manifest, the skill, the agents
  and the commands.

## 1.0.0 - 2026-09-20

- The lesson edit pipeline as a standalone Claude Code plugin: the `lesson-cut` skill, three agents,
  `/cut-lesson` and `/lesson-doctor`, and the toolchain behind one command, `lc`.
- Caption style, render quality and per-take vocabulary live in each project, so one plugin serves
  a landscape course canvas and a portrait one.
- Transcription with ElevenLabs Scribe or a local whisper backend, so no API key is required.
- The doctor checks the prerequisites, including which font libass actually resolves.
