---
name: lesson-doctor
description: Check that this machine can run the lesson-cut toolchain, and say exactly what is missing
---

Run the prerequisites check:

```
bash "${CLAUDE_PLUGIN_ROOT}/scripts/doctor.sh"
```

It checks ffmpeg and ffprobe, the python version and the three modules the toolchain imports, an
ASR backend, and whether libass actually resolves the caption font. That last one matters more than
it sounds: a missing font does not fail anything, it silently substitutes another face, and the
first sign of it is the delivered pixels after a long render.

If anything is missing, offer to run `bash "${CLAUDE_PLUGIN_ROOT}/scripts/setup.sh"`, which
creates a private virtualenv at `~/.lesson-cut/venv` (or under `$LESSON_CUT_HOME` when that is
set), outside the plugin, and installs what it can. Keep the double quotes around the path: it
breaks without them if it contains a space. Add
`--local-asr` to install faster-whisper so the machine needs no transcription API key at all. A key,
if used, goes in `~/.lesson-cut/env` (`$LESSON_CUT_HOME/env` when that is set) as
`ELEVENLABS_API_KEY=...`, never inside the plugin.

Inside a project, the font check uses the project's own caption font.

Report the result plainly, including the free-disk note the doctor prints: a 4K render needs a few
GB of scratch (per-segment clips and a base file) on top of the final file, and camera footage
needs more.
If the doctor reports that ffmpeg has no libass, the fix on macOS is `brew install ffmpeg-full`.
