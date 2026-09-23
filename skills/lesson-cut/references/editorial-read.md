# The editorial read

Two reads decide the quality of a cut. The first happens before any cut exists and produces the
decisions. The second happens after the cut is built and reads what the cut actually says.

## Read one: deciding the cuts

A 60 to 90 minute take holds 150 to 250 real cuts. Reading it once end to end and keeping all of
them in mind does not work: local stumbles need line-by-line attention, structural repeats need the
whole take in view, and the two kinds of attention crowd each other out.

Split it four ways:

1. **Window readers.** One per 10 minutes of source, each owning its window and allowed to read
   context either side. They find the local material: abandoned attempts, truncations, doubled
   words, fillers, self-talk, failed actions, prompts dictated twice, editor instructions.
2. **A structure reader** over the whole transcript plus the script. It finds what a window cannot
   see: a section redone later, a point landing more often than the script asks, an off-script
   tangent, the beat map with a keep or trim verdict per beat.
3. **An adversarial verifier per reader.** Its job is to REFUTE each proposed cut: does it remove
   an idea delivered nowhere else, is the kept side really the complete take, is this a
   continuation rather than a restart, are the boundaries on the attempt rather than on its last
   broken word. It confirms, rejects or adjusts, and can add what its reader missed. Default to
   reject when a cut would lose content and the case is unclear.
4. **A completeness critic** over the surviving list. It applies the cuts to the transcript, reads
   the result end to end, and looks for what the per-window view cannot produce: two cuts that
   combine into a broken join, a cut whose rationale assumed a neighbour that another cut removed,
   a dangling reference, and the delivered length estimate.

The plugin ships the agents for roles 1, 3 and 4 (`lesson-window-reader`, `lesson-cut-verifier`,
`lesson-cut-critic`) and a brief template at `assets/cut-brief.md`. Fill its bracketed fields,
save the filled copy as `cut-brief.md` in a scratch directory, and point every reader at it.
`assets/editorial-workflow.js` runs the whole read as one workflow when the harness supports it:
set the constants at its top, including the same scratch directory, and its `surviving` list can be
written to a file and passed straight to `lc mkcuts`. On a short piece, or when workflows are not
available, do the same four passes yourself in sequence: the structure is what matters, not the
parallelism.

**Expect the verifier and the critic to ADD cuts, not only to remove them.** In practice they
contribute the last 10 to 20 percent, and it is nearly all small: the standalone fillers and
signposts a reader concentrating on structure walks past. A single pass over a window reliably
finds the retakes, the instructions and the repeats, and reliably under-catches these. That is the
reason for the second and third passes, so leave the `missed` lists switched on and read them.

**Give readers the frames.** Many decisions are visual and cannot be made from a transcript: which
dictation reached the input box, whether an instruction refers to the screen or to the editor,
whether a click did anything. Tell them to grab frames and look.

Word-level lookup in a window, which is what a reader needs to place an edge between two specific
words:

    lc words <from_s> <to_s>          # lc is the full, quoted lc path SKILL.md gives

It prints each word's logged span, its measured span, the gap before it, and its text. Decisions
are written with the logged start of the first removed word and of the first kept word.

### Turning findings into decisions

Each finding carries the first removed word and the first kept word, so the cut is expressed in the
transcript's own terms rather than in raw seconds.

Filter by **verdict**, never by the label a reader chose. On the lesson this skill was built from,
a confirmed cut was tagged `accuracy_flag` by its reader, a selection step dropped everything with
that tag, and the cut was lost until the delivered read caught it. Keep a written exclusion list:
every rejected finding with the reason, so the list can be re-derived and audited later.

Resolve conflicts explicitly. Two readers proposing overlapping versions of one cut is normal and
harmless (`mkcuts` unions them by word index). Two readers proposing ALTERNATIVE fixes is not:
applied together they remove both copies of a word, or leave a sentence without its verb. The
critic catches these; its `wrong_cuts` and `conflicts` lists are the ones to read first.

## Read two: the delivered cut

After the cut is built, generate the delivered text with every join marked and read it in order:

    lc delivered_read . > delivered_read.txt

Hold three questions, in this order: does anything **not make sense**, does anything **still need
deleting**, is anything **repeated**. A file that passes every automated gate can still be full of
things worth cutting, because a gate detects defects and cannot judge prose. On one lesson this
read found a batch of further cuts after a 6/6 green, including a long stretch of filler over a
half-read screen card and a verdict that landed four times in four wordings.

For a long piece the join markers dominate the file. A compact rendering (utterances, with a
`‖ cut: …` line only where speech was removed) is easier to read end to end, and seeing what each
join dropped is how a bad join gets noticed.

What to look for beyond the three questions:

- A join that reads fine but says something the screen contradicts.
- A reference to something a cut removed ("the instructions we already have here").
- A garbled reading that survived because no scanner defines it as a defect. If the audio is
  genuinely unintelligible it is not captionable: either cut it, or caption what the screen says.
- Numbering given out loud ("the second question") that no longer matches what the viewer sees.

Re-run this read after every cut-list change. It is cheap, and it is the only pass that sees what
the cut created.
