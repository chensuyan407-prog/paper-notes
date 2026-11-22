# Minimal example (illustrative only — not an official case or answer)

Input `/input/case.json`:
```json
{"case_id": "demo-1", "pdf": "paper.pdf", "task": "Write structured notes", "output_contract": ["paper_card", "section_notes", "limitations"]}
```

Calls:
```bash
python $SKILL_DIR/scripts/notes.py init --case /input/case.json --out /app/output --work /app/work
# read /app/work/digest.md, then write /app/work/draft.json, e.g. (excerpt):
```
```json
{"card": {
   "research_question": {"text": "Can much deeper networks be trained by learning residual functions?",
                         "a": ["p1-b5: We present a residual learning framework to ease the training of networks"]},
   "main_findings": [{"text": "152-layer ResNet: 4.49% top-5 error (single model, ImageNet val)", "a": ["Table 4: ResNet-152 4.49"]}],
   "limitations": null},
 "sections": [{"section_id": "s5", "heading": "3.1 Residual Learning", "purpose": {"text": "Motivates fitting F(x)=H(x)-x", "a": ["p3-b4: we explicitly let these layers approximate a residual function"]}}],
 "unreported": [{"field": "card.limitations", "reason": "no limitations stated; checked Sec. 4 and appendix"}],
 "contract": {"paper_card": "@card", "section_notes": "@sections", "limitations": "@card.limitations"}}
```
```bash
python $SKILL_DIR/scripts/notes.py build --work /app/work
```
Illustrative build output (shape only):
```json
{"status": "partial", "items": 4, "verified": 4, "needs_review": 0, "failed": 0,
 "uncovered_sections": ["s2 1 Introduction", "..."], "card_missing": ["data", "method", "..."], "fix_these": []}
```
`notes.md` line: `- 152-layer ResNet: 4.49% top-5 error (single model, ImageNet val) 〔p.6 §4.1 Table 4〕`.
A wrong number (e.g. `4.94%`) would print `numbers_not_in_evidence:4.94` under `fix_these` and mark the line ✗.
