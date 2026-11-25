# paper-notes — 阅读10｜文献总结与结构化笔记 (Skill, v1.1.0)

Challenge: `product-arena-06-6d8cf72b`. The Skill itself is `submission/` (SKILL.md + scripts + templates + example,
15 UTF-8 text files, ~370 KB). Everything else here is evidence and tooling.

v1.1 (2026-11-25) adds: `.md` / `.txt` / `.docx` papers and primary-vs-supplement selection (`S1::` anchors),
Chinese / ALL-CAPS / unnumbered heading recovery, mixed text+image page detection, key-table-row and author-voice
cues, unit-aware number checking (60 亿 = 6 billion), abbreviation collision / definition-conflict detection, and a
write-in-parts draft workflow (`merge` / `add` / `build --dry-run`) where a broken draft never overwrites
`result.json`. See `CHANGELOG.md` and `submission/README.md`.

**Chosen problem:** source retention + section alignment (来源保留 + 章节对齐). The Skill makes the notes' skeleton the
paper's own outline (with heading repair), keeps a unified paper card (research question, data, method, conditions,
findings, conclusion, limitations ...), and **machine-checks every note against the PDF**: quote verbatim in the cited
block, anchor inside the summarised section, numbers in the note present in the cited text/table row, card fields
filled or declared unreported, every section covered, duplicate knowledge points merged, abbreviations checked.

## Layout

| path | what |
|---|---|
| `submission/` | **the Skill** (install as `/skills/weekly-skill`) — see `submission/README.md` for method, outputs, limits |
| `tests/run_tests.py` | self-check: synthetic two-column paper + 14 adversarial note perturbations + encrypted + scanned inputs; then runs `tests/test_v11.py` |
| `tests/test_v11.py` | v1.1 expectations: md/txt/docx inputs, primary/supplement, number equivalence, knowledge conflicts, draft safety, mixed pages, heading recovery |
| `tests/make_samples.py` | synthetic PDF generator (exact ground truth; from pdf-evidence-reader v0.3) |
| `src/reproduce.py` | runs the self-check (+ optional outline before/after on PDFs you pass) → `execution/results/metrics.json` |
| `execution/results/example_bn_dev/` | one development run on arXiv 1502.03167 (BatchNorm): draft, result.json, notes.md, card CSV, knowledge JSONL, verification — **dev example, not an official case** |

```bash
pip install -r requirements.txt
python src/reproduce.py                       # self-check, writes execution/results/metrics.json
python src/reproduce.py --pdfs some_paper.pdf # + outline before/after repair
```

## Evidence recorded (what was actually run, 2026-11-22, Windows, Python 3.13, PyMuPDF 1.28.2)

| check | result |
|---|---|
| self-check (`tests/run_tests.py`) | 28/28 expectations met: good block quote / table-row / column-break quote → verified; fabricated quote, wrong number, number from another table row, missing anchor, unknown table, off-page bbox → failed; wrong block id with real quote (relocated), paraphrased quote (fuzzy), figure reading, whole-section anchor, section note anchored in another section → needs review; uncovered section reported; notes re-ordered to the paper's order; duplicate term merged; contract auto-map; encrypted → `failed`; image-only → pseudo section |
| outline repair, arXiv 1502.03167 | parser: 13 sections incl. two junk `1 N` headings and none of §2–§3.4; repaired: 17 sections, 2 junk removed, 6 headings recovered (§2, §3, §3.1–§3.4) |
| outline repair, GloVe (Pennington et al. 2014) | §4.4 recovered (parser had §4.3 → §4.5) |
| outline repair, ResNet (1512.03385) | appendices A–C lifted out of *References* |
| dev run on 1502.03167 (agent = Claude, not the platform model) | first build flagged 1 real error in the draft (`1000` classes cited to a sentence without that number); after fix 37/37 items verified, 0 failed, 7/7 top-level sections covered (16 section entries incl. sub-sections, appendix skipped with reason), status `success`; init ≈ 1–2 s, build < 1 s |
| robustness (init only) | Chinese single-column sample: outline `1 引言 / 2 方法 / 2.1 数据`; scanned sample: image-only pseudo section with page-image path; encrypted: `failed`/`encrypted`; GPT-3 (75 pp): digest capped ≈ 70–90 KB |

### v1.1 evidence (2026-11-25, same machine)

| check | result |
|---|---|
| self-check (`tests/run_tests.py`, via `src/reproduce.py`) | 77/77 expectations met (the 28 v1.0 ones unchanged + 49 new) |
| outline, 7 real PDFs, v1.0 (`6257128`) vs v1.1 init | no heading lost on Attention, BERT (scanned copy), GloVe, ResNet, BatchNorm, Kaplan (2001.08361), Chinchilla (2203.15556); added ResNet *PASCAL VOC* / *MS COCO*, Chinchilla *H.2 MMLU*; a Kaplan ToC line (`Appendices 20`) was first mis-recovered and is now rejected (test added) |
| real-paper bug found | ResNet / Attention tables contain merged (None) cells: `Table N: ...` anchors crashed v1.0 `build`; fixed + test |
| ResNet end-to-end with `add` + `build` | 10 items: 9 verified, 1 failed = the deliberately wrong `22.43%` (paper: 21.43); `0.2143` accepted as `21.43%` via number equivalence; top-3 `conditions` cues = the SGD / lr / weight-decay sentences |

Not done (honest): no A/B against the platform's base agent or DeepSeek; the platform runs that comparison. The dev
PDFs (arXiv/ACL) are not redistributed here; their SHA-256 are in `execution/results/example_bn_dev/result.json` (`sources`).

## Versions / maintenance

v1.0.0 — 2026-11-22, first release (author: chensuyan407). Parser code reused from the author's pdf-evidence-reader v0.3.0.
Changes: see `CHANGELOG.md`.
