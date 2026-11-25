---
name: paper-notes
description: Turn a research paper PDF into section-aligned, field-structured reading notes in which every key note points back to a verified place in the original (page, block, table row, figure, equation). Use when a task gives a paper PDF and asks for a literature summary, structured notes, a paper card (research question, data, method, conditions, findings, conclusion, limitations), section-by-section summaries, a knowledge-point list, or notes "with sources/evidence". Builds the paper's own outline (repairs missed or junk headings, lifts appendices), gives a reading digest with block anchors, then checks each note against the PDF text layer - quote verbatim in the cited block, anchor inside the section it summarises, every number in the note present in the cited text or table row, card fields filled or declared unreported, sections covered in the paper's order, duplicate terms merged and abbreviations checked. Handles scanned, encrypted, Chinese and long papers honestly.
---

# paper-notes (v1.0.0)

Goal: notes that **follow the paper's own structure**, **keep** research question / data / method /
conditions / findings / conclusion / limitations, can be **found back** in the PDF claim by claim, and are
**reusable** (same card fields for every paper, CSV/JSONL exports). You read and write the notes; the
scripts give you the outline and anchors and then check your notes mechanically.

`SKILL_DIR` = directory of this file (at evaluation `/skills/weekly-skill`). Python 3 + PyMuPDF (+ numpy). No network.
Budget-aware: the whole flow is ~6-12 model requests. **Save early** (init already writes a valid partial result).

## Workflow

1. **Init** (seconds):
   ```bash
   PY=$(command -v python3 || command -v python)
   for d in "${SKILL_DIR:-}" /skills/weekly-skill /app/submission /app/skills "$(pwd)"; do
     [ -f "$d/scripts/notes.py" ] && SKILL_DIR="$d" && break
   done
   "$PY" "$SKILL_DIR/scripts/notes.py" init --case /input/case.json --out /app/output --work /app/work
   ```
   Prints `case_id`, `contract_fields`, `parse_status`, the **outline** (`s4 L2 3.1 Residual Learning pp3-3`), and paths.
   Writes `/app/output/result.json` (status `partial`, every contract field null), `/app/work/digest.md`,
   `/app/work/cues.json`, `/app/work/outline.json`, `/app/work/draft.json`.
   If `parse_status` is `failed` (e.g. `encrypted`): stop, result.json already says why (use `--password` only if the task gives one).
2. **Read** `task.md` / `case.json` (language, required fields, focus), then `digest.md`: the paper in reading order,
   grouped by **the paper's sections**, every paragraph prefixed by its anchor `[p3-b12]`; tables/figures/equations
   listed under their section. `cues.json` = candidate sentences per card field (research_question, data, conditions,
   main_findings, limitations, ...) with anchors - a shortcut, not an answer: read the sentence before using it.
   More text: `"$PY" "$SKILL_DIR/scripts/notes.py" find "query words" [--section 3.2]` (prints paste-ready anchors);
   tables: `"$PY" "$SKILL_DIR/scripts/table_query.py" /app/output/parsed/<stem> --table "Table 2" --list`.
3. **Write `/app/work/draft.json`** (keep its shape; one file write). Every note item is
   `{"text": "your note", "a": ["p3-b12: 6-25 words copied verbatim from that block", "Table 2: ResNet-152 4.49"]}`;
   a field holds one item or a list.
   - `card`: the 13 unified fields (see README *Field dictionary*). Required: title, authors, research_question,
     data, method, conditions, main_findings, conclusion, limitations. Not in the paper -> leave null **and** add
     `{"field": "card.limitations", "reason": "no limitation stated; searched Discussion/Conclusion (p15-16)"}` to `unreported`.
     `conditions` = what the conclusions depend on (assumptions, settings, data scope, hyper-parameters).
   - `sections`: one entry per outline section (already listed, in paper order; do not reorder or invent ids).
     Fill `purpose`, `method`, `results`, `conclusion` where the section has them (null otherwise), `transition`
     = how it links to the previous/next section, `key_points` = list of items. Anchor each item **inside that section**.
     Every top-level section needs at least one note (or `"skip_reason"`); sub-sections count for their parent.
   - `knowledge`: concepts, terms, abbreviations, variables/symbols, methods, datasets, metrics, findings:
     `{"term", "aliases": [...], "kind", "definition", "section_id", "a": [...]}`. One entry per concept (aliases for synonyms).
   - `contract`: map **every** output_contract field: `"@card"`, `"@card.limitations"`, `"@sections"`, `"@knowledge"`,
     `"@notes_md"`, `"@evidence"`, or a literal value (objects inside may carry `"a"` anchors; they are checked too).
     Unmapped fields are auto-mapped by name when obvious (e.g. `limitations` -> `@card.limitations`), else reported.
   - `uncertainty`, `conflicts` (e.g. abstract vs table disagree - cite both): plain strings or objects.
   Notes in the task's language; quotes stay verbatim in the paper's language. Numbers exactly as printed.
