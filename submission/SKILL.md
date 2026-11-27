---
name: paper-notes
description: Turn a research paper (PDF, Markdown, plain text or Word .docx; optionally with supplementary files) into section-aligned, field-structured reading notes in which every key note points back to a verified place in the original (page, block, source line, table row, figure, supplement). Use when a task gives a paper and asks for a literature summary, structured notes, a paper card (research question, data, method, conditions, findings, conclusion, limitations), section summaries, a knowledge-point list, or notes "with sources/evidence". Scripts pick the primary paper, build the paper's own outline and an anchored digest, then check every note against the source (verbatim quote in the cited block, numbers present, anchor inside its section); notes that fail are kept out of the deliverable instead of blocking it. Handles scanned, encrypted, image-heavy, Chinese and long papers honestly.
---

# paper-notes (v1.2.0)

You write the notes; the scripts parse the paper, give you anchors, check every note and write all outputs.
**Three steps, 3-6 requests in total.** A valid `result.json` exists from step 1 on and is never made worse.

## Step 1 - setup + parse (one shell call)

```bash
PY=$(command -v python3 || command -v python); for d in "${SKILL_DIR:-}" /skills/weekly-skill /app/submission /app/skills /skills/* "$(pwd)"; do [ -f "$d/scripts/notes.py" ] && SKILL_DIR="$d" && break; done
"$PY" "$SKILL_DIR/scripts/notes.py" init --case /input/case.json --out /app/output --work /app/work && cat /app/work/digest.md
```
It prints `case_id`, `contract_fields`, `inputs` (roles: `primary`, `supplement=S1`), the paper's **outline**
(`s4 L2 3.1 Residual Learning pp3-3`) and then the digest: the paper by section, each paragraph prefixed by its
anchor `[p3-b12]` (text inputs: `[p1-b12 L40-44]`), plus WHERE TO LOOK, KEY TABLE ROWS (pre-checked anchors like
`Table 2: Ours 95.3`) and VISUAL PAGES. Also read `/input/task.md` if present (language, focus).
- Wrong primary? re-run init with `--primary FILE --force`. `parse_status: failed` (encrypted/corrupt): stop -
  result.json already says why. Long paper: the digest shortens late paragraphs; `N find "words"` searches.
- Later shell calls start with `. /app/work/env.sh;` (sets `N` = notes.py; e.g. `. /app/work/env.sh; N find "limitation"`).

## Step 2 - write the notes (one call, 2-3 files)

Every note item is `{"text": "your note", "a": ["p3-b12: 6-25 words copied verbatim from that block"]}`
(table: `"Table 2: row label value"`); a field holds one item or a list. Write e.g.
- `/app/work/part_card.json`: `{"card": {...}, "unreported": [...], "contract": {...}}`
  - card fields: `title, authors, research_question, data, method, conditions, main_findings, conclusion,
    limitations` (+ optional `year, venue, keywords, future_work`). `conditions` = what the conclusions depend on
    (assumptions, settings, data scope, hyper-parameters). Not in the paper -> leave it out and add
    `{"field": "card.limitations", "reason": "no limitation stated; searched Discussion (p15-16)"}` to `unreported`.
  - `contract`: map each `output_contract` field: `"@card"`, `"@card.<field>"`, `"@sections"`, `"@knowledge"`,
    `"@notes_md"`, `"@evidence"`, or a literal. Obvious names map themselves; `case_id` is always filled.
- `/app/work/part_sections.json`: `{"sections": [{"section_id": "s4", "purpose": .., "method": .., "results": ..,
  "conclusion": .., "transition": .., "key_points": [..]}, ...]}` - one per top-level outline section (id, number
  `"3.1"` or title accepted), anchored **inside that section**; sub-section notes count for the parent.
- `/app/work/part_knowledge.json`: `{"knowledge": [{"term", "aliases": [..], "kind", "definition", "section_id",
  "a": [..]}], "uncertainty": [..], "conflicts": [..]}` (conflicts: e.g. abstract vs table disagree - cite both).

Notes in the task's language; quotes verbatim in the source language; numbers as printed (60 亿 = 6 billion,
95% = 0.95 are accepted). Supplement facts: prefix the anchor `S1::`. Page image: `p2@x0,y0,x1,y1: what you read`.

## Step 3 - merge + check + write (one command)

```bash
. /app/work/env.sh; N build /app/work/part_card.json /app/work/part_sections.json /app/work/part_knowledge.json
```
Writes `/app/output/result.json` (all contract fields + `case_id`), `notes.md`, `paper_card.json/.csv`,
`knowledge_points.jsonl`, `verification.json`, and prints `status`, `reason`, `warnings`, `fix_these`.
- A part file that is not valid JSON is listed under `merge.rejected`; the others still merge (fences and
  trailing commas are repaired). Rewrite only that file and run the same command again.
- A note whose quote is not in the cited block, whose number is not in the cited text, or whose anchor does not
  exist is **left out of the notes** (kept in `verification.dropped_items`) - nothing unsupported is delivered.
- `status: success` = core notes delivered; warnings (dropped notes, a section without notes, unread image pages,
  type coercions) are recorded in `run_status.warnings`, not blocking. `partial` only if research_question /
  method / main_findings have no verified note, fewer than half of the top-level sections have notes, or a
  contract field has no mapping - `reason` says which. `failed` = unreadable input.
- **Optional, once:** if `fix_these` lists notes you can fix (copy the exact words from the digest), write them to
  `/app/work/part_fix.json` and run `N build /app/work/part_fix.json`. Then stop. Never edit result.json by hand.

## Anchor formats

`p3-b12: words` (block, best) · `L120-L131: words` (.md/.txt lines) · `Table 2: row value` · `Fig. 4: caption
words` · `Eq. 3` · `p2@x0,y0,x1,y1: reading` (stays needs_review) · `s4` (whole section, weak) · prefix `S1::`.
Review-only results (`relocated`, `quote_fuzzy`, figure/page-image readings) stay in the notes marked ⚠.

## Special inputs (handled by the scripts; say what is left in `uncertainty`)

Several files -> primary by role/key/name, others are S1, S2 (`digest_S1.md`). Scanned page -> image-only pseudo
section; cite `pN@bbox` or state it was not read. No headings -> page-based pseudo sections. Two columns ->
reading order restored. Equations/figures -> by number and caption only: do not invent curve values.
Chinese / non-English -> CJK-aware matching. Encrypted -> `failed` (`--password` only if the task gives one).

## Honesty rules

- Every note comes from text you read in the digest. Unknown -> `unreported` with a reason, never a guess.
- Keep the paraphrase close to its quote. Your own reading of limitations: start it with "reader's note:".
- Do not cite headers/footers for body claims; do not present supplement facts as main-paper facts.
