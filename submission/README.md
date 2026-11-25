# paper-notes — section-aligned, anchor-verified paper notes (v1.1.0)

Skill for challenge 阅读10｜文献总结与结构化笔记. Input: a paper as PDF, Markdown, plain text or Word `.docx`,
optionally with supplementary files (+ `case.json` / `task.md`). Output: structured notes whose skeleton is the
paper's own outline, with a unified paper card, per-section notes, a merged knowledge-point list, and a machine
check of every anchor.

Focus (one problem, done properly): **source retention + section alignment**. A base agent typically writes a
fluent summary with a generic template ("Background / Method / Results"), cites "Section 4" or nothing, and
silently mixes numbers from different tables. This skill makes each note carry a block-level anchor and then
*checks* it against the source text, so wrong quotes, wrong places and wrong numbers are caught before hand-in.

## Files

| path | role |
|---|---|
| `SKILL.md` | agent instructions (setup, workflow, anchor format, check table, special inputs) |
| `scripts/notes.py` | CLI: `init` (pick primary + parse + outline + digest + draft + partial result), `merge` / `add` (write the draft in validated parts), `build` (resolve/check/merge/render; `--dry-run`), `find` |
| `scripts/textdoc.py` | `.md` / `.txt` / `.docx` → the same `doc.json` layout as the PDF parser (headings, tables, equations, line/paragraph locators); stdlib only |
| `scripts/notes_lib.py` | outline repair + heading classifier, anchor resolution, quote/number/section checks, quantity equivalence, cue sentences + key table rows |
| `scripts/parse_pdf.py`, `mathlayout.py` | layout-aware PDF parser (columns, headings, tables, equations, header/footer removal, mixed text+image pages) from pdf-evidence-reader 0.3.1 |
| `scripts/table_query.py`, `find_evidence.py`, `crop_region.py`, `provenance.py` | table cell lookup, text search, page-image crops with provenance |
| `templates/field_dictionary.md` | card / section / knowledge fields, anchor record, machine vs human checkability |
| `examples/minimal_example.md` | minimal call + illustrative (not official) output |

Dependencies: Python ≥ 3.9, `pymupdf>=1.23`, `numpy` (both in the evaluation image). Optional: `tesseract` on PATH
(OCR of scanned pages, used automatically by the parser when present), `fontTools`. `.docx`/`.md`/`.txt` need only
the standard library. No network, no model calls.

## Usage

```bash
python scripts/notes.py init  --case /input/case.json --out /app/output --work /app/work
#   options: --input X.docx / --pdf X.pdf (if case.json names none)  --primary FILE  --pages 1-12  --password PW
#            --full-digest  --force (reset draft.json and result.json)
. /app/work/env.sh                                        # PY, SKILL_DIR and N() for every later shell call
# agent: read /app/work/digest.md (+ cues.json), then write the notes in parts:
N merge /app/work/part_card.json /app/work/part_sections.json   # validated, atomic, draft.bak.json kept
N add card.limitations --text "..." --a "p9-b3: verbatim words" # one item (--append to add to a list)
N build --dry-run                                         # report only, writes nothing
N build                                                   # repeatable; fix what it prints, rebuild
N find "residual mapping" --section 3 [--source S1]       # optional search, paste-ready anchors
```

## Outputs (`/app/output`)

| file | content |
|---|---|
| `result.json` | `case_id` (0 kept), every `output_contract` field, `status` (`success`/`partial`/`failed`), `run_status`, `notes` {`paper_card`, `section_notes`, `knowledge_points`, `outline`}, `evidence` (flat list: field, source, page, block_id, line_start/line_end, bbox, section, quote, check), `unreported`, `uncertainty`, `conflicts`, `verification`, `sources` (file, format, role primary/supplement + why, SHA-256, parse status, unresolved pages), `change_log` |
| `notes.md` | human-readable notes; each line ends with 〔p.PAGE §SECTION BLOCK〕 (text inputs add `L..`, supplements `S1:file`), ⚠ needs review, ✗ failed |
| `paper_card.json` / `paper_card.csv` | one row per paper, fixed columns → several papers can be concatenated and compared |
| `knowledge_points.jsonl` | one merged knowledge point per line (term, aliases, kind, definition, conflict, abbreviation check, anchors) |
| `verification.json` | counts, failed/review items with field path, section coverage, outline fixes, merges, knowledge conflicts, visual-page coverage, draft repairs |
| `parsed/<stem>/` | parser output (`doc.json`, tables, page images) — the anchors' ground truth |

## Method

