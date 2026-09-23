# Pipeline: intake to a checked cut

Every command below is `lc`, short for the full path to the plugin's `scripts/lc` that SKILL.md
gives. This file does not carry that path (Claude Code fills it in when SKILL.md loads, and it is
not an environment variable in shell commands), so write the lc path from SKILL.md, in double
quotes, wherever `lc` appears. Run it from the project directory or from its `edit/` directory; it
finds the project either way, and a relative file path you give it is read from where you stand.

By hand, outside Claude Code, a marketplace install keeps a stable copy (under `$CLAUDE_CONFIG_DIR`
instead of `~/.claude` when that is set; a clone has its own `scripts/lc`):

    LC=~/.claude/plugins/marketplaces/lesson-cut/scripts/lc
    "$LC" doctor

Never point an alias, a symlink or PATH into `~/.claude/plugins/cache`: that copy is versioned and
is left behind on the next update.

## Phase 1: intake

A take usually arrives as an export from an editor, often still being written when you are told
about it. If it is still exporting, set a background waiter rather than polling in the foreground:
watch for the file's size to stop growing and for the editor's temp folder to disappear. A
foreground `sleep` is blocked in most agent harnesses; a backgrounded loop that notifies on exit is
not.

    lc init 2026-09-20-my-lesson --source ~/Downloads/export.mov --lang ar
    cd 2026-09-20-my-lesson
    lc intake

`init` MOVES the source in (a 5 GB take should not exist twice; `--copy` overrides), probes it, and
writes `edit/project.json` with the source's own long edge as the render scale and a caption
canvas with the source's own aspect ratio. `intake` transcribes once and measures the audible
extent of every word. It prints which backend it used: `scribe` is the paid ElevenLabs API, `local`
is whisper on this machine.

The project layout is fixed, because the tools depend on it:

    <project>/take1.mov            the source, one level ABOVE the edit dir (.mov or .mp4)
    <project>/edit/project.json    render and caption settings
    <project>/edit/cutlist.py      THE EDIT
    <project>/edit/transcripts/    take1.json (raw) and take1.audible.json (measured)

`measure_tokens` writes `transcripts/take1.audible.json`, the measured extent of every word. The cut
builders and the caption builder read that file rather than the recogniser's logged spans, because
a recogniser pads a token's end (and sometimes its start) with silence, and a cut placed on a logged
boundary either restores seconds of dead air or clips a word. Re-run it after ANY change to
`take1.json`: the measured file is matched to the raw one by position, and a stale one silently puts
every measurement on the wrong word. `lc intake` always runs it.

With the local backend, the model decides whether the transcript is usable. On mixed Arabic and
English speech, whisper `base` produced nothing usable (0 of 41 words right when forced to Arabic,
and every Arabic word dropped when left to auto-detect); `small` got 36 of 41 and places cuts well;
`large-v3`, the default, is the most accurate and the slowest, and its first run downloads about
3 GB. `lc intake --backend local --model small` is the practical floor for Arabic.

The transcript is cached on its file name. A second `lc intake` costs nothing. Replacing the take
with a different recording under the same name does NOT invalidate it: delete
`edit/transcripts/take1*.json` by hand first.

## Phase 2: orient

- **Read the script the take was made from.** It is the contract: target duration, beats in order,
  exact answers, on-screen directions. Cut against it. If there is no script, ask for the intended
  length and the beats before cutting anything.
- **Look at the picture before reading the words.** One frame per minute, tiled into contact
  sheets, tells you the structure, which applications appear, and whether there is a webcam inset:

      SRC=$(ls take1.* | head -1)
      DUR=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$SRC" | cut -d. -f1)
      for t in $(seq 5 60 $DUR); do ffmpeg -v error -y -ss $t -i "$SRC" -frames:v 1 \
        -vf "scale=640:-1,drawtext=text='$t':x=10:y=10:fontsize=28:fontcolor=yellow:box=1:boxcolor=black" f_$t.jpg; done

- **Estimate the delivered length before cutting anything.** Sum the utterance spans in
  `edit/transcript_lines.txt` and add about 0.3s per gap. If that number is already far over the
  target, the cut has to be structural (whole redone sections), not just stumble removal.
- **Check lip sync once.** Pull a frame at a hard sound that meets a visible action (a click, a
  clap, a plosive on camera). If the export carries its audio early, set `render.av_offset_s` in
  `project.json` to how far early, in seconds. It defaults to 0.

## Phase 3: editorial read

See `editorial-read.md`. It produces a decisions list: for each cut, the first word removed and the
first word kept, with a reason.

## Phase 4: author the cut

