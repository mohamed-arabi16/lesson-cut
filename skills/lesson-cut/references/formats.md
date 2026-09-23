# Formats: what transfers, what must be re-derived

The cutting is the same craft everywhere. The animation, the caption, the positioning and the ratio
are not. This file draws that line, so a lesson's numbers never get applied to a short vertical
video and a Reel's treatment never lands on a lesson.

## Transfers to every format

The judgement, unchanged:

- Keep the last complete attempt; cut the abandoned one back to where the attempt began.
- Cut a truncated word rather than captioning it.
- The re-coverage test for a spoken "delete this".
- One idea lands as many times as the script asks for, and no more.
- Trim every wordless gap, not just the long ones.
- Read the DELIVERED cut end to end before calling it done, holding the three questions.
- Verify a Latin token against the screen, not the ear.
- Prove the artifact that ships, not the input to the step that makes it.
- A correction becomes a written rule the same session.

The tool chain also transfers: `measure_tokens`, `mkcuts`, `build_edl`, `tighten_gaps`,
`post_cut_check`, `untranscribed`, `waitbeats`, `delivered_read`, `qc`. They are format-agnostic;
they read an EDL and a transcript.

## Does not transfer

Apart from "never downscaled" in the Frame row, which is a non-negotiable for every format (see
SKILL.md), everything in this table is a default, not a rule. The caption rows are the two presets
the plugin ships, tuned on the recordings it was built on; they are a starting point to check
against your own frame, and `edit/project.json` is where you change them. The length, graphics and music rows
are one house style, written down so the difference between the formats is visible: replace them
with yours. The plugin adds no graphics and no music itself.

| | Landscape lesson (`course-landscape`, the default preset) | Short vertical (`reel-portrait`: Reel, Short, TikTok) |
|---|---|---|
| Frame | Landscape, the source's own 4K or 1080p, never downscaled | Portrait, at the source's own resolution (1080x1920 for a typical phone take), never downscaled. Nothing in the plugin reframes a landscape take, so crop it to portrait before `lc init` |
| Caption canvas | Authored at 2560x1440, FontSize 72 (5% of height), Outline 4.4, Shadow 0.4, MarginV about 80, max ~23 chars/line | Authored at 1080x1920, FontSize 66, Outline 4.0, Shadow 1.2, MarginV 420, max ~25 chars/line |
| Why the numbers differ | Captions sit near the bottom edge of a dense UI recording; a heavy shadow reads as too dark over screen content | MarginV 420 clears the app's bottom UI; the shadow carries the text over busy footage |
| Length (house style) | Whatever the script sets | Usually seconds to a couple of minutes, with the hook in the first three seconds |
| Graphics (house style) | None: the screen is the content | Whatever your brand uses. One example: titles and numbered treatments for spoken enumerations, timed to the payoff word |
| Music (house style) | None | Your call. One example: a low bed under dialogue |

`lc init --profile reel-portrait` writes the second column's caption numbers into `project.json`,
and `init` always takes the render scale from the source's LONG edge, so a 1080x1920 take renders
at 1080x1920. The canvas keeps the preset's height and takes its width from the source's aspect
ratio, so a 1.54:1 recording gets a 2218x1440 canvas rather than a 16:9 one stretched onto it.
`capcheck` measures on the delivered frame of whichever canvas the project uses.

The caption geometry is the trap, and it is worth being explicit about why. FontSize is a fraction
of the AUTHORING canvas, not of the delivered frame: libass scales an ASS from its PlayRes up to
the real frame, so the same FontSize means a different apparent size on a different canvas. MarginV
was calibrated against one specific app's chrome. Applying the portrait numbers to a landscape
frame puts the captions "way in the middle" of the picture; applying the landscape numbers to a
vertical video puts them under the app's UI. Both sets are correct only for their own canvas, and
neither converts into the other by arithmetic.

## Camera pieces inside a course

Same skill, three differences worth holding:

- A 1080p camera with no larger original ships at native 1080p. Upscaling adds no detail.
- Camera footage wants CRF 23 (`lc init --crf 23`, or `render.crf` in `project.json`); screen
  recordings keep the default, 18.
- When the speaker is not the person who wrote the script, a scripted beat missing from THEIR take
  is their choice, not a finding. Keep running the coverage check, because it still catches a beat
  the CUT dropped, but an absence in the source is not reported.