0. **Inputs and roles.** Every `.pdf/.md/.markdown/.txt/.docx` string in `case.json` is a candidate (`task.md` /
   `case.json` excluded; nothing named → supported files next to case.json). Score: `--primary` > `role|type|kind`
   = primary/main/paper (or `"primary": true`) > key name (`paper`, `main_pdf`, …) > supplement-like role / key /
   file name / description (`supp`, `SI`, `appendix`, 附件, 补充) loses > PDF > docx > md > txt > order. The best
   parsed file is the primary; the others are parsed as supplements `S1, S2…` (own digest, anchors `S1::p2-b4: …`,
   `find --source S1`). Named but missing files are reported in `uncertainty`. Text inputs go through `textdoc.py`:
   Markdown `#`/setext headings, YAML title, pipe tables, `$$` math, images; Word heading/title styles, tables, OMML
   equations, content controls, page breaks; plain text with form-feed pages. Pattern headings must keep the
   numbering increasing, so numbered list items and `1 Department of …` affiliation marks are not taken for sections;
   the Chinese hierarchy 一、 > （一） > 1. restarts the arabic numbering under each Chinese heading.
1. **Outline = the paper's sections.** From the parser's headings, then repaired: junk numbered headings (e.g. `1 N`
   produced by footnote markers) are rejected; bold numbered lines that the parser left as body text are
   **recovered when their number continues the numbering** (prev < n < next, parent matches); appendix letters wrongly
   nested under *References* are lifted; numbering gaps are reported; with no headings at all, page-based pseudo
   sections are used and marked. v1.1 also recovers **unnumbered** headings left as body text when they are short,
   standalone and bold/larger (`Limitations`, `Threats to validity`, `EXPERIMENTAL SETUP`, `局限性`, `附录A`,
   `（二）研究对象`): inside a numbered paper they become sub-sections of the current section, end matter stays top level;
   table-of-contents lines (`Appendices 20`, dot leaders) are rejected. The PDF parser now also reads `（一）`, `第3章`,
   `1.1数据集`, and no longer labels page-1 body text and headings as authors when the paper has no "Abstract"
   heading. Every block is reassigned to the last heading before it in reading order; all repairs are logged
   (`verification.outline_fixes`). On the dev set v1.0 turned BatchNorm (1502.03167) into the correct 17-section
   outline and recovered GloVe §4.4; v1.1 keeps every heading on 7 real papers (Attention, BERT-scan, GloVe, ResNet,
   BatchNorm, Kaplan, Chinchilla) and adds ResNet's *PASCAL VOC* / *MS COCO* and Chinchilla's *H.2 MMLU*.
2. **Digest.** Reading-order text grouped by section, each paragraph with its anchor (and source lines for text
   inputs), captions/equations inline, **table rows printed under their section**; head lines *WHERE TO LOOK*,
   *KEY TABLE ROWS*, *VISUAL PAGES*; >45k chars of body text → later sections show only the first sentence of their
   first two paragraphs (tell-tale line added).
3. **Cue sentences** per card field: generic cue words + **strong author-voice cues** (+2: "a limitation of this
   study", "may not generalize", "trained for N epochs", "learning rate … 0.1", "n = 120", 本研究的局限, 设置为, 样本量…)
   + section-name prior (+1.5) + own-section bonus (+2 inside `Limitations` / `Experimental setup`); a bare
   "does not / cannot" is down-weighted. `table_rows`: per table the proposed-method row (`ours`, `proposed`, 本文) and
   best/worst rows, offered as **pre-resolved** `Table N: label value` anchors; `sections_of_interest` lists sections
   whose titles match each field. On ResNet the top-3 `conditions` cues are exactly the SGD / lr / weight-decay
   sentences. **Visual pages**: a text-layer page whose raster images cover ≥25 % of it with < 1500 text chars (or
   ≥50 %) gets a page image (`visual_check` in doc.json, `[pN VISUAL]` in the digest); each build reports such a page
   as read (a `pN@bbox` / figure anchor on it) or unread (automatic `uncertainty` entry) in
   `verification.visual_coverage`.
4. **Anchor resolution** (`notes_lib.Doc.resolve`): comparison form = NFKC, lower case, letters/digits/CJK only
   (robust to hyphenation, ligatures, quotes, spaces). Order: cited block → same paragraph / ±2 blocks (column breaks)
   → whole document (`relocated`) → fuzzy best sentence (share of quote covered by ≥4-char runs ≥ 0.85 →
   `quote_fuzzy`, review) → `quote_not_found`. Tables: quote must be within one row (`Table 4: ResNet-152 4.49`) or
   the caption (merged / empty cells tolerated). Line anchors `L120` map to the block covering that source line.
   `S1::` routes the anchor to supplement S1.
5. **Checks per note item:** ≥1 anchor; all anchors resolve; every number in the note (≥10 or decimal) appears in the
   anchored paragraph / matched table row / caption (small integers only flagged). **Quantity equivalence**: a number
   with its scale word / sign is compared by value with every quantity in the evidence: `60 亿` = `6 billion` =
   `6,000,000,000` = `6×10^9`, `128 万` = `1.28 million`, `3.2k` = `3200`, `95%` = `0.95` (decimal→percent skipped
   after `p <`), recorded as `number_equivalence`; a different value still fails. Numbers right after a CJK character
   are now detected (v1.0 silently skipped `准确率为95.3%`); `2.1节`, `表2`, `in 2019` / `2019年` are treated as
   references/years, not claims. Section notes must be anchored inside their section (or sub-section); figure and
   image readings are always `needs_review`.
6. **Document checks:** required card fields filled or declared unreported; every top-level section covered
   (sub-sections count); notes emitted in outline order regardless of draft order; unknown section ids reported.
   **Knowledge points** merged by normalised term/alias (plural, case, hyphen, CJK spacing, a few 异形词 and British
   spellings, `Long Form (ABBR)` split), and an abbreviation is merged with the entry whose long form spells it or
   that the paper prints for it (`CNN` + `convolutional neural network`). **Not merged**: the same abbreviation with
   different long forms (`SA` = self-attention vs simulated annealing) → `abbreviation_collision`. Definitions are
   compared: different numbers or low word overlap → `definition_conflict` (with the defining sections, also added
   to `conflicts`), else `definitions_agree`. A printed expansion different from the entry's long form →
   `expansion_mismatch`.
7. **Contract mapping:** explicit `@refs` or literal values (anchors inside literals are checked), name-based
   auto-map, unmapped → `unreported` and `partial`; `case_id` listed in the contract keeps the case's id (including
   `0`); a failed literal anchor makes the status `partial`.