**The decisions file** is a JSON array. Each entry names two words by their start times, as
`lc words <from> <to>` prints them:

    [{"rm": 812.44, "keep": 815.02, "why": "abandoned attempt, redone at 815"},
     {"rm": 4786.10, "keep": 99999, "why": "tail: after the closing line"}]

`rm` is the first word to remove and `keep` the first word to keep after it. A `keep` after the
last word of the take makes a tail cut to the end of the source. The editorial workflow's own keys
(`first_removed_word_start`, `first_kept_word_start`, `reason`) are accepted too, so its output can
be passed in unchanged.

`mkcuts` turns decisions into cut-list lines:

    lc mkcuts decisions.json > speech_cuts.txt     # audit the ‖ [dropped] ‖ lines

It unions overlapping findings by word index (so two readers' versions of one cut become one cut)
and pads edges by `min(0.03, gap/2)`, because a fixed 30 ms pad lands inside a removed word wherever
two words abut, and the caption builder assigns a word to the range containing its END. A head cut
ends 0.25s before the first kept word's measured onset, so the viewer hears a clean lead-in rather
than a clipped first syllable, unless a removed word ends inside that 0.25s.

**Paste the tuples into `SPEECH_CUTS` in `edit/cutlist.py` WHOLE**, all six fields:

    (812.410, 814.990, "abandoned attempt, redone at 815", 0.0, False, False),

The last two fields pin both edges where mkcuts put them. A speech cut pasted as just
`(start, end, "why")` lets `build_edl` move its edges to the nearest quiet point, which for a cut
that removes speech can shrink it to nothing, and it prints `SKIPPED`. Order in the list does not
matter: `build_edl` sorts every cut and unions overlaps.

Then rebuild:

    lc rebuild

That is five steps in the one order that works: empty `pause_cuts.py`, build the EDL from the speech
cuts alone, tighten every wordless gap against that raw EDL, build the EDL again with the pause cuts
in, and build the captions. The tightener has to see RAW gaps. Run over an EDL that already has the
pause cuts in it, it would write an empty list and the next build would restore every second of
dead air, so `tighten_gaps` now refuses to do that, and `lc rebuild` is the way to run it.

The default numbers are `0.50 0.18 4.0 0.90`: a wordless gap over 0.5s is trimmed to about 0.18s
plus a small edge either side, and a wait over 4s keeps 0.9s of its busiest picture so the viewer
sees the tool working. A gap under about 0.7s is left whole, because there is no piece of it long
enough to remove safely; the tightener says how many. `lc rebuild 0.60 0.20 5.0 1.2` sets all four.

The tightener also measures the inside of every cut it is about to make, not just its edges. A gap
is only wordless according to the transcript; if the recogniser missed a word, the "gap" holds
speech. When a cut's interior holds speech-level sound that no transcript word accounts for (sound
up to 0.8s after a word counts as that word's ring-out), the cut is not made and the rebuild says
`cut(s) NOT made: the gap holds speech-level audio with no word under it`. Listen to each one: it
is either a word the transcript missed (keep it, or fix the transcript) or a murmur (cut it
deliberately as a speech cut).

**Read the rebuild's output.** `build_edl` prints the range count, the delivered length, straddles
(a range edge inside a word, reported), and the words dropped by the cut. It REFUSES to write when a
word is dropped that no declared cut covers. Every `SKIPPED` line is a cut that did not happen:
widen it to the next real boundary, pin its edges, or write an accept with a measurement. Never let
one scroll past.

## Phase 5: the checks, and what each one alone can see

Run all of them. They are not redundant; each exists because the others missed something.

    lc waitbeats            # contact sheet of every kept wait beat: before | beat | after
    lc untranscribed        # speech-level audio with no word under it
    lc post_cut_check       # truncations, adjacent duplicates, immediate restarts, n-gram repeats
    lc capcheck             # caption glyph extents through libass on the delivered frame
    lc head_onset_check .   # head and tail must not clip the kept word
    lc gapcheck             # wordless gaps between kept words, word to word
    lc qc transcript --edit-dir . --video /dev/null    # the gate's own transcript scan

- **`post_cut_check` and `qc transcript` overlap but are not mirrors.** Their n-gram scans use the
  same distance windows. Only `post_cut_check` sees an adjacent duplicate («تمام. تمام،») and a
  two-word restart with no pause between; only `qc transcript` sees a reworded or cut-short restart
  after a pause the speaker made in the take (it measures that pause in the take, so the tightener's
  trimming cannot hide it) and a range edge landing inside an audible word. Run both. `lc render`
  runs both before it renders anything, and again after.
- **`untranscribed`** is the only check that reads the audio for what is NOT in the transcript.
  A murmur under the breath, or a removed filler ringing 0.3s past its measured end, ships as sound
  with no caption and nothing else can see it. It is advisory: it exits 0 and you judge each hit.
- **`waitbeats`** is the only check that reads a wait beat for meaning. "Busiest" is a proxy for
  "the tool working", and it can pick the moment a settings panel or a menu was opened. Cut the
  detour window as its own cut and rebuild. A cut with no long waits has nothing to show, and says so.
- **`gapcheck`** measures word to word with no audio threshold, so it cannot agree with the
  tightener by construction. It checks every gap between kept words, the lead-in before the first
  word and the tail after the last. A flagged gap that sounds loud is a murmur, not silence: run
  `untranscribed`.
- **`capcheck`** renders the captions through libass on the delivered frame (the caption canvas
  scaled to `render.scale`), at each cue's midpoint, and reports how close the widest lines come to
  the edges. It is the gate's caption-pixel pass without a render in front of it.
- **`head_onset_check`** reads the first and last 1.2s of the cut against the take's speech level.
  It can miss a soft final word more than 15 dB below the loudest speech, so listen to the tail too.

Two secondary tools are not in the main order: `delivered_silence` (dead-air sweep on the assembled
audio, before loudness normalisation) and `tighten` (an older silence-ceiling enforcer). Both assume
a single take.

Then fix what they found and `lc rebuild`. Changing a cut invalidates every downstream artifact,
including `master.ass`, and `lc render` refuses a caption file older than the EDL.

## Accepting a finding in writing

Some findings are correct and deliberate: a parallel list that repeats its opener, a word said
twice on purpose. Those go in `edit/qc-accept.json`, a JSON array where every entry has a `phrase`
and a written `reason`. An entry without a reason stops both checks.

    [{"phrase": "ممتاز. ممتاز،",
      "reason": "2026-09-22: two different confirmations, one per step; both on screen"},
     {"phrase": "the settings panel",
      "reason": "2026-09-22: parallel list, open the settings panel / close the settings panel"}]

How the phrase has to be written depends on the check that found it. The gate (`qc`) compares after
normalising, so diacritics, hamza forms, case and punctuation do not matter to it; `post_cut_check`
compares the text exactly as transcribed. Write the phrase as transcribed and both are satisfied:

| Finding | Write the phrase as |
|---|---|
| Truncated word | the token exactly as the transcript has it, dashes included |
| Adjacent duplicate (`post_cut_check`) | the two tokens exactly, punctuation included, one space between |
| Immediate two-word restart (`post_cut_check`) | the two-word phrase exactly |
| N-gram repeat | the repeated run as the transcript spells it; at least its first two words must match |
| Restart across a pause (`qc`) | the words the finding prints, in its order |
| Black bar on an edge (`qc` video pass) | `black bar on left edge` or `black bar on top edge` |

An accept is a judgement, never a loosened threshold. Nothing else has an accept path: a range edge
inside an audible word, the caption checks, loudness, dead air, sync, duration and resolution can
only be fixed.

## Captions

Style lives in `edit/project.json` under `captions`; the take's own vocabulary lives in
`edit/captions_project.py`:

- **`CORRECTIONS`** is a list of `("heard", "actual")` pairs. They are SUBSTRING replacements
  applied to each cue, so `("pro", "pilot")` would also turn "project" into "pilotject": make each
  pair long enough to be unambiguous. The screen is the ground truth for a Latin token, not the ear.
  A recogniser renders an unfamiliar product or UI word as the nearest common English word, and both
  readings sound right on replay. Grab the frame at the token's timestamp and read the UI. This is
  how "the pro cover" became "the pilot cover" and "either gap" became "neither gap".
- **`NO_SPLIT`** lists phrases that must stay inside one cue, written as the recogniser spelled them
  (matching runs before the corrections). It matches when a cue ENDS with the start of the phrase,
  so a phrase whose first word is common can hold cues open: keep entries specific.

Cue rules: a cue breaks at sentence-ending punctuation, at `max_chars_per_line × max_lines`
characters, or at a pause of 0.55s; it never crosses a cut; it never ends on an Arabic article
such as «الـ»; a `NO_SPLIT` phrase stays on one line; a cue lasts at most 7s, and at least 0.55s
unless the next cue starts sooner. The per-line
character limit is a target, not a hard cap, which is why `capcheck` and the gate's pixel pass
exist. After any change, grep the OUTPUT for the thing you were fixing, not the source for the line
you added, and check that no cue exceeds 7 seconds (a long cue is a swallowed-silence bug).

`render.fps` in `project.json` is what the caption builder compensates for: ffmpeg emits
`ceil(dur × fps)` frames per segment, so the rendered timeline runs longer than the EDL by up to one
frame per join, and captions timed on raw EDL offsets drift progressively early. The builder stamps
the fps into `master.ass`, and `lc render` refuses when the stamp and the render disagree.
