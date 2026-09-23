---
name: lesson-cut
description: >
  Cut a long recorded lesson, talk, tutorial or screencast down to a tight delivered video: a raw
  take of 30 to 90 minutes becomes a finished piece with every retake, repeated section, failed
  attempt, spoken "delete this" and stretch of dead air removed, captions burned in, and every
  check run before the render. Use this whenever a new take arrives to be edited ("here is the
  recording", "I'm exporting it now, edit it when it lands", a long .mov or .mp4 handed over),
  whenever a finished piece needs a re-cut, and whenever the job is to make a recording read as one
  clean take. Covers intake, transcription, the editorial read against the script, the cut list,
  captions, the pre-render gates, the render and the QC gate. Built for long landscape recordings,
  not short-form verticals: for a Reel or Short the CUTTING method transfers but the finishing does
  not, so read references/formats.md and start it with `lc init --profile reel-portrait`.
---

# Lesson cut

A raw take is someone building or explaining something live. The delivered version is the same
thing with every stumble, retake and wait removed, and the standard is that a viewer cannot tell
where the joins are. The brief this skill was built around put it in one line: "Give me a clean
version from the first shot."

Everything runs through one command, `lc`, at `${CLAUDE_PLUGIN_ROOT}/scripts/lc`. That full path
is written out only here: Claude Code fills it in when this file loads, it is not an environment
variable in shell commands, and the reference files do not repeat it, so they write `lc` and mean
this path. Write it in full, in double quotes, in every shell command (an unquoted path with a
space in it breaks). It is written `lc` below for short:

    lc doctor                                             # what is missing on this machine
    lc init <project-dir> --source <video> --lang ar      # scaffold a project around a take
    lc intake                                             # probe, transcribe once, measure words
    lc mkcuts decisions.json > speech_cuts.txt            # decisions -> cut-list lines
    lc rebuild                                            # cut list -> EDL -> tightened -> captions
    lc render                                             # gated render, then stop

`lc <tool>` runs any tool in the plugin against the current project, from the project directory or
its `edit/` directory, and `lc tools` lists them all. A relative file path is read from where you
stand.

## Before the first run on a machine

`lc doctor` is not optional on a new machine. It checks ffmpeg, the python version and modules, a
transcription backend, and whether libass actually resolves the caption font, which is the one
failure that otherwise shows up only in the delivered pixels after a long render.
`bash "${CLAUDE_PLUGIN_ROOT}/scripts/setup.sh"` creates a private virtualenv at
`~/.lesson-cut/venv` (or under `$LESSON_CUT_HOME` when that is set), outside the plugin, and
installs what is missing; add `--local-asr` for transcription with no API key. The ElevenLabs key,
when there is one, lives in `~/.lesson-cut/env` (`$LESSON_CUT_HOME/env` when that is set) or the
environment, never inside the plugin or a project.

## Non-negotiables

These come from expensive failures. Everything else in this skill is judgement.

- **Never reduce resolution.** Render at the source's own resolution with an explicit scale, never
  a tool default. `lc init` reads the source's long edge and writes it into `project.json`.
- **Burned captions, verified in the delivered pixels**, not just in `master.ass`. Pull a frame out
  of the finished file and look at it.
- **Move the source into the project, do not copy it.** A 5 GB take should not exist twice.
- **Transcribe once.** Transcripts cache in `edit/transcripts/`; a paid recogniser charges per run.
- **One render at a time**, and never edit a script that is currently running.
- **Nothing ships unless the operator says so.** The default end state is a rendered, gated file
  and a report.
- **Check lip sync once per recording setup.** If the export carries its audio early, set
  `render.av_offset_s` in `project.json`. It defaults to 0; the gate cannot see a wrong value.

## The spine

Work through these in order. Each phase has a reference file with the exact commands and the
reasoning; read the reference when you reach the phase, not before.

| Phase | What happens | Reference |
|---|---|---|
| 1. Intake | Move the take in, probe it, transcribe once, measure audible word extents | `references/pipeline.md` |
| 2. Orient | Read the script the take was made from, sample the picture, estimate the delivered length | `references/pipeline.md` |
| 3. Editorial read | Read the whole take against the script and decide every cut, with verification | `references/editorial-read.md` |
| 4. Author the cut | Decisions through `lc mkcuts` into `cutlist.py`, then `lc rebuild` | `references/pipeline.md` |
| 5. Machine checks | The pre-render gates, each catching a class the others cannot see | `references/pipeline.md` |
| 6. Delivered read | Read the cut end to end as prose, joins marked | `references/editorial-read.md` |
| 7. Render and prove | Gated render, QC gate, inspect the finished file yourself | `references/delivery.md` |
| 8. Report, then stop | Report and hold. Ship only when told | `references/delivery.md` |

## How to decide what gets cut

This is the part that makes the piece feel clean, and it is judgement, not a detector. The scanners
find candidates; the decision is always "does the delivered version still say everything it said,
and does it now read as one take?"

**Cut these.** A retake (keep the last complete attempt, which is usually the correction). An
abandoned attempt, back to where the attempt began rather than just its last broken word. A
truncated word. A doubled word or stutter. Self-talk while hunting the screen. A failed action and
its retry (a dictation that never landed, a click that did nothing, a command that errored),
keeping the attempt that worked. A point that lands more times than the script asks for. Reading
aloud something the speaker then says properly in their own words. A half-read of a line on screen that stops
partway and goes nowhere: the fragment has no meaning and the screen still carries the full line.

**Sweep the standalone fillers as their own pass.** A lone "OK", "right", "so", «تمام», «آآآ» or
"um" sitting between two silences, with nothing either side of it, is a cut. They are easy to read
past one at a time, and there are dozens in an hour: on the lesson this skill was built from,
about one cut in five was exactly this. They are also most of the difference between a piece that
feels clean and one that feels nearly clean, so walk the transcript once looking for nothing else.
A test run that found every structural cut still missed a third of these, which is why this is its
own pass rather than a category to notice in passing.

**Never cut these.** An idea that is not delivered again somewhere else. The corrections the
speaker makes to the tool on camera, which in a build lesson are the lesson. A parallel
construction or a list that continues a sentence rather than replacing it. An on-screen action
whose narration is the only thing explaining it.

**When the speaker talks to the editor** ("delete this", "scrap that", "let me do that again",
«احذف هاي», «إعادة»), the instruction is a cut and so is its referent, but the scope is bounded by
re-coverage, not by the instruction's position. List the ideas between the previous clean point and
the instruction, search forward for each one being delivered again, and cut back only as far as the
earliest idea that IS re-covered. Anything not re-covered stays, however rough it sounds. As the
author put it: "I don't mean for everything, everything. I just mean for
the last scene or the last idea that didn't really get explained correctly." And check whether the
instruction is aimed at the editor at all: the same words often mean "delete this line from the
draft I am editing on screen".

**A garbled delivery is cut; a garbled transcript is captioned.** When a line reads as nonsense,
decide which of the two it is before acting. If it was said cleanly and the recogniser misheard,
the screen tells you the real words and it is a caption correction. If the delivery itself is
broken, half-read or slurred past intelligibility, no caption can honestly carry it and it is a
cut. The transcript alone cannot tell you which, and assuming the first case leaves broken speech
in the file, so settle it mechanically: read the screen at that timestamp, then run a SECOND
transcription over that span. If the second reading matches the screen, fix the caption. If both
readings disagree with the screen and with each other, the delivery is broken and the line goes.

**Which copy to keep when something is said twice.** The one that landed. If a prompt was dictated
twice, the frames decide it: the take that reached the input box is the one the tool actually
received, and keeping the other one desynchronises the audio from the screen. Check the frames
rather than reasoning about which reading sounds better.

**Silence is not your job to judge one gap at a time.** `lc tighten_gaps` trims every wordless gap
and keeps a short beat of the busiest picture on long waits, so the viewer sees the tool working.
Your job is the two things it cannot judge: audio with no transcript word under it (a murmur, or a
removed filler ringing past its measured end), and a wait beat that shows a detour instead of the
work. Both have tools, `lc untranscribed` and `lc waitbeats`, and both are in phase 5.

**Flag, do not silently fix, anything the picture carries.** If the speaker says something the
screen contradicts, or does something the script forbids, and no cut can fix it because the action
is visible, then cut nothing and put it in the report as the operator's decision. Cutting the audio
alone would leave the screen telling a different story.

## Working rules that keep the edit honest

- **The script is the contract.** If the take was made from a script, cut against it, and report a
  beat it promises that the take never delivers.
- **Read the delivered cut, not the source transcript.** The defects that matter are the ones the
  cut created or left adjacent, and in the source they can be half a minute apart.
- **A skipped cut is a cut that did not happen.** `build_edl` prints `SKIPPED (no clean boundary)`
  when an edge has nowhere to land, usually a speech cut pasted without its two pinning fields.
  Paste mkcuts' tuples whole, and decide every SKIPPED line: widen the cut, pin its edges, or write
  an accept with a measurement. Never let one scroll past.
- **An accept is a written judgement, never a loosened detector.** It goes in
  `edit/qc-accept.json` with a `phrase` and a `reason`, and the phrase must match what the check
  matched; `references/pipeline.md` has the table and the matching rules.
- **Sweep the class, never the instance.** The moment one instance of a mechanical defect is found,
  enumerate every instance across the timeline and fix them together.
- **When two checks disagree, re-derive the measurement before overriding either.** A tool that has
  been right all session is usually right again.
- **Report honest deltas.** Compare against the live version when re-cutting, and never call a
  piece finished before the gate's own verdict line says so.
- **Every correction the operator gives becomes a written rule the same session.** Keep it in the
  project's own house rules file; `references/house-rules.md` explains the practice and carries the
  rules that are physics rather than taste.

## What to hand back

The operator watches the file, so the report is short and specific, in this shape:

1. The file path and the delivered length against the raw length.
2. What was cut, grouped by kind, naming the interesting ones by timestamp (the delete
   instructions, the retakes, the failed attempts).
3. What was fixed that they did not ask about (murmurs, wait-beat detours, caption corrections
   verified against the screen).
4. The flags: things in the recording itself that no cut can fix, each one their call.
5. Length against the script's target, with the largest trims that would lose no idea, if it is
   over.

Then stop.

## Other formats

The cutting method here is general: retakes, re-coverage, the delivered read, the gates. The
finishing is not. Caption size and margins, aspect ratio, graphics and music all differ for a short
vertical video, and applying a landscape lesson's numbers to a portrait Reel puts the captions in
the middle of the frame. Before touching another format read `references/formats.md`. A portrait
piece starts with `lc init <project-dir> --source <video> --profile reel-portrait`, which writes
the portrait caption numbers into `project.json`; nothing in the plugin reframes a landscape take
to portrait, so the source has to be portrait already.
