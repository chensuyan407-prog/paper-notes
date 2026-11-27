# Field dictionary (paper-notes 1.2.0)

Every note item: `{"text": str, "anchors": [resolved anchor], "check": {"status": verified|needs_review|failed, "problems", "review"}}`.
Resolved anchor: `kind` (block/para/line/table/figure/equation/image/section), `page`, `block_id`, `paragraph_id`, `bbox`
(PDF points, origin top-left; null for text inputs), `line_start`/`line_end` (source lines, .md/.txt), `source_paragraph`
(.docx paragraph index), `source` + `source_file` (supplement key S1.. when the anchor was prefixed `S1::`; section ids
then read `S1:s3`), `section_id`, `section` (path, e.g. `3 Method > 3.2 Loss`), `quote`, `check`, `ok`.
`check.number_equivalence` lists numbers accepted in another unit/notation (`60 == 6e+09`); `check.small_numbers_unchecked`
lists single digits / years not checked.

## Paper card (`notes.paper_card`, same keys for every paper)

| key | required | content | machine-checkable | human |
|---|---|---|---|---|
| title | yes | title as printed (pre-filled from the title block) | anchor/quote | – |
| authors | yes | authors (+affiliations) (pre-filled) | anchor/quote | completeness |
| venue_year | no | venue, year, arXiv id if printed | anchor/quote | – |
| research_question | yes | question/problem addressed | anchor exists, quote verbatim | faithful wording |
| motivation_gap | no | why / gap in prior work | anchor | faithful |
| contributions | no | claimed contributions | anchor | faithful |
| data | yes | datasets, samples, sizes, splits | anchor, numbers ⊂ cited text | right dataset ↔ number |
| method | yes | approach / design / model | anchor | faithful |
| conditions | yes | assumptions, settings, hyper-parameters, scope on which conclusions depend | anchor, numbers | completeness |
| main_findings | yes | results with numbers as printed | anchor, numbers ⊂ cited paragraph / table row | number ↔ quantity |
| conclusion | yes | authors' conclusion | anchor | faithful |
| limitations | yes | stated limitations, or `unreported` + reason | anchor or reason present | completeness |
| future_work | no | stated future work | anchor | – |

## Section notes (`notes.section_notes`, one per outline section, paper order)

`section_id`, `number`, `heading`, `level`, `parent`, `pages`, `block_span`, `appendix`, and lists of items for
`purpose`, `method`, `results`, `conclusion`, `transition` (link to previous/next section), `key_points`; optional `skip_reason`.
Machine: coverage of top-level sections, anchors inside the section, order. Human: whether the section's role is captured.

## Knowledge points (`notes.knowledge_points`)

`term`, `aliases`, `kind` (concept, term, abbreviation, variable, method, dataset, metric, finding, assumption, formula),
`definition`, `other_definitions` + `definition_conflict` {`first`, `disagreeing`: [{definition, section_id, why}]} when merged
entries disagree (different numbers / low word overlap) or `definitions_agree: true`, `abbreviation` {`abbr`,
`expansion_in_paper`, `status`: found_in_text | expansion_not_printed | expansion_mismatch, `note`}, `section_id`, anchors, check.
`verification.knowledge_conflicts`: `abbreviation_collision` (same abbreviation, different long forms: kept apart) and
`definition_conflict` entries. Machine: dedupe by normalised term/alias/long form, collisions, definition drift,
abbreviation expansion printed. Human: definition correctness.

## Sources and visual pages

`sources[]`: `file`, `format` (pdf/md/txt/docx), `role` (primary/supplement/unparsed), `source_key` (primary, S1, ...),
`role_reasons` (why: role=, key=, file name), `sha256`, `parse_status`, `page_count`, `warnings`.
`verification.visual_pages[]`: `page`, `kind` (image_only | mixed), `reason`, `image` (PNG path), `read` (an image/figure
anchor cites that page). Unread pages are added to `uncertainty` with `auto: true`. `verification.draft_repairs`: what the
lenient draft reader fixed or re-mapped.

## Status values

`result.status`: success (core notes delivered: research_question, method and main_findings have a verified note or a
stated reason, at least half of the top-level sections have notes, every contract field mapped; failed notes are left out
into `verification.dropped_items` and listed with other gaps in `run_status.warnings`) · partial (reason in `run_status.reason`) · failed (no input file / encrypted /
unparseable; nothing invented). `run_status.human_takeover` points to `verification.failed_items` / `review_items`.
