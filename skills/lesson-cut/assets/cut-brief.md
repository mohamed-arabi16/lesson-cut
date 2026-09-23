# Editorial brief (template)

Fill every bracketed field, save the filled copy as `cut-brief.md` in the scratch directory the
readers share, and point every reader and verifier at it. It is deliberately concrete about what
gets cut, because a vague brief produces vague findings.

Fields: [PIECE NAME], [language and register], [screen recording / camera], [OPERATOR'S BRIEF],
[PROJ] (the project directory), [EDIT] (its edit/ directory), [LC] (the full path to the plugin's
scripts/lc, as SKILL.md gives it), [SCRATCH] (the shared scratch directory this brief is saved in),
[SCRIPT PATH], and the beat list at the end. Keep the double quotes around the paths in the
commands below: a path with a space in it breaks without them.

---

## Editorial brief: [PIECE NAME] ([language and register])

You are helping cut a raw [screen recording / camera] take. The goal, unless the operator's brief
below says otherwise: precise cuts, no dead air, every repeated sentence and repeated section
removed without losing an idea, so the piece reads as one clean take from the first shot. Understand
each segment before deciding where a cut starts and ends.

The operator's brief for this piece:

> [OPERATOR'S BRIEF: what they want from this cut, in their own words. Say whether the take
> contains spoken instructions to the editor ("delete that", "again") and in which language, and
> anything that must stay whatever it sounds like. If there is nothing to add, write "none".]

Silence is trimmed mechanically afterwards (wordless gaps over about 0.7s are cut down to a short
beat; waits over 4s keep 0.9s of the busiest picture). **Do not list plain pauses.** Your job is the spoken content:
what must go so the piece reads as one clean take.

### Files

- Transcript, one utterance per line: `[EDIT]/transcript_lines.txt` (`[start-end] (silence after it) text`, source seconds)
- Word level with measured audible spans: `"[LC]" --project "[PROJ]" words <from_s> <to_s>`
- The shooting script, which is the contract: `[SCRIPT PATH]`
- A frame, whenever the screen decides the question (the take is `take1.mov` or `take1.mp4`), one
  file per timestamp and never inside the project (run `mkdir -p "[SCRATCH]/frames"` once first):
  `ffmpeg -v error -y -ss <t> -i "[PROJ]"/take1.* -frames:v 1 -vf scale=1600:-1 "[SCRATCH]/frames/<t>.jpg"`
  then read it

### What gets cut

1. **Abandoned attempts and retakes.** Keep the last complete attempt. The unit is the whole
   abandoned attempt, back to where it began, not just its last broken word: cutting only the
   truncated token leaves the words in front of it stranded or doubled across the join.
2. **Truncated words**, with or without a trailing marker from the recogniser.
3. **Spoken instructions to the editor** ("delete this", "scrap that", "again", "sorry", «احذف»,
   «امسح», «إعادة»). Cut the instruction AND its referent, with the scope bounded by the
   re-coverage test: list the ideas between the previous clean point and the instruction, search
   forward for each one being delivered again, cut back only to the earliest idea that IS
   re-covered, and keep anything that is not. Check first whether the speaker is talking to the
   editor at all, or editing something on screen.
4. **Repeated sentences and sections.** The same point twice, the same UI step narrated twice, the
   same verdict in four wordings. Test: does the second instance CONTINUE the sentence (a parallel
   list, anaphora: keep both) or REPLACE the first attempt (cut the first)?
5. **Never cut the good take.** If the removed span restates what is kept before it, the removed
   span is the later attempt, and the later attempt is usually the correction.
6. **A point that lands more often than the script asks for.** The script is the authority on how
   often something lands, not whether a repeat "sounds deliberate".
7. **Doubled words and stutters.**
8. **Standalone fillers, swept deliberately as their own pass.** A lone "OK", "right", "so",
   «تمام», «آآآ» or "um" between two silences is a cut. Expect dozens across an hour and list every
   one: walk the transcript once looking for nothing else, because they are easy to read past
   individually and together they are what makes the piece feel tight.
9. **Self-talk while hunting the screen**, and reading something aloud that the speaker then says
   properly in their own words.
10. **A half-read of an on-screen line** that stops partway and leads nowhere. The screen still
   shows the full line; the spoken fragment is noise.
11. **A garbled delivery**, as distinct from a garbled transcript. If the screen shows the real
   words and they were said cleanly, it is a caption correction, not a cut. If the delivery itself
   is unintelligible, it cannot be captioned honestly, so cut it. Decide it mechanically: read the
   screen at that timestamp and run a second transcription over the span. Matching the screen means
   caption fix; both readings disagreeing with the screen means the delivery is broken, so cut.
12. **Failed on-screen actions and their retries** (a dictation that never landed, a click that did
   nothing, a command that errored). Keep the attempt that worked; check the frames to see which.

### What must NOT be cut

- An idea delivered nowhere else.
- The corrections the speaker makes to the tool on camera: in a build lesson, that IS the lesson.
- Parallel constructions and lists that continue a sentence.
- A prompt being dictated: the viewer needs to see and hear it. A prompt dictated twice is a failed
  action, and the frames decide which take reached the input box.

### Output discipline

- Times in SOURCE seconds to 2 decimals, taken from the transcript files.
- For each cut give: the first removed word's start, the first KEPT word's start after the cut, the
  words either side, the exact removed text, the reason, and an explicit idea-loss check naming
  where each removed idea is re-delivered (with a time) or why nothing is lost.
- Quote the transcript's own wording exactly.
- Either it is a cut with a reason, or it is not a cut. A vague "maybe trim here" helps nobody.
- Anything the PICTURE carries that a cut cannot fix (a claim the screen contradicts, a step the
  script forbids) is a FLAG for the operator, not a cut.

### The script's beats and target

[PASTE THE BEAT LIST AND TARGET DURATION FROM THE SHOOTING SCRIPT]

Also flag, without cutting, anything said on camera that contradicts the script's own accuracy
guards.
