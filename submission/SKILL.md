---
name: paper-notes
description: Turn a research paper (PDF, or Markdown / plain text / Word .docx; optionally with supplementary files) into section-aligned, field-structured reading notes in which every key note points back to a verified place in the original (page, block, source line, table row, figure, equation, supplement). Use when a task gives a paper and asks for a literature summary, structured notes, a paper card (research question, data, method, conditions, findings, conclusion, limitations), section-by-section summaries, a knowledge-point list, or notes "with sources/evidence". Picks the primary paper among several inputs (role / key / file name), builds the paper's own outline (Chinese numbering 一、/（一）/第N章, ALL-CAPS and unnumbered headings such as Limitations, appendices), gives a reading digest with anchors and pre-checked key table rows, then checks each note against the source text - quote verbatim in the cited block, anchor inside the section it summarises, every number present in the cited text or table row (60 亿 = 6 billion, 95% = 0.95 accepted), card fields filled or declared unreported, sections covered in the paper's order, knowledge points merged with abbreviation collisions and definition conflicts reported. Notes can be written in small parts (merge/add) and a broken draft never overwrites a valid result. Handles scanned, encrypted, image-heavy, Chinese and long papers honestly.
---

# paper-notes (v1.1.0)

Goal: notes that **follow the paper's own structure**, **keep** research question / data / method / conditions /
findings / conclusion / limitations, can be **found back** in the source claim by claim, and are **reusable**
(same card fields for every paper, CSV/JSONL exports). You read and write the notes; the scripts give you the
outline and anchors and then check your notes mechanically. Budget: ~6-12 model requests. **Save early**: init
already writes a valid partial `result.json`, and every later step keeps a valid one.

## 0. Setup (first shell call; shell state is not kept between calls)

```bash
PY=$(command -v python3 || command -v python)
for d in "${SKILL_DIR:-}" /skills/weekly-skill /app/submission /app/skills /app/skills/* /skills/* "$(pwd)"; do
  [ -f "$d/scripts/notes.py" ] && SKILL_DIR="$d" && break
done
"$PY" "$SKILL_DIR/scripts/notes.py" init --case /input/case.json --out /app/output --work /app/work
```
init writes `/app/work/env.sh`. **Start every later shell call with `. /app/work/env.sh;`** - it sets `$PY`,
`$SKILL_DIR` and the shortcut `N` = `"$PY" "$SKILL_DIR/scripts/notes.py"` (e.g. `. /app/work/env.sh; N build`).

init prints `case_id`, `contract_fields`, `inputs` (each with its role: `primary`, `supplement=S1`, ...), `primary`,
`parse_status`, the **outline** (`s4 L2 3.1 Residual Learning pp3-3`), `visual_pages` and paths. It writes
`/app/output/result.json` (status `partial`), `/app/work/digest.md`, `cues.json`, `outline.json`, `draft.json`.
- Inputs: `.pdf`, `.md`/`.markdown`, `.txt`, `.docx`. Primary = explicit `--primary FILE` > `role`/`type` = primary/main
  > key name (`paper`, `main_pdf`, ...) > not supplement-like by role/key/file name (`supp`, `SI`, `appendix`, 附件, 补充)
  > PDF > docx > md > txt. Wrong choice? re-run init with `--primary paper.docx --force`.
- `parse_status` `failed` (e.g. `encrypted`, corrupt docx): stop; result.json already says why (`--password` only if the task gives one).

## 1. Read

`task.md` / `case.json` (language, required fields, focus), then `digest.md`: the paper in reading order, grouped by
**the paper's sections**, each paragraph prefixed by its anchor `[p3-b12]` (text inputs: `[p1-b12 L40-44]` = source lines).
Its head lists **WHERE TO LOOK** (sections matching data / method / conditions / findings / limitations),
**KEY TABLE ROWS** (pre-checked anchors such as `'Table 2: Ours 95.3'`) and **VISUAL PAGES**. Tables are printed
under their section. `cues.json` = candidate sentences per card field (`strong_cue` = author-voice phrase such as
"A limitation of this study", "trained for 90 epochs") - a shortcut, not an answer: read the sentence first.
More: `N find "query words" [--section 3.2] [--source S1]` (paste-ready anchors);
tables: `"$PY" "$SKILL_DIR/scripts/table_query.py" /app/output/parsed/<stem> --table "Table 2" --list`.
Supplements: `digest_S1.md` ...; cite them with the prefix `S1::`.

