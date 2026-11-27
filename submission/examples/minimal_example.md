# Minimal example (illustrative only — not an official case or answer)

Input `/input/case.json` (a main paper plus a supplement; roles optional — file names like `*_SI.pdf` also work):
```json
{"case_id": "demo-1", "task": "Write structured notes",
 "materials": [{"path": "paper.pdf", "role": "primary"}, {"path": "supplementary.docx", "role": "supplement"}],
 "output_contract": ["case_id", "paper_card", "section_notes", "limitations"]}
```

Calls:
```bash
PY=$(command -v python3 || command -v python)
for d in "${SKILL_DIR:-}" /skills/weekly-skill /app/submission /app/skills/* "$(pwd)"; do
  [ -f "$d/scripts/notes.py" ] && SKILL_DIR="$d" && break; done
"$PY" "$SKILL_DIR/scripts/notes.py" init --case /input/case.json --out /app/output --work /app/work
# -> "inputs": ["paper.pdf [primary] (role=primary)", "supplementary.docx [supplement=S1] (role=supplement, ...)"]
# read /app/work/digest.md, then write the notes in two small files, e.g. /app/work/part_card.json (excerpt):
```
```json
{"card": {
   "research_question": {"text": "Can much deeper networks be trained by learning residual functions?",
                         "a": ["p1-b5: We present a residual learning framework to ease the training of networks"]},
   "main_findings": [{"text": "152-layer ResNet: 4.49% top-5 error (single model, ImageNet val)", "a": ["Table 4: ResNet-152 4.49"]},
                     {"text": "Extra ablation in the supplement: 0.61 baseline", "a": ["S1::Table 1: Baseline 0.61"]}],
   "limitations": null},
 "unreported": [{"field": "card.limitations", "reason": "no limitations stated; checked Sec. 4 and appendix"}],
 "contract": {"paper_card": "@card", "section_notes": "@sections", "limitations": "@card.limitations"}}
```
and `/app/work/part_sections.json`:
```json
{"sections": [{"section_id": "3.1", "purpose": {"text": "Motivates fitting F(x)=H(x)-x",
               "a": ["p3-b4: we explicitly let these layers approximate a residual function"]}}]}
```
```bash
. /app/work/env.sh; N build /app/work/part_card.json /app/work/part_sections.json   # merge + check + write
. /app/work/env.sh; N add card.conditions --text "SGD, mini-batch 256, lr 0.1" --a "p4-b7: We use SGD with a mini-batch size of 256"  # optional single fix
. /app/work/env.sh; N build
```
Illustrative build output (shape only):
```json
{"status": "partial", "reason": "core card fields without a verified note: ['method']; only 1/5 top-level sections have notes",
 "warnings": ["..."], "items": 6, "verified": 6, "needs_review": 0, "failed": 0,
 "uncovered_sections": ["s2 1 Introduction", "..."], "card_missing": ["data", "method", "..."], "fix_these": [], "next": "done"}
```
`notes.md` line: `- 152-layer ResNet: 4.49% top-5 error (single model, ImageNet val) 〔p.6 §4.1 Table 4〕`.
A wrong number (e.g. `4.94%`) would print `numbers_not_in_evidence:4.94` under `fix_these` and keep that line out of
the notes (`verification.dropped_items`); the same value written as `0.0449` passes with `number_equivalence`.
A truncated part file is listed under `merge.rejected` and the other parts still merge; a broken `draft.json` makes `build` exit 4 and leaves the last `result.json` as it was.

Text input instead of a PDF: `{"paper": "paper.md"}` — the digest shows `[p1-b12 L40-44]` and notes may cite
`L40: verbatim words`; `.docx` blocks keep the Word paragraph index (`source_paragraph`) and approximate page.
