#!/usr/bin/env python3
"""Self-check for paper-notes: build a synthetic two-column paper with known content, write a draft with
good notes and adversarial perturbations (one defect each), run init + build, and compare every item's
status with the expected one. Also checks section coverage, ordering, knowledge merging, contract mapping,
encrypted and image-only PDFs.

    python tests/run_tests.py [--keep DIR]
Exit code 0 = all expectations met. Prints a table (case, expected, actual).
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.join(os.path.dirname(HERE), "submission", "scripts")
sys.path.insert(0, HERE)
import make_samples as M  # noqa: E402

NOTES = os.path.join(SKILL, "notes.py")


def run(*args):
    r = subprocess.run([sys.executable, NOTES, *args], capture_output=True, text=True, encoding="utf-8")
    out = r.stdout[r.stdout.find("{"):] if "{" in r.stdout else r.stdout
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        raise SystemExit(f"notes.py {args[0]} failed:\n{r.stdout}\n{r.stderr}")


def read_json(directory, name="result.json"):
    with open(os.path.join(directory, name), encoding="utf-8") as fh:
        return json.load(fh)


def case_dir(root, name, pdf_maker, contract):
    d = os.path.join(root, name)
    os.makedirs(os.path.join(d, "input"), exist_ok=True)
    pdf_maker(os.path.join(d, "input", "paper.pdf"))
    with open(os.path.join(d, "input", "case.json"), "w", encoding="utf-8") as fh:
        json.dump({"case_id": name, "pdf": "paper.pdf", "output_contract": contract}, fh)
    return d


# (label, card field or section, item, expected status, expected problem substring)
def items():
    I = []
    I.append(("good_block_quote", "card.research_question",
              {"text": "A procedure restoring reading order with page/bbox pointers",
               "a": ["<<restores the reading order>>: restores the reading order and keeps a pointer from every paragraph"]}, "verified", None))
    I.append(("good_table_row", "card.main_findings",
              {"text": "Layout-aware parser: order accuracy 1.00 vs baseline 0.61",
               "a": ["Table 1: Layout-aware 1.00", "Table 1: Baseline 0.61"]}, "verified", None))
    I.append(("quote_across_column_break", "card.method",
              {"text": "Pointers back to the original layout",
               "a": ["<<every answer can be checked>>: checked against the original layout of the document without guessing"]}, "verified", None))
    I.append(("fabricated_quote", "card.conclusion",
              {"text": "The parser is optimal for all layouts",
               "a": ["<<We first detect the column gutter>>: the parser is provably optimal for every possible layout"]}, "failed", "quote_not_found"))
    I.append(("wrong_number", "card.main_findings",
              {"text": "Baseline order accuracy 0.66", "a": ["Table 1: Baseline"]}, "failed", "numbers_not_in_evidence"))
    I.append(("number_from_other_row", "card.main_findings",
              {"text": "Baseline header leak 0 pages", "a": ["Table 1: Baseline 4"]}, "verified", "small_numbers_unchecked"))  # single digits: informational only
    I.append(("number_other_row_decimal", "card.main_findings",
              {"text": "Baseline order accuracy 1.00", "a": ["Table 1: Baseline 0.61"]}, "failed", "numbers_not_in_evidence"))
    I.append(("wrong_block_id_real_quote", "card.data",
              {"text": "Evaluated on synthetic pages with known ground truth",
               "a": ["p2-b1: evaluated on synthetic pages with a known ground truth"]}, "needs_review", "relocated"))
    I.append(("paraphrased_quote", "card.conditions",
              {"text": "Left column read before right column inside a band",
               "a": ["<<Inside each band the left column>>: inside every band the left column is read before the right one"]}, "needs_review", "quote_fuzzy"))
    I.append(("no_anchor", "card.limitations",
              {"text": "Only synthetic data", "a": []}, "failed", "no_anchor"))
    I.append(("unknown_table", "card.main_findings",
              {"text": "Table 7 numbers", "a": ["Table 7"]}, "failed", "table_not_found"))
    I.append(("bad_bbox_image_anchor", "card.future_work",
              {"text": "Read from page image", "a": ["p1@0,0,9000,9000: some words"]}, "failed", "bbox_off_page"))
    I.append(("figure_reading", "card.main_findings",
              {"text": "Curve rises with page count", "a": ["Fig. 1: the curve rises"]}, "needs_review", "figure_reading_unverified"))
    I.append(("coarse_section_anchor", "card.motivation_gap",
              {"text": "Two-column order problem", "a": ["s1"]}, "needs_review", "coarse_section_anchor"))
    return I


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", default=None)
    a = ap.parse_args()
    root = a.keep or tempfile.mkdtemp(prefix="paper_notes_test_")
    if os.path.exists(root) and a.keep:
        shutil.rmtree(root)
    os.makedirs(root, exist_ok=True)
    results, ok_all = [], True

    def expect(label, exp, act, extra=""):
        nonlocal ok_all
        ok = exp == act
        ok_all &= ok
        results.append((label, exp, act, "PASS" if ok else "FAIL", extra))

    # ---------------- main synthetic paper
    d = case_dir(root, "two_column", M.sample_a, ["paper_card", "section_notes", "knowledge_points", "limitations"])
    init = run("init", "--case", os.path.join(d, "input", "case.json"), "--out", os.path.join(d, "output"),
               "--work", os.path.join(d, "work"))
    expect("outline_headings", ["1 Introduction", "2 Method", "2.1 Reading order", "3 Results", "References"],
           [" ".join(x.split()[2:]).rsplit(" pp", 1)[0].strip() for x in init["outline"]])
    sys.path.insert(0, SKILL)
    import notes_lib as L  # noqa: E402
    D = L.Doc(os.path.join(d, "output", "parsed", "paper"))

    def bid_for(quote):
        hit, _ = D._match_quote(quote, D.order)
        return hit

    draft_p = os.path.join(d, "work", "draft.json")
    draft = json.load(open(draft_p, encoding="utf-8"))
    for k in draft["card"]:
        if k not in ("title", "authors"):
            draft["card"][k] = []
    cases = items()
    for label, field, it, _, _ in cases:
        it = json.loads(json.dumps(it))
        fixed = []
        for x in it["a"]:
            if x.startswith("<<"):
                loc, q = x[2:].split(">>: ", 1)
                x = f"{bid_for(loc) or 'p1-b99'}: {q}"
            fixed.append(x)
        it["a"] = fixed
        it["label"] = label
        draft["card"][field.split(".")[1]].append(it)
    # sections: introduce one note anchored outside its section, and omit section 3 to test coverage
    sec_ids = {s["heading"]: s["section_id"] for s in draft["sections"]}
    for s in draft["sections"]:
        if s["heading"] == "1 Introduction":
            s["purpose"] = {"text": "Motivates reading-order recovery", "a": [f"{bid_for('Scientific articles are usually typeset')}: usually typeset in two columns"]}
        if s["heading"] == "2 Method":
            s["method"] = {"text": "Gutter detection from narrow blocks", "a": [f"{bid_for('We first detect the column gutter')}: detect the column gutter"]}
            s["results"] = {"text": "anchored in Results instead", "a": [f"{bid_for('Table 1 lists the scores')}: Table 1 lists the scores"]}
    draft["knowledge"] = [
        {"term": "reading order", "aliases": [], "kind": "concept", "definition": "order in which blocks are read",
         "a": [f"{bid_for('Inside each band the left column')}: the left column is read before the right column"]},
        {"term": "Reading orders", "aliases": [], "kind": "concept", "definition": "column-wise order", "a": []},
    ]
    draft["unreported"] = []
    draft["contract"] = {"paper_card": "@card", "section_notes": "@sections", "knowledge_points": "@knowledge"}
    json.dump(draft, open(draft_p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    run("build", "--work", os.path.join(d, "work"))
    output = os.path.join(d, "output")
    res = read_json(output)
    ver = read_json(output, "verification.json")
    expect("result_matches_contract", {"case_id", "paper_card", "section_notes", "knowledge_points", "limitations"}, set(res))
    expect("init_contract_skeleton", set(res) - {"case_id"}, set(init["output_contract"]))
    expect("init_required_dimensions", {"research_question", "method", "data", "conditions", "main_findings", "conclusion", "limitations"},
           set(init["coverage_checklist"]))
    by_label = {}
    for k, v in res["paper_card"].items():
        for it in v:
            if it.get("label"):
                by_label[it["label"]] = it
    for it in ver["dropped_items"]:  # notes without a usable anchor
        if it.get("label"):
            by_label[it["label"]] = it
    for label, field, it, exp, prob in cases:
        got = by_label.get(label, {}).get("check", {})
        txt = json.dumps(got) + json.dumps(by_label.get(label, {}).get("anchors", []))
        expect(label, exp, got.get("status"), "" if (prob is None or prob in txt) else f"missing '{prob}'")
        if prob and prob not in txt:
            ok_all = False
    secs = {s["heading"]: s for s in res["section_notes"]}
    expect("section_note_outside_section", "needs_review", secs["2 Method"]["results"][0]["check"]["status"])
    expect("uncovered_section_reported", True, any("3 Results" in m for m in ver["section_coverage"]["missing"]))
    expect("section_order_follows_paper", ["1 Introduction", "2 Method", "2.1 Reading order", "3 Results"],
           [s["heading"] for s in res["section_notes"]])
    expect("knowledge_merged", 1, len(res["knowledge_points"]))
    expect("contract_auto_map_limitations", True, isinstance(res["limitations"], list))
    retained = next(it for it in res["paper_card"]["main_findings"] if it.get("label") == "wrong_number")
    expect("weak_claim_kept_with_warning", True, bool(retained.get("warn")))
    evidence = retained["anchors"][0]
    expect("inline_source_location", True, bool(evidence.get("page") and evidence.get("section") and evidence.get("quote")))
    with open(os.path.join(output, "notes.md"), encoding="utf-8") as fh:
        expect("markdown_inline_source", True, any(evidence["quote"].replace("|", "&#124;") in line and evidence["section"] in line
                                                   and retained["text"] in line for line in fh))
    expect("status_success_with_warnings", ["success", True], [ver["status"], any("failed verification" in w for w in ver["run_status"]["warnings"])])
    expect("uncovered_section_is_warning", True, any("without notes" in w for w in ver["run_status"]["warnings"]))
    with open(draft_p, "w", encoding="utf-8") as fh:  # only a fabricated note left: no substantive notes -> partial
        json.dump({"card": {"research_question": {"text": "x", "a": ["p1-b1: words that are not in the paper at all"]}}}, fh)
    run("build", "--work", os.path.join(d, "work"))
    rp_ = read_json(output, "verification.json")
    expect("status_partial_without_substantive_notes", "partial", rp_["status"], rp_["run_status"]["reason"])
    expect("card_missing_none_when_filled_or_failed", [], [k for k in ver["card_missing"] if k not in ("conclusion", "limitations")])
    # v1.2: a field whose only note failed (fabricated quote / no anchor) is recorded as not filled, not left with a ✗ note
    expect("failed_only_field_auto_unreported", True, any(u.get("auto") and u.get("field") == "card.limitations" for u in ver["unreported"]))
    for f in ("notes.md", "paper_card.csv", "knowledge_points.jsonl", "verification.json"):
        expect(f"output_{f}", True, os.path.exists(os.path.join(d, "output", f)))

    # ---------------- encrypted
    d2 = os.path.join(root, "encrypted")
    os.makedirs(os.path.join(d2, "input"), exist_ok=True)
    M.sample_a(os.path.join(d2, "plain.pdf"))
    M.sample_encrypted(os.path.join(d2, "plain.pdf"), os.path.join(d2, "input", "paper.pdf"))
    json.dump({"case_id": "enc", "output_contract": ["paper_card"]}, open(os.path.join(d2, "input", "case.json"), "w"))
    os.remove(os.path.join(d2, "plain.pdf"))
    run("init", "--case", os.path.join(d2, "input", "case.json"), "--out", os.path.join(d2, "output"), "--work", os.path.join(d2, "work"))
    r2 = read_json(os.path.join(d2, "output"), "verification.json")
    expect("encrypted_status_failed", "failed", r2["status"], r2["run_status"]["reason"])

    # ---------------- image-only page
    d3 = os.path.join(root, "scanned")
    os.makedirs(os.path.join(d3, "input"), exist_ok=True)
    M.sample_a(os.path.join(d3, "plain.pdf"))
    M.sample_scanned(os.path.join(d3, "plain.pdf"), os.path.join(d3, "input", "paper.pdf"))
    os.remove(os.path.join(d3, "plain.pdf"))
    json.dump({"case_id": "scan", "output_contract": ["paper_card"]}, open(os.path.join(d3, "input", "case.json"), "w"))
    i3 = run("init", "--case", os.path.join(d3, "input", "case.json"), "--out", os.path.join(d3, "output"), "--work", os.path.join(d3, "work"))
    expect("scanned_pseudo_section", True, any("image-only" in x or "no heading" in x for x in i3["outline"]) or bool(i3["unresolved_pages"][0]) is False,
           "; ".join(i3["outline"][:2]))

    # ---------------- v1.1: multi-format inputs, primary/supplement, number equivalence, knowledge, draft safety, mixed pages
    import test_v11  # noqa: E402
    try:
        test_v11.main(root, expect)
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        expect("v11_suite_completed", True, False, f"{type(e).__name__}: {e}")

    w = max(len(r[0]) for r in results)
    for r in results:
        print(f"{r[3]}  {r[0]:<{w}}  expected={r[1]!s:<14} actual={r[2]!s:<14} {r[4]}")
    print(f"\n{sum(r[3] == 'PASS' for r in results)}/{len(results)} passed; work dir {root}")
    sys.exit(0 if ok_all else 1)


if __name__ == "__main__":
    main()
