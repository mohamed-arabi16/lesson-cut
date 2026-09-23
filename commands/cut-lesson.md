---
name: cut-lesson
description: Edit a recorded lesson end to end - intake, editorial read, cut, captions, gates, render
---

Edit a recorded take into a finished lesson, following the `lesson-cut` skill.

Argument (optional): the path to the raw take, or the project directory if one already exists.
If nothing is given, ask which file to edit, or wait for it if the operator says it is still
exporting.

Work through the skill's eight phases in order and read each phase's reference file when you reach
it, not before. There is no `lc` on the PATH: `lc` in the skill and below is short for
`"${CLAUDE_PLUGIN_ROOT}/scripts/lc"`, and every shell command spells out that full path, in double
quotes. The things most often skipped, in the order they bite:

1. `"${CLAUDE_PLUGIN_ROOT}/scripts/lc" doctor` if this machine has not run the toolchain before.
2. The editorial read is four passes, not one: window readers, a structure reader, an adversarial
   verifier per reader, and a completeness critic. The last two contribute the final 10 to 20
   percent of the cut list.
3. Sweep the standalone fillers as their own pass. They were about a fifth of the cut list on the
   lesson this was built from, and they are invisible when you are reading for structure.
4. Paste mkcuts' tuples whole, run `"${CLAUDE_PLUGIN_ROOT}/scripts/lc" rebuild`, and read every
   SKIPPED line it prints.
5. Run every pre-render check. Each one exists because the others missed something.
6. Read the delivered cut end to end as prose before rendering.
7. Check lip sync by eye once; the gate cannot see a wrong `render.av_offset_s`.

Stop at a rendered, gated file and a report. Nothing ships unless the operator says so.
