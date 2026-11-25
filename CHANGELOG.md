# Changelog

## 1.1.0 - 2026-11-25
- Inputs: `.md` / `.markdown` / `.txt` / `.docx` papers (new `scripts/textdoc.py`, stdlib only) with line / Word-paragraph
  locators and `L120:` anchors; primary-paper choice by `--primary` > role > key > supplement-like name > format;
  other files parsed as supplements `S1..` with `S1::` anchors, own digests and `find --source`; missing named files reported.
- Outline: Chinese numbering (`一、` `（一）` `第N章/节` `1.1数据集`), ALL-CAPS and unnumbered named headings (Limitations,
  局限性, Appendix A ...) recovered as sub-/top-level sections; ToC lines rejected; parser no longer labels page-1 body text
  as authors when there is no Abstract heading (parse_pdf 0.3.1).
- Mixed pages (little text + large raster image): page image kept, `[pN VISUAL]` in the digest, read/unread coverage in
  `verification.visual_pages`, unread pages added to `uncertainty`.
- Cues: strong author-voice cues for limitations / conditions / data / findings, own-section bonus, weak 'does not' penalty,
  pre-checked key table rows, sections of interest; digest prints table rows and a WHERE TO LOOK head.
- Numbers: scale/percent equivalence (60 亿 = 6 billion, 128 万 = 1.28 million, 95% = 0.95, 6x10^9, 3.2k); numbers after CJK
  characters are now checked; section/page suffixes and years are context, not claims.
- Knowledge: abbreviation <-> long-form merging (incl. printed `Long Form (ABBR)`), abbreviation collisions kept apart,
  definition conflicts (numbers / wording) with sections, expansion mismatch, CJK spacing / variant spellings.
- Draft safety: `merge` (validated part files, atomic, backup) and `add` commands, lenient draft reader (fences, trailing
  commas, Python literals, key aliases / typos), `build --dry-run`, broken draft or internal error never overwrites
  result.json (`work/build_error.json`), previous result kept + regression warning, init keeps a built result.
- Fixes: `case_id` listed in the contract was overwritten with null (and `case_id: 0` lost at init); merged table cells
  (None) crashed `Table N:` anchors; contract-literal failures did not downgrade status.
- SKILL.md: one setup block (`PY=$(command -v python3 || command -v python)`, SKILL_DIR search incl. `/app/skills/*`),
  `work/env.sh` + `N` shortcut for later calls, write-in-parts workflow.
- Tests: 77 expectations (28 v1.0 + 49 v1.1, `tests/test_v11.py`).

## 1.0.0 — 2026-11-22
- First release for 阅读10｜文献总结与结构化笔记.
- `notes.py init`: parse, outline repair (junk headings, recovered numbered headings, appendix lifting, gap report,
  page pseudo-sections), digest with block anchors, cue sentences, draft template, partial result.
- `notes.py build`: anchor resolution (block / paragraph / table row / figure / equation / page-image / section),
  verbatim + neighbour + relocated + fuzzy quote matching, number check, section-alignment check, coverage, card
  completeness, knowledge-point merging and abbreviation check, contract mapping, Markdown/CSV/JSONL outputs.
- `tests/run_tests.py`: 28 expectations.
