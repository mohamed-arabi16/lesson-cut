# House rules

## The practice

Every correction the operator gives is permanent and applies to every future piece of that kind,
unless they say it is a one-off. They should never have to give the same note twice.

When they ask for something to be changed, added or removed:

1. **Fix the artifact** they are looking at.
2. **Write the rule down the same session**, in the project's own `house-rules.md` (or one file for
   all projects, which is better once there is more than one). Each entry records three things:
   what they said, what was actually wrong, and the generalised rule. All three matter: the words
   alone are ambiguous a month later, and the fix alone does not generalise.
3. **Generalise it.** A note about one asset is a rule about all assets of that type.
4. **Automate it where it can be automated** (a check, a builder change, a refusal in a script) and
   mark it as automated. Rules that depend on remembering will eventually be forgotten. Most of the
   checks in this plugin started as a note someone gave once.
5. **Read the ledger before starting the next piece**, and again before any final render. A ledger
   is a pre-flight checklist, not an archive.

Root-cause every complaint before fixing it. When the note is non-technical ("looks badly
compressed", "feels like AI", "the caption is faster than my voice"), find the actual mechanism and
fix that. Nudging parameters produces another round of the same feedback. That last example was a
real one, and the mechanism turned out to be frame quantisation accumulating one frame per join,
not a constant offset anyone could tune out.

## The rules that are physics

These are not taste and they do not vary by operator. They are in this file because a new install
starts with an empty ledger, and these were expensive enough to be worth shipping.

**Boundaries and cuts**

- A cut edge belongs in silence, never inside a word. Use the MEASURED audible extents, not the
  recogniser's logged spans: a recogniser pads a token's end with silence, so a boundary that looks
  clean in the transcript can restore seconds of dead air or clip a syllable.
- Pad an edge by `min(0.03, gap/2)`. A fixed 30 ms pad lands inside a removed word wherever two
  words abut, and 20 ms gaps are routine.
- Union overlapping findings by WORD INDEX, not by time. Two readers' versions of one cut must
  become one cut before the builder sees them.
- Cut the whole abandoned attempt, back to where the attempt began, not just its last broken word.
  Cutting only the truncation leaves the words in front of it stranded or doubled across the join.
- A head cut ends at the first kept word's onset minus 0.25s. A recogniser's `start` runs about
  110 ms late, and cutting to it clips the first syllable the viewer hears.
- A cut that removes speech has both edges pinned. Left free, the builder moves each edge to the
  nearest quiet point, which can shrink the cut to nothing: it prints SKIPPED, and a skipped cut is a
  cut that did not happen. Read every SKIPPED line.
- The tightener must measure raw gaps. Run it over an EDL that already has its own trims in it and
  it writes an empty list, and the next build restores all the dead air. Rebuild the chain as one
  unit, never step by step.

**Picture and sound**

- The offset between a take's audio and its picture is a property of the recording rig, not of
  the tool. Measure it once per rig by eye at a hard sound; never inherit someone else's number.
- A QC gate that compares stream start times cannot see a wrong offset. Look.

**Captions**

- FontSize is a fraction of the authoring canvas, not of the delivered frame. Never rescale the
  style constants per project; change the canvas instead.
- The caption builder's frame rate must equal the render's. A mismatch makes cues drift early by
  one frame per join, which is invisible at six joins and over a second at eighty.
- The screen is the ground truth for an unfamiliar token, not the ear.
- Verify captions in the DELIVERED pixels. An `.ass` file that looks right proves nothing about
  what the render burned in.

**Process**

- Run the checks that read only the transcript BEFORE the render. They cost seconds; the render
  costs an hour.
- One ffmpeg at a time, matched by process name (`pgrep -x ffmpeg`). Matching the full command line
  makes a script wait on itself forever.
- An accept is a written judgement with a measurement, never a loosened threshold, and its key must
  match exactly what the check matched.
- Sweep the class, not the instance. The moment one instance of a mechanical defect is found,
  enumerate every instance across the timeline and fix them together.
- Never reduce resolution to make a file smaller. Raise the CRF. The distinction matters and the
  words sound alike. The render scale is the source's LONG edge; taking the width shrinks a portrait
  take.
