# Changelog

## 1.0.0 — 2026-11-22
- First release for 阅读10｜文献总结与结构化笔记.
- `notes.py init`: parse, outline repair (junk headings, recovered numbered headings, appendix lifting, gap report,
  page pseudo-sections), digest with block anchors, cue sentences, draft template, partial result.
- `notes.py build`: anchor resolution (block / paragraph / table row / figure / equation / page-image / section),
  verbatim + neighbour + relocated + fuzzy quote matching, number check, section-alignment check, coverage, card
  completeness, knowledge-point merging and abbreviation check, contract mapping, Markdown/CSV/JSONL outputs.
- `tests/run_tests.py`: 28 expectations.