8. **Draft safety.** `merge` / `add` write the draft in validated parts (unknown section ids / card keys rejected or
   mapped: `limitation` → `limitations`, `findings` → `main_findings`; section ids as `s4`, `3.1` or title; `note` /
   `claim` accepted for `text`, `anchors` / `evidence` / `source` for `a`); writes are atomic with `draft.bak.json`.
   `build` reads drafts leniently (BOM, ```json fences, leading prose, trailing commas, Python literals; repairs listed
   in `draft_repairs`) and, on unrecoverable JSON or an internal error, exits non-zero with `work/build_error.json`
   and **does not touch `result.json`**. Each build keeps the previous result as `work/result.prev.json` and warns on
   a sharp drop of verified items; re-running `init` keeps a built result (unless `--force`).

Machine-checkable vs human: see `templates/field_dictionary.md`. In short, existence/position/verbatim/number/
coverage/merging are machine-checked; *whether a paraphrase is faithful* and readings of figures/scans need a human.

## Limits (known)

- Number check is value-level, not meaning-level: a number present in the cited paragraph but attached to a different
  quantity passes; `5%` vs an unrelated `0.05` in the same paragraph would pass (p-value contexts excluded).
- Table quotes are checked per row, not per column: cite `row label + value`; the column is not verified.
- Figures: only captions are text; values read from plots or pasted images are never verified (always review).
- Heading recovery needs a numbered line continuing the numbering, or a short standalone bold/larger named/ALL-CAPS
  line; run-in headings (`Limitations.` followed by text in the same paragraph) stay inside the paragraph.
- `.docx` page numbers come from Word's last layout (`lastRenderedPageBreak`) or explicit breaks: approximate.
  `.doc` (binary), `.tex`, `.html`, `.pptx` are not parsed (not picked as inputs).
- Scanned pages without OCR: notes can only be image readings (review). With tesseract on PATH they become text
  blocks (OCR errors possible, `ocr_conf` in doc.json).
- One primary document per run; supplements are anchorable but get no section notes of their own.

## Self-check

```bash
python tests/run_tests.py     # in the GitHub repo: 77 expectations (28 from v1.0 + 49 for v1.1)
python src/reproduce.py       # same, writes execution/results/metrics.json
```
v1.0 part: synthetic two-column PDF + 14 adversarial note perturbations, encrypted and scanned PDFs. v1.1 part
(`tests/test_v11.py`): Markdown primary + PDF supplement chosen by role, `.txt` with Chinese numbering and form-feed
pages, a generated `.docx`, primary choice by file name, unnumbered / ALL-CAPS PDF headings, a mixed text+image page,
number equivalence (pass and fail), CJK-context numbers, abbreviation merge / collision, definition conflicts,
`case_id: 0` in the contract, broken / fenced / trailing-comma drafts, dry-run, regression warning, merged table
cells, table-of-contents lines. Expected: every perturbation gets the expected status; good notes verify.

## Maintenance

Version 1.1.0 (2026-11-25). Parser: pdf-evidence-reader 0.3.1 (same author). Issues/changes: see repository `CHANGELOG`.