4. **Build + verify**:
   ```bash
   "$PY" "$SKILL_DIR/scripts/notes.py" build --work /app/work
   ```
   Writes `/app/output/result.json`, `notes.md`, `paper_card.json`, `paper_card.csv`, `knowledge_points.jsonl`,
   `verification.json`; prints `fix_these` / `review` / `uncovered_sections` / `card_missing`.
5. **Fix and rebuild** (1-2 rounds). Fix every `fix_these` item; read `review` items.

| check (item status) | meaning | action |
|---|---|---|
| `quote_verbatim`, `quote_in_table`, `quote_in_caption`, `equation_exists` (verified) | anchor exists, quote is in it | done |
| `quote_in_neighbour_block` (verified) | quote is in the same paragraph/next block; anchor moved there | done |
| `relocated` (review) | quote not in the cited block but verbatim elsewhere; anchor moved | check the claim fits the new place |
| `quote_fuzzy` (review) | not verbatim; closest source sentence attached | copy the exact words |
| `quote_not_found` (failed) | no such text in the paper | fix quote/claim or drop it |
| `numbers_not_in_evidence:X` (failed) | a number in your note is not in the cited block/paragraph/table row | cite where X is printed, or correct X |
| `all anchors outside this section` (review) | a section note cites another section | anchor inside the section (or accept for `transition`) |
| `coarse_section_anchor`, `no_quote`, `table_exists`/`figure_exists` without quote | weak anchor | add a quote (table: row label + value) |
| `figure_reading_unverified`, `image_read_unverified` | your reading of a plot / page image | stays in review (honest) |
| `bbox_off_page`, `*_not_found`, `anchor_unparseable` (failed) | bad anchor | fix format (below) |

`status` = `success` only when no item failed, all required card fields are filled or declared unreported, every
top-level section is covered and every contract field is filled; else `partial` with the reason in `run_status`.
Never edit result.json by hand to change verdicts; change the draft and rebuild.

## Anchor formats

`p3-b12: verbatim words` (block, best) · `para14: words` · `Table 2` / `Table 2: row label value` (row-level check) ·
`Fig. 4` / `Fig. 4: caption words` · `Eq. 3` · `p2@x0,y0,x1,y1: what you read` (image-only page; bbox in PDF points) ·
`s4` (whole section, flagged coarse). Block ids: `p{page}-b{n}`; `p{page}-m{n}` removed header/footer, `p{page}-g{n}` text inside a figure.

## Special inputs

| Situation | What the scripts do | What you do |
|---|---|---|
| Encrypted / unreadable PDF | init: `status=failed`, reason in `run_status` | report; `--password PW` only if the task provides it |
| Scanned page (no text layer, no OCR) | pseudo section `[page N, image-only page]`, page image path + ink regions in digest | look at the image; anchors `pN@bbox: text`; all such items stay `needs_review`; say so in `uncertainty` |
| No headings detected | page-based pseudo sections (`pseudo: true`) | write section notes per page; mention weak alignment in `uncertainty` |
| Heading missed / junk heading | repaired, logged in `verification.outline_fixes` (`recovered heading ...`, `numbering gap ...`) | if a gap remains, note it; anchor by block anyway |
| Two-column / reading order | parser restores column order; anchors are per block | if a quote spans a column break, `quote_in_neighbour_block` handles it |
| Long paper (digest > 45k chars of body text) | later paragraphs shortened to first sentence | `notes.py find`, or `init --pages A-B`, or `--full-digest`; prioritise abstract, intro, method, results, conclusion |
| Formula/figure content missing | equations by number (`Eq. N`, `transcription_status`); figures = captions only | do not invent curve values; cite caption or mark unreported |
| Non-English / Chinese paper | CJK-aware matching | quotes in the original language |

## Honesty rules

- No note without an anchor you have read. Unknown -> null + `unreported` with reason. Never write "not reported" as a finding.
- A verified anchor proves the words are there, not that your paraphrase is right: keep notes close to the quote.
- Limitations: prefer the authors' stated ones; if you add your own reading, label it ("reader's note:") and still anchor the basis.
- Do not cite headers/footers/figure-internal text for body claims.
