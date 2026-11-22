# Field dictionary (paper-notes 1.0.0)

Every note item: `{"text": str, "anchors": [resolved anchor], "check": {"status": verified|needs_review|failed, "problems", "review"}}`.
Resolved anchor: `kind` (block/para/table/figure/equation/image/section), `page`, `block_id`, `paragraph_id`, `bbox`
(PDF points, origin top-left), `section_id`, `section` (path, e.g. `3 Method > 3.2 Loss`), `quote`, `check`, `ok`.

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
`definition`, `other_definitions` + `definition_conflict` (when merged entries disagree), `abbreviation`
{`abbr`, `expansion_in_paper`, `status`: found_in_text | expansion_not_printed}, `section_id`, anchors, check.
Machine: dedupe by normalised term/alias, abbreviation expansion printed. Human: definition correctness.

## Status values

`result.status`: success (no failed item, required card fields filled or unreported with reason, all top-level
sections covered, all contract fields filled) · partial (reason in `run_status.reason`) · failed (no PDF / encrypted /
unparseable; nothing invented). `run_status.human_takeover` points to `verification.failed_items` / `review_items`.
