// Editorial read for a recorded lesson: window readers + a structure reader, each adversarially
// verified, then a completeness critic over the survivors.
//
// Fill the constants below and pass this to the Workflow tool. Windows are derived from DUR, so a
// 40 minute take gets 4 readers and an 80 minute one gets 8. Returns the structure reader's beat
// map, the surviving cuts (each carrying its verifier's note), and the critic's conflicts,
// wrong_cuts and missed items. The surviving cuts use the keys lc mkcuts accepts
// (first_removed_word_start, first_kept_word_start, reason), so once the critic's lists are read
// and resolved they can be written to a JSON file and converted directly.
//
// Why this shape: local stumbles need line-by-line attention and structural repeats need the whole
// take in view, and one reader cannot hold both. The verifier exists because a reader that proposes
// a cut is the wrong party to judge whether it loses content. The critic exists because cuts that
// are each correct can still combine into a broken join.

export const meta = {
  name: 'lesson-editorial-read',
  description: 'Read a recorded lesson take against its script and propose verified content cuts',
  phases: [
    { title: 'Read', detail: 'window readers + whole-take structure reader' },
    { title: 'Verify', detail: 'adversarial check of every proposed cut' },
    { title: 'Critique', detail: 'completeness critic over the simulated delivered transcript' },
  ],
}

const PROJ = '<project dir>'                 // the dir holding take1.mov and edit/
const EDIT = `${PROJ}/edit`
const SCRATCH = '<scratch dir>'              // holds the FILLED cut-brief.md and the readers' frames
const TAKE = '<take1.mov or take1.mp4>'      // the source's name inside the project
const SCRIPT = '<path to the shooting script>'
const LC = '<the full lc path SKILL.md gives>' // absolute; the prompts below quote it
const DUR = 0                                // source seconds

const COMMON = `
Read the editorial brief FIRST and follow it exactly: ${SCRATCH}/cut-brief.md
Project: ${PROJ} (source ${TAKE}). Edit dir: ${EDIT}. Shooting script: ${SCRIPT}
Read-only on the project: never modify a file under ${PROJ}.
Tools: ${EDIT}/transcript_lines.txt (utterances), and for word level with measured audible spans:
  "${LC}" --project "${PROJ}" words <from_s> <to_s>
A frame whenever the screen decides the question (mkdir -p "${SCRATCH}/frames" first):
  ffmpeg -v error -y -ss <t> -i "${PROJ}/${TAKE}" -frames:v 1 -vf scale=1600:-1 "${SCRATCH}/frames/<n>.jpg"
The raw take is ${DUR}s. Cut to the script's target, but never at the cost of an idea delivered
nowhere else.
`

const FINDING = {
  type: 'object',
  properties: {
    id: { type: 'string' },
    kind: { type: 'string', enum: ['false_start', 'truncation', 'editor_instruction', 'repeat', 'script_redundancy', 'doubled_word', 'filler', 'failed_action', 'self_talk', 'off_script', 'other'] },
    first_removed_word_start: { type: 'number' },
    first_kept_word_start: { type: 'number' },
    last_kept_word_before: { type: 'string' },
    first_kept_word_after: { type: 'string' },
    removed_text: { type: 'string' },
    reason: { type: 'string' },
    idea_loss_check: { type: 'string', description: 'where each removed idea is re-delivered (time), or why nothing is lost' },
    confidence: { type: 'string', enum: ['high', 'medium', 'low'] },
  },
  required: ['id', 'kind', 'first_removed_word_start', 'first_kept_word_start', 'removed_text', 'reason', 'idea_loss_check', 'confidence'],
}
// Flags (something the picture carries that no cut can fix) are kept apart from
// cuts, so the surviving list can go to lc mkcuts without turning a flag into a cut.
const FLAG = { type: 'object', properties: { at_s: { type: 'number' }, what: { type: 'string' }, why_no_cut: { type: 'string' } }, required: ['at_s', 'what', 'why_no_cut'] }
const FINDINGS = { type: 'object', properties: { findings: { type: 'array', items: FINDING }, flags: { type: 'array', items: FLAG }, notes: { type: 'string' } }, required: ['findings', 'flags', 'notes'] }
const STRUCT = {
  type: 'object',
  properties: {
    beats: { type: 'array', items: { type: 'object', properties: { name: { type: 'string' }, source_from: { type: 'number' }, source_to: { type: 'number' }, summary: { type: 'string' }, keep_verdict: { type: 'string' } }, required: ['name', 'source_from', 'source_to', 'summary', 'keep_verdict'] } },
    findings: { type: 'array', items: FINDING },
    flags: { type: 'array', items: FLAG },
    script_redundancy: { type: 'string' },
    notes: { type: 'string' },
  },
  required: ['beats', 'findings', 'flags', 'script_redundancy', 'notes'],
}
const VERDICTS = {
  type: 'object',
  properties: {
    verdicts: { type: 'array', items: { type: 'object', properties: { id: { type: 'string' }, verdict: { type: 'string', enum: ['confirm', 'reject', 'adjust'] }, first_removed_word_start: { type: 'number' }, first_kept_word_start: { type: 'number' }, removed_text: { type: 'string' }, note: { type: 'string' } }, required: ['id', 'verdict', 'first_removed_word_start', 'first_kept_word_start', 'removed_text', 'note'] } },
    missed: { type: 'array', items: FINDING },
  },
  required: ['verdicts', 'missed'],
}

const W = 600
const windows = []
for (let i = 0; i * W < DUR; i++) {
  const from = i * W, to = Math.min(DUR, (i + 1) * W)
  windows.push({ id: `W${i + 1}`, from, to, ctxFrom: Math.max(0, from - 90), ctxTo: Math.min(DUR, to + 90) })
}
const items = [{ id: 'STRUCT', structure: true }, ...windows]

