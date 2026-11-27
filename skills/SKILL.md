---
name: paper-notes
description: Read a research paper and produce section-aligned notes, a structured paper card, and claim-level evidence. Use for literature summaries, research findings, methods and conditions, limitations, or reusable knowledge points.
---

# Paper notes

Read the actual case materials and answer every required part of the task in the first build.
Use the paper's section order and the case's requested language. Keep quotations in the original language.
The runner uses Python 3 with PyMuPDF and numpy from requirements.txt. No network is needed at runtime.

## Run the workflow

Run this from the case environment. The skill is normally installed at /skills/weekly-skill.

```sh
PY=$(command -v python3 || command -v python)
for d in "${SKILL_DIR:-}" /skills/weekly-skill /app/submission /app/skills "$PWD"; do
  [ -f "$d/scripts/notes.py" ] && SKILL_DIR="$d" && break
done
notes() { "$PY" "$SKILL_DIR/scripts/notes.py" "$@"; }
notes init --case /input/case.json --work /app/work --out /app/output
# Read the case and digests, then fill /app/work/draft.json.
notes build --work /app/work
```

1. Use init's coverage checklist, output contract skeleton, source index, and outline for planning.
   Read the indicated task.md and case.json for all case-specific questions, fields, and output types.
2. Read digest.md for the primary paper and verify candidate passages from cues.json against the source.
   Prioritize the main paper. Use digest_S1.md and other indexed supplements for details or corroboration.
3. Fill draft.json in one pass. Keep the section IDs, map every requested contract field, and save.
4. Run build with the populated draft. Review result.json and notes.md for coverage and inline evidence.
   Fix obvious gaps or citation errors in one follow-up build if needed. Keep usable notes with warnings.

## Required coverage checklist

- Research question — identify the actual problem, scope, and objective.
- Method — state the design, procedure, comparison, and evaluation method.
- Data and experimental conditions — include relevant samples, splits, settings, metrics, units, and assumptions.
- Core findings and conclusion — answer each question with results, comparisons, and conditions for the conclusion.
- Limitations — capture the authors' stated limits and label any reader inference or unresolved uncertainty.
- Task-specific requirements — check every question and output_contract field from the case before finishing.

## Draft and evidence

- Put each distinct claim in an item with text and an a array of source anchors.
- Copy a short verbatim quote from the same block, using p3-b12: quoted words.
- For numbers, cite the row and value together, such as Table 2: Baseline 0.61. Include the metric and units in the claim.
- Use S1:: before a supplement anchor. Cite both sources for disagreements and explain the conflict.
- Keep card findings concise. Summarize each relevant section in paper order and link it to its own blocks.
- Use knowledge for reusable terms or findings requested by the case. Merge synonyms through aliases.
- Map contract fields with @card, @card.method, @sections, @knowledge, @notes_md, @evidence, or literal values.
  For a literal claim, put a beside its content so the builder can keep evidence inline.
- If the source lacks a requested fact, leave the draft field empty and record where you searched in unreported.
- If evidence is indirect or visual, keep a bounded statement and describe its uncertainty alongside the item.

## Worked example

Illustrative input. Suppose the case requests paper_card and the primary digest contains these blocks.

```text
[p1-b2] We test whether layout-aware ordering reduces paragraph errors.
[p2-b3] We compared column-aware and baseline ordering on 120 two-column pages.
[p3-b4] Paragraph-order accuracy was 95% for column-aware ordering and 82% for the baseline.
[p3-b7] We evaluated only English two-column articles.
```

In the generated draft, fill card and contract as follows. Use the actual outline IDs for section notes.

```json
{
  "card": {
    "research_question": {"text": "Does layout-aware ordering reduce paragraph errors?", "a": ["p1-b2: whether layout-aware ordering reduces paragraph errors"]},
    "method": {"text": "Compare column-aware ordering with baseline ordering.", "a": ["p2-b3: We compared column-aware and baseline ordering"]},
    "data": {"text": "120 pages", "a": ["p2-b3: on 120 two-column pages"]},
    "conditions": {"text": "Evaluation on two-column pages", "a": ["p2-b3: on 120 two-column pages"]},
    "main_findings": {"text": "Paragraph-order accuracy was 95% versus 82% for the baseline.", "a": ["p3-b4: Paragraph-order accuracy was 95% for column-aware ordering and 82% for the baseline."]},
    "conclusion": {"text": "Column-aware ordering improved accuracy on the evaluated pages.", "a": ["p3-b4: 95% for column-aware ordering and 82% for the baseline"]},
    "limitations": {"text": "The evaluation covered English two-column articles only.", "a": ["p3-b7: We evaluated only English two-column articles."]}
  },
  "contract": {"paper_card": "@card"}
}
```

After build, result.json has case_id and paper_card. The finding reads with its source excerpt,
page 3 and section name in the same item. For example:

```json
{
  "text": "Paragraph-order accuracy was 95% versus 82% for the baseline.",
  "anchors": [{"quote": "Paragraph-order accuracy was 95% for column-aware ordering and 82% for the baseline.",
               "page": 3, "section": "3 Results", "block_id": "p3-b4"}]
}
```

notes.md also prints the quotation next to the finding.

## Check the delivered files

- /app/output/result.json uses the exact case_id and output_contract keys.
- notes.md presents the paper card, ordered section notes, inline evidence, and uncertainty for review.
- verification.json contains run status, warnings, coverage gaps and detailed verification records.
- For a scanned or image-heavy page, inspect the rendered page and cite p2@x0,y0,x1,y1 plus the reading.
  Visual transcriptions remain reviewable. Use the original figure or table caption where it supports the claim.
- For long papers, use notes find "query words" --work /app/work to recover text beyond the digest.
- If the primary file cannot be read, use init's recorded failure. Supply a password only when the case provides it.
- When a check warns, verify the quoted text, metric, and section. Keep qualified findings with a usable source location.
