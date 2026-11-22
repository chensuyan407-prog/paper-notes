# paper-notes — section-aligned, anchor-verified paper notes (v1.0.0)

Skill for challenge 阅读10｜文献总结与结构化笔记. Input: a paper PDF (+ `case.json` / `task.md`).
Output: structured notes whose skeleton is the paper's own outline, with a unified paper card, per-section
notes, a merged knowledge-point list, and a machine check of every anchor.

Focus (one problem, done properly): **source retention + section alignment**. A base agent typically writes a
fluent summary with a generic template ("Background / Method / Results"), cites "Section 4" or nothing, and
silently mixes numbers from different tables. This skill makes each note carry a block-level anchor and then
*checks* it against the PDF text, so wrong quotes, wrong places and wrong numbers are caught before hand-in.

## Files

| path | role |
|---|---|
| `SKILL.md` | agent instructions (workflow, anchor format, check table, special inputs) |
| `scripts/notes.py` | CLI: `init` (parse + outline + digest + draft + partial result), `build` (resolve/check/merge/render), `find` |
| `scripts/notes_lib.py` | outline repair, anchor resolution, quote/number/section checks, cue sentences |
| `scripts/parse_pdf.py`, `mathlayout.py` | layout-aware PDF parser (columns, headings, tables, equations, header/footer removal) from pdf-evidence-reader v0.3 |
| `scripts/table_query.py`, `find_evidence.py`, `crop_region.py`, `provenance.py` | table cell lookup, text search, page-image crops with provenance |
| `templates/field_dictionary.md` | card / section / knowledge fields, with machine vs human checkability |
| `examples/minimal_example.md` | minimal call + illustrative (not official) output |

Dependencies: Python ≥ 3.9, `pymupdf>=1.23`, `numpy` (both in the evaluation image). Optional: `tesseract` on PATH
(OCR of scanned pages, used automatically by the parser when present), `fontTools`. No network, no model calls.

## Usage

```bash
python scripts/notes.py init  --case /input/case.json --out /app/output --work /app/work
#   options: --pdf X.pdf (if case.json names none) --pages 1-12 --password PW --full-digest --force (overwrite draft)
# agent: read /app/work/digest.md (+ cues.json), fill /app/work/draft.json
python scripts/notes.py build --work /app/work          # repeatable; fix what it prints, rebuild
python scripts/notes.py find "residual mapping" --section 3   # optional search, paste-ready anchors
```

## Outputs (`/app/output`)

| file | content |
|---|---|
| `result.json` | `case_id`, every `output_contract` field, `status` (`success`/`partial`/`failed`), `run_status`, `notes` {`paper_card`, `section_notes`, `knowledge_points`, `outline`}, `evidence` (flat list: field, page, block_id, bbox, section, quote, check), `unreported`, `uncertainty`, `conflicts`, `verification`, `sources` (file, SHA-256, parse status, unresolved pages), `change_log` |
| `notes.md` | human-readable notes; each line ends with 〔p.PAGE §SECTION BLOCK〕, ⚠ needs review, ✗ failed |
| `paper_card.json` / `paper_card.csv` | one row per paper, fixed columns → several papers can be concatenated and compared |
| `knowledge_points.jsonl` | one merged knowledge point per line (term, aliases, kind, definition, abbreviation check, anchors) |
| `verification.json` | counts, failed/review items with field path, section coverage, outline fixes, merges |
| `parsed/<stem>/` | parser output (`doc.json`, `document.md`, tables) — the anchors' ground truth |

## Method

1. **Outline = the paper's sections.** From the parser's headings, then repaired:
   junk numbered headings (e.g. `1 N` produced by footnote markers) are rejected; bold numbered lines that the parser
   left as body text are **recovered when their number continues the numbering** (prev < n < next, parent matches);
   appendix letters wrongly nested under *References* are lifted; numbering gaps are reported; with no headings at all,
   page-based pseudo sections are used and marked. Every block is then reassigned to the last heading before it in
   reading order. All repairs are logged (`verification.outline_fixes`). On the dev set this turned the BatchNorm paper
   (1502.03167) from 2 bogus + 0 of its 6 §2–§3.4 headings into the correct 17-section outline, and recovered GloVe §4.4.
2. **Digest.** Reading-order text grouped by section, each paragraph with its anchor, captions/equations inline,
   tables/figures listed under their section; >45k chars of body text → later sections show only the first sentence of their first two paragraphs (tell-tale line added).
3. **Cue sentences** per card field (regex cues + section-name prior, e.g. limitations favour Discussion/Conclusion).
4. **Anchor resolution** (`notes_lib.Doc.resolve`): comparison form = NFKC, lower case, letters/digits/CJK only
   (robust to hyphenation, ligatures, quotes, spaces). Order: cited block → same paragraph / ±2 blocks (column breaks)
   → whole document (`relocated`) → fuzzy best sentence (share of quote covered by ≥4-char runs ≥ 0.85 → `quote_fuzzy`,
   review) → `quote_not_found`. Tables: quote must be within one row (`Table 4: ResNet-152 4.49`) or the caption.
5. **Checks per note item:** ≥1 anchor; all anchors resolve; every number in the note (≥10 or decimal) appears in the
   anchored paragraph / matched table row / caption (small integers only flagged); section notes anchored inside their
   section (or sub-section); figure and image readings always `needs_review`.
6. **Document checks:** required card fields filled or declared unreported; every top-level section covered (sub-sections
   count); notes emitted in outline order regardless of draft order; unknown section ids reported; knowledge points merged
   by normalised term/alias (plural, case, hyphen), conflicting definitions kept and flagged; abbreviation expansion
   searched in the text (`Long Form (ABBR)` / `ABBR (Long Form)`).
7. **Contract mapping:** explicit `@refs` or literal values (anchors inside literals are checked), name-based auto-map,
   unmapped → `unreported` and `partial`.

Machine-checkable vs human: see `templates/field_dictionary.md`. In short, existence/position/verbatim/number/coverage are
machine-checked; *whether a paraphrase is faithful* and readings of figures/scans need a human.

## Limits (known)

- Number check is string-level: a number present in the cited paragraph but attached to a different quantity passes.
- Table quotes are checked per row, not per column: cite `row label + value`; the column is not verified.
- Figures: only captions are text; curve values read from plots are never verified.
- Heading recovery needs a numbered, bold/larger line; unnumbered headings missed by the parser stay merged (gap not detectable).
- Scanned pages without OCR: notes can only be image readings (review). With tesseract on PATH they become text blocks (OCR errors possible, `ocr_conf` in doc.json).
- One primary PDF per run (others: run init with another `--work`).

## Self-check

```bash
python tests/run_tests.py     # in the GitHub repo: synthetic PDF + 14 adversarial note perturbations
```
Expected: every perturbation (fabricated quote, wrong number, number from another row, wrong block, wrong section,
paraphrased quote, missing anchor, bbox off page, unknown table, ...) gets the expected status; good notes verify.

## Maintenance

Version 1.0.0 (2026-11-22). Parser: pdf-evidence-reader 0.3.0 (same author). Issues/changes: see repository `CHANGELOG`.
