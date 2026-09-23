# Delivery: render, prove, report

## Render

    lc render                       # settings come from edit/project.json
    lc render --scale 3840 --fps 30 # or state them
    lc render --accept-findings     # only after every finding is accepted in writing

`lc render` checks that the captions belong to this cut (it refuses a missing `master.ass`, one
older than `edl.json`, or one stamped for a different fps) and that `project.json` parses, runs three
pre-render gates (`post_cut_check`, `qc transcript`, `head_onset_check`), takes the render lock,
waits for any other ffmpeg to finish, renders, runs the full six-pass QC gate plus `post_cut_check`
once more, and stops. Nothing is uploaded and nothing is published. It exits 1 when anything
refuses or fails, so a script or an agent can act on the result; the full report is in
`edit/qc.log`.

`--accept-findings` renders past findings a gate reports, never past a gate that crashed or a
malformed `qc-accept.json`, and the final verdict re-runs `post_cut_check` and `head_onset_check`
and says NOT CLEAN while any finding stands. `--out` is read from where you stand, must name a
`.mp4` or `.mov`, and may not replace a source or any existing file outside `edit/`; the render goes
to a temporary name and replaces `--out` only when it succeeds.

The gates run before the render because two of them never touch the video. On the lesson that
taught this, a long 4K render was thrown away over two surviving repeats that `qc transcript`
reports in seconds.

`render.scale` is the source's own long edge, never less. `render.crf` is 18 for a screen recording,
which is mostly flat UI, and 23 for camera footage, where skin, fabric and bokeh carry far more
information at the same CRF. A higher CRF is not a lower resolution: the delivered file keeps its
full size and only the bitrate moves. A 4K camera piece left at 18 came out at about 19.5 Mbps,
too large to stream comfortably.

A 4K render of a piece about half an hour long takes roughly an hour and a half and produces a file
around 600 MB. The run writes per-segment clips, a base file and the final into `edit/`: about
3 GB of scratch for a screen recording of that length, and more for camera footage, so leave
generous room.
If the plan changes mid-render, kill it rather than letting it finish a superseded cut, and confirm
no ffmpeg survived. A `final.mp4` with no `qc.log` beside it is an ungated file.

For a quick look at a cut before committing to the real render, call the renderer directly; it has
draft and preview modes the gated command does not expose. It is `render.py`, in the same
`scripts/` directory as the lc path SKILL.md gives, run with the toolchain's own python:

    "${LESSON_CUT_HOME:-$HOME/.lesson-cut}/venv/bin/python" \
        "<the scripts dir from SKILL.md>/render.py" \
        edit/edl.json -o edit/draft.mp4 --draft --fps 30      # 1280 long edge, fast

Always pass `--fps` equal to `render.fps`, or the captions drift. A draft is for checking cuts, not
for delivery.

## Prove the file, do not trust the green

The gate's six passes are necessary and not sufficient. After `QC GREEN`:

- Read the gate's own measurement lines in `edit/qc.log`, not just the verdict: caption grid offset,
  cue count, "burned captions confirmed in pixels at N/N sampled cues", delivered resolution, A/V
  skew, loudness. A pass that reports nothing measured has told you nothing.
- Pull frames from `final.mp4` itself at the opening, the closing, a few caption moments and every
  spot you fixed, and look at them. Map a delivered time from the EDL by accumulating
  `ceil(dur × fps) / fps` per range, not raw durations.
- Check lip sync by eye at one hard sound. The gate compares stream start times only, so a wrong
  `render.av_offset_s` passes it.
- If the recording shows a screen, sweep the whole frame for anything that should not ship: one
  frame every 15 seconds of delivered time, plus every second across any span showing mail, a file
  browser, a chat, an IDE or a document.

      ffmpeg -v error -i edit/final.mp4 -vf "fps=1/15,scale=960:-1,tile=4x3" edit/sweep_%02d.jpg

  What gets raised, once, with a measured duration: a live credential, which blocks publishing,
  or a third party's private data. Agree with the operator beforehand what is settled and not worth
  reporting (usually their own name, their own account contents and their machine's user name),
  and keep that list in the project. This sweep is a good job to delegate while the render runs.

## Report and hold

The default end state is a rendered, gated, self-inspected file and a short report. The operator
watches it. `SKILL.md` has the report shape.

## Shipping

There is no upload step in this plugin, on purpose: every platform's is different, and a wrong
upload is expensive to undo. When the operator asks for one, write it as a project script and hold
it to the same standard as the render:

- Re-run the full gate before uploading, so nothing rebuilt after its last check can ship.
- Presence at the destination is the post-condition, not the upload command's exit code, and
  object storage is usually eventually consistent, so one immediate read can report a perfect
  upload as missing.
- Publishing is a separate decision from uploading. Default to not published.
- If the destination carries copy in more than one language, write every language every time.
  Writing only the first leaves the other showing planning-era text, which is exactly how a
  superseded title survived a fresh one.

## Close the loop

- **Project log**: the delivered length, where the file went, its state, and the open flags. State
  is rewritten in place when it changes; events are appended.
- **House rules**: every correction the operator gives becomes a numbered rule the same session,
  with what they said, what was actually wrong, and the generalised rule. See `house-rules.md`.
  Automate it where a tool can carry it.