phase('Read')
const results = await pipeline(
  items,
  (it) => it.structure
    ? agent(`${COMMON}
You are the WHOLE-TAKE STRUCTURE reader. Read the ENTIRE transcript and the script.
1. Map the take onto the script's beats with source times and a keep verdict per beat.
2. Find what a 10-minute window cannot see: a section redone later, the same point landing across
   the take, off-script tangents, a long silent stretch that gets summarised afterwards, and the
   material any spoken editor instruction refers to (write out the re-coverage test in full).
3. Put in 'flags' (never in findings) anything the picture carries that no cut can fix: a claim
   the screen contradicts, a step the script forbids.
Ids S-01, S-02, ...`, { label: 'read:structure', phase: 'Read', schema: STRUCT })
    : agent(`${COMMON}
You are window reader ${it.id}, owning ${it.from}s to ${it.to}s: report only cuts whose first
removed word falls in that window. Read context from ${it.ctxFrom}s to ${it.ctxTo}s, and anything
else you need to judge re-coverage.
Go line by line. For every utterance ask, in order: does it NOT make sense, does it still NEED
deleting, is it REPEATED. Look for abandoned attempts and their restarts, truncations, doubled
words, standalone fillers, screen-hunting self-talk, reading aloud something the speaker then
re-says properly, prompts dictated twice (check the frames for which one landed), failed actions,
and spoken editor instructions. Anything the picture carries that no cut can fix goes in
'flags', never in findings.
Ids ${it.id}-01, ${it.id}-02, ...`, { label: `read:${it.id}`, phase: 'Read', schema: FINDINGS }),
  (res, it) => {
    if (!res) return null
    const f = res.findings || []
    if (!f.length) return { item: it, res, ver: { verdicts: [], missed: [] } }
    return agent(`${COMMON}
You are an ADVERSARIAL VERIFIER for ${it.structure ? 'the structure reader' : 'window ' + it.id}.
For EACH proposed cut, try to REFUTE it:
(a) does it remove an idea delivered nowhere else (content loss means reject, or adjust to keep it);
(b) is the kept side the complete, correct take, or is the removed span the better one;
(c) is this really a repeat, or a continuation / parallel list / a teaching beat the script asks for;
(d) are the boundaries right: the first removed word must be where the attempt BEGAN, and the join
    must leave no fragment stranded and no word doubled. Correct the numbers (verdict=adjust);
(e) for an editor instruction: is it aimed at the editor, and does the scope follow re-coverage?
Use the frames. Default to reject when a cut would lose content and you are unsure. Add to 'missed'
any clear cut in the same window the reader overlooked, and sweep specifically for standalone
fillers, which readers concentrating on structure walk past.
Proposed cuts:
${JSON.stringify(f, null, 1)}
Reader notes: ${res.notes || ''}`, { label: `verify:${it.id}`, phase: 'Verify', schema: VERDICTS })
      .then(ver => ({ item: it, res, ver }))
  },
)

const good = results.filter(Boolean)
const surviving = []
for (const r of good) {
  const byId = {}
  for (const v of (r.ver?.verdicts || [])) byId[v.id] = v
  for (const f of (r.res.findings || [])) {
    const v = byId[f.id]
    if (v?.verdict === 'reject') continue      // filter by VERDICT, never by the reader's own label
    const m = { ...f }
    if (v?.verdict === 'adjust') { m.first_removed_word_start = v.first_removed_word_start; m.first_kept_word_start = v.first_kept_word_start; m.removed_text = v.removed_text }
    m.verifier = v ? `${v.verdict}: ${v.note}` : 'not verified'
    m.source_reader = r.item.id
    surviving.push(m)
  }
  for (const m of (r.ver?.missed || [])) surviving.push({ ...m, verifier: 'added by verifier', source_reader: r.item.id })
}
surviving.sort((a, b) => a.first_removed_word_start - b.first_removed_word_start)
log(`${surviving.length} surviving cuts from ${good.length} readers`)

phase('Critique')
const CRIT = {
  type: 'object',
  properties: {
    missed: { type: 'array', items: FINDING },
    conflicts: { type: 'array', items: { type: 'string' } },
    wrong_cuts: { type: 'array', items: { type: 'string' } },
    delivered_estimate_s: { type: 'number' },
    notes: { type: 'string' },
  },
  required: ['missed', 'conflicts', 'wrong_cuts', 'delivered_estimate_s', 'notes'],
}
const critic = await agent(`${COMMON}
You are the COMPLETENESS CRITIC. Write the surviving cuts below to ${SCRATCH}/surviving_cuts.json,
then write a small python script that removes every word whose start lies in a cut's
[first_removed_word_start, first_kept_word_start) and prints the DELIVERED transcript with a join
marker. Read that end to end holding the three questions: does anything not make sense, does
anything still need deleting, is anything repeated.
Then report: cuts that would combine into a broken join or whose rationale assumed a neighbour
another cut removes (conflicts); cuts that lose an idea delivered nowhere else (wrong_cuts, with
the id and reason); anything missed (ids C-01...); and the delivered duration estimate against the
script's target, with the largest additional trims that would lose no idea.
SURVIVING CUTS:
${JSON.stringify(surviving, null, 1)}`, { label: 'critic', phase: 'Critique', schema: CRIT })

const flags = good.flatMap(r => (r.res.flags || []).map(fl => ({ ...fl, source_reader: r.item.id })))
return { structure: (good.find(r => r.item.structure) || {}).res || null, surviving, flags, critic }
