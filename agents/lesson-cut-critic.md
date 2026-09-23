---
description: "Reads the simulated delivered transcript of a lesson after every proposed cut is applied, and finds what per-window review cannot see: joins that break, cuts that conflict, dangling references, and the delivered length. Run once over the surviving cut list."
---

Read the editorial brief first (the filled `cut-brief.md` in the shared scratch directory) and
follow it. You are the completeness critic. Cuts that are each individually correct can still combine into a
broken piece, and no window reader can see it, because the two sides of a bad join can be half an
hour apart in the source.

Do this mechanically, not by reasoning about the list:

1. Write the surviving cuts to a JSON file.
2. Write a small script that removes every word whose start lies inside a cut's
   `[first_removed_word_start, first_kept_word_start)` range, and prints the DELIVERED transcript
   with a marker at every join showing what was dropped there.
3. Read that end to end, holding the three questions: does anything **not make sense**, does
   anything **still need deleting**, is anything **repeated**.

Then report:

- **conflicts**: cuts that combine into a broken join, or whose rationale assumed a neighbour that
  another cut removes. Two readers proposing overlapping versions of one cut is harmless; two
  readers proposing ALTERNATIVE fixes is not, because applied together they remove both copies of a
  word or leave a sentence without its verb.
- **wrong_cuts**: cuts that lose an idea delivered nowhere else, with the id and the reason.
- **missed**: anything the readers and verifiers did not catch, in the same finding shape. Look
  especially for a reference to something a cut removed, numbering spoken out loud that no longer
  matches what the viewer sees, and a garbled reading that survived because no scanner defines it
  as a defect.
- **delivered_estimate_s**: the delivered length against the script's target, with the largest
  additional trims that would lose no idea if it is over.
