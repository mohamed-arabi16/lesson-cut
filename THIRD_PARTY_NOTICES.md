# Third-party notices

## Code derived from video-use

Three files in `scripts/` are derived from **video-use** (https://github.com/browser-use/video-use),
taken from upstream commit `92c2b34e44c205cbc2acae7f6ca7c1c219d5dd66` (2026-07-01) and used under
the MIT License reproduced below:

| File | Derived from |
|---|---|
| `scripts/render.py` | `helpers/render.py` |
| `scripts/grade.py` | `helpers/grade.py` |
| `scripts/transcribe.py` | `helpers/transcribe.py` |

`scripts/transcribe_local.py` also reuses the `extract_audio()` helper from `helpers/transcribe.py`.

These files have been changed for this plugin (per-project quality settings, error reporting, key
handling, a local transcription backend, and path handling). Those changes, and the rest of
lesson-cut, are covered by the `LICENSE` file at the root.

---

MIT License

Copyright (c) 2026 Browser Use

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

---

## What lesson-cut uses but does not ship

Nothing below is bundled in this repository. You install it, or `scripts/setup.sh` installs it into
`~/.lesson-cut/venv`, each under its own license. It is listed so you know what you are running.

| Component | License | How it arrives |
|---|---|---|
| ffmpeg and ffprobe | LGPL 2.1 or later, or GPL 2 or later for builds with GPL parts such as libx264, which the render uses | you install it |
| numpy | BSD-3-Clause | `setup.sh` |
| Pillow | MIT-CMU | `setup.sh` |
| requests | Apache-2.0 | `setup.sh` |
| urllib3 (kept below 2 on Python 3.9) | MIT | `setup.sh` |
| faster-whisper (optional) | MIT | `setup.sh --local-asr`, which also pulls in its own dependencies, among them CTranslate2 (MIT) and PyAV (BSD-3-Clause) |
| openai-whisper (optional, instead of faster-whisper) | MIT | you install it |
| ElevenLabs Scribe (optional) | a paid service under ElevenLabs' own terms | your API key |
| Almarai, the default caption font | SIL Open Font License 1.1 | you install it ([Google Fonts](https://fonts.google.com/specimen/Almarai)) |

Building the PDF guide (not needed to use the plugin) also takes python `markdown` (BSD-3-Clause),
`playwright-chromium` (Apache-2.0), which downloads a Chromium build, and optionally the Tajawal font
(SIL Open Font License 1.1), a subset of which the PDF then embeds. See `docs/build/README.md`.