## 2. Write the notes - in parts (safer than one big file)

Every note item is `{"text": "your note", "a": ["p3-b12: 6-25 words copied verbatim from that block", "Table 2: ResNet-152 4.49"]}`;
a field holds one item or a list. Write **2-4 small JSON files** and merge them (each is validated; a bad one is
rejected without touching the draft; `` ```json `` fences / trailing commas are repaired):
```bash
. /app/work/env.sh; N merge /app/work/part_card.json /app/work/part_sections.json /app/work/part_knowledge.json
```
- `part_card.json`: `{"card": {...}, "unreported": [...], "contract": {...}}`
- `part_sections.json`: `{"sections": [{"section_id": "s4", "purpose": ..., "results": ...}, ...]}` (id, number `"3.1"` or title accepted)
- `part_knowledge.json`: `{"knowledge": [...], "uncertainty": [...], "conflicts": [...]}`
Single fixes: `N add card.limitations --text "..." --a "p9-b3: ..."` · `N add sections.3.2.results --append --text .. --a ..` ·
`N add knowledge --term CNN --kind abbreviation --definition ".." --a ".."` · `N add unreported.card.future_work --reason ".."` ·
`N add contract.summary --value @card`. (Editing `/app/work/draft.json` directly still works.)

Content rules:
- `card`: 13 unified fields (README *Field dictionary*). Required: title, authors, research_question, data, method,
  conditions, main_findings, conclusion, limitations. Not in the paper -> null **and** `unreported`:
  `{"field": "card.limitations", "reason": "no limitation stated; searched Discussion/Conclusion (p15-16)"}`.
  `conditions` = what the conclusions depend on (assumptions, settings, data scope, hyper-parameters).
- `sections`: one entry per outline section (paper order is restored automatically; unknown ids are reported).
  Fill `purpose`, `method`, `results`, `conclusion` where the section has them, `transition` = link to previous/next
  section, `key_points` = list. Anchor each item **inside that section**. Every top-level section needs a note
  (or `"skip_reason"`); sub-section notes count for their parent.
- `knowledge`: `{"term", "aliases": [...], "kind", "definition", "section_id", "a": [...]}`, one per concept.
- `contract`: map **every** output_contract field: `"@card"`, `"@card.limitations"`, `"@sections"`, `"@knowledge"`,
  `"@notes_md"`, `"@evidence"`, or a literal (objects inside may carry `"a"` anchors; checked too). Obvious names are
  auto-mapped (`limitations` -> `@card.limitations`); `case_id` is always filled from case.json.
- `uncertainty`, `conflicts` (e.g. abstract vs table disagree - cite both): strings or objects.
Notes in the task's language; quotes stay verbatim in the source language. Numbers exactly as printed
(another unit/notation is accepted: 60 亿 = 6 billion, 128 万 = 1.28 million, 95% = 0.95).

## 3. Build + verify, fix, rebuild (1-2 rounds)

```bash
. /app/work/env.sh; N build            # N build --dry-run = report only, writes nothing
```
Writes `/app/output/result.json`, `notes.md`, `paper_card.json/.csv`, `knowledge_points.jsonl`, `verification.json`;
prints `fix_these` / `review` / `uncovered_sections` / `card_missing` / `visual_pages_unread` / `knowledge_conflicts`.
If the draft is not valid JSON, build exits 4, writes `/app/work/build_error.json` (line/column) and **leaves
result.json untouched**; a build that verifies far fewer items than the previous one prints `regression_warning`
(previous result kept in `/app/work/result.prev.json`).

| check (item status) | meaning | action |
|---|---|---|
| `quote_verbatim`, `quote_in_table`, `quote_in_caption`, `equation_exists` (verified) | anchor exists, quote is in it | done |
| `quote_in_neighbour_block` (verified) | quote is in the same paragraph/next block; anchor moved there | done |
| `number_equivalence` (info, verified) | note number = cited number in another unit (亿/billion, %/decimal) | done |
| `relocated` (review) | quote not in the cited block but verbatim elsewhere; anchor moved | check the claim fits the new place |
| `quote_fuzzy` (review) | not verbatim; closest source sentence attached | copy the exact words |
| `quote_not_found` (failed) | no such text in the source | fix quote/claim or drop it |
| `numbers_not_in_evidence:X` (failed) | a number in the note is not in the cited block/paragraph/table row | cite where X is printed, or correct X |
| `all anchors outside this section` (review) | a section note cites another section (or a supplement) | anchor inside the section (or accept for `transition`) |
| `coarse_section_anchor`, `no_quote`, `table_exists`/`figure_exists` without quote | weak anchor | add a quote (table: row label + value) |
| `figure_reading_unverified`, `image_read_unverified` | your reading of a plot / page image | stays in review (honest) |
| `abbreviation ... mismatch / shared`, `definitions disagree` (review) | knowledge point conflicts with the paper or another entry | check; fix term/definition |
| `source_not_found`, `bbox_off_page`, `line_not_found`, `*_not_found`, `anchor_unparseable` (failed) | bad anchor | fix format (below) |

`status` = `success` only when no item failed, required card fields are filled or declared unreported, every
top-level section is covered and every contract field is filled; else `partial` with the reason in `run_status`.
Never edit result.json by hand to change verdicts; change the draft and rebuild.

## Anchor formats

`p3-b12: verbatim words` (block, best) · `L120: words` / `L120-L131: words` (source lines, .md/.txt) · `para14: words` ·
`Table 2` / `Table 2: row label value` (row-level check) · `Fig. 4` / `Fig. 4: caption words` · `Eq. 3` ·
`p2@x0,y0,x1,y1: what you read` (page image / pasted figure; bbox in PDF points) · `s4` (whole section, coarse) ·
any of these prefixed `S1::` for supplement S1. Block ids: `p{page}-b{n}`; `p{page}-m{n}` removed header/footer,
`p{page}-g{n}` text inside a figure. `.docx` pages follow Word's page breaks (approximate); `.md` is one logical page.

## Special inputs

| Situation | What the scripts do | What you do |
|---|---|---|
| Several files (paper + SI / appendix / data) | primary chosen by role/key/name; others parsed as S1, S2 (digest_S1.md) | cite supplement facts with `S1::`; check init's `inputs` |
| `.md` / `.txt` / `.docx` paper | same outline/anchor/check pipeline; line (txt/md) or paragraph (docx) locators | anchor by block or `L..` |
| Encrypted / unreadable / corrupt | init: `status=failed`, reason in `run_status` | report; `--password PW` only if the task provides it |
| Scanned page (no text layer, no OCR) | pseudo section `[page N, image-only page]`, page image + ink regions | look at the image; anchors `pN@bbox: text`; all such items stay `needs_review`; say so in `uncertainty` |
| Page with little text but a large image (pasted table/plot) | `VISUAL` page: page image saved; listed in `visual_pages`; unread ones become an automatic `uncertainty` entry | open the PNG, cite `pN@bbox: what you read` (review) or state it was not read |
| No headings detected | page-based pseudo sections (`pseudo: true`) | write notes per page; mention weak alignment in `uncertainty` |
| Heading missed / junk heading / ToC lines | numbered, Chinese-numbered, ALL-CAPS and named (Limitations, 局限性, Appendix) lines recovered; ToC lines rejected; logged in `verification.outline_fixes` | if a gap remains, note it; anchor by block anyway |
| Two-column / reading order | parser restores column order; anchors are per block | a quote over a column break is `quote_in_neighbour_block` |
| Long paper (digest > 45k chars of body text) | later paragraphs shortened to first sentence | `N find`, `init --pages A-B`, or `--full-digest`; prioritise abstract, intro, method, results, conclusion |
| Formula/figure content missing | equations by number (`Eq. N`, `transcription_status`); figures = captions only | do not invent curve values; cite caption or mark unreported |
| Non-English / Chinese paper | CJK-aware matching; numbers in Chinese notes are checked too | quotes in the original language |

## Honesty rules

- No note without an anchor you have read. Unknown -> null + `unreported` with reason. Never write "not reported" as a finding.
- A verified anchor proves the words are there, not that your paraphrase is right: keep notes close to the quote.
- Limitations: prefer the authors' stated ones; if you add your own reading, label it ("reader's note:") and still anchor the basis.
- Do not cite headers/footers/figure-internal text for body claims. Do not present supplement facts as main-paper facts.
