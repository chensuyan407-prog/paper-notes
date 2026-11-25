#!/usr/bin/env python3
"""v1.1 expectations (called by run_tests.py): non-PDF inputs, primary/supplement selection, cross-source anchors,
line anchors, number equivalence (60 亿 = 6 billion ...), Chinese number checking, knowledge merge / collision /
definition conflicts, draft safety (broken JSON never overwrites result.json, lenient repair, dry-run, merge/add),
mixed text+image pages, unnumbered / ALL-CAPS heading recovery, case_id 0 with case_id in the contract."""
import hashlib
import json
import os
import subprocess
import sys
import zipfile

try:
    import pymupdf as fitz
except ImportError:  # pragma: no cover
    import fitz

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.join(os.path.dirname(HERE), "submission", "scripts")
NOTES = os.path.join(SKILL, "notes.py")
sys.path.insert(0, HERE)
import make_samples as M  # noqa: E402


def run(*args, ok_codes=(0,)):
    r = subprocess.run([sys.executable, NOTES, *args], capture_output=True, text=True, encoding="utf-8")
    out = r.stdout[r.stdout.find("{"):] if "{" in r.stdout else r.stdout
    try:
        js = json.loads(out)
    except json.JSONDecodeError:
        js = {"_raw": r.stdout, "_err": r.stderr}
    js["_code"] = r.returncode
    return js


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


PAPER_MD = """# Section-Aligned Notes for Long Papers

Ada Reader, Bo Writer

Abstract: We propose a section-aligned note method and evaluate it on 1,280,000 abstracts.

## 1 Introduction

Generic summaries ignore the structure of a paper. This paper aims to keep every note linked to its source.
A convolutional neural network (CNN) encodes each page. Self-attention (SA) links sections.

## 2 Method

Our model has about 6 billion parameters and was trained for 90 epochs with a learning rate of 0.001.
We assume that section headings are printed in the text.

1. Read the source file.
2. Split it into sections.

| Method | Acc | F1 |
|---|---|---|
| Baseline | 0.61 | 0.55 |
| Ours | 0.95 | 0.90 |

Table 1: Main results on the benchmark.

## 3 Results

The proposed method outperforms the baseline by a large margin.

## Limitations

A limitation of this study is the small sample of English papers, so the results may not generalize.

## References

[1] A. Author. A paper. 2020.
"""

PAPER_TXT = ("面向长文献的结构化笔记\n\n一、引言\n科研文献阅读耗时，本研究旨在减少整理时间。\n\n（一）研究背景\n\n已有方法套用通用模板。\n\n"
             "二、研究方法\n\n1.1数据集\n\n共收集 1200 篇论文作为样本。\n\f三、结果\n\n准确率达到 95.3%。\n\n局限性\n\n"
             "本研究的局限在于样本量较小。\n")


def make_docx(path):
    W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'

    def p(text, style=None, bold=False, br_page=False):
        ppr = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
        rpr = "<w:rPr><w:b/></w:rPr>" if bold else ""
        brk = '<w:r><w:br w:type="page"/></w:r>' if br_page else ""
        return f'<w:p>{ppr}{brk}<w:r>{rpr}<w:t xml:space="preserve">{text}</w:t></w:r></w:p>'

    def tbl(rows):
        return "<w:tbl>" + "".join("<w:tr>" + "".join(f"<w:tc><w:p><w:r><w:t>{c}</w:t></w:r></w:p></w:tc>" for c in r) + "</w:tr>"
                                   for r in rows) + "</w:tbl>"
    body = (p("Notes on Word Papers", "Title") + p("Introduction", "Heading1")
            + p("This paper studies structured notes from Word files.") + p("Method", "Heading1")
            + p("Training Setup", "Heading2") + p("We trained the model for 12 epochs.")
            + p("Table 1: Scores on the test set.") + tbl([["Method", "Acc"], ["Baseline", "0.70"], ["Ours", "0.88"]])
            + p("Results", "Heading1", br_page=True) + p("Ours reaches 0.88 accuracy on the test set."))
    styles = (f'<w:styles {W}><w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/></w:style>'
              f'<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/></w:style>'
              f'<w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/></w:style></w:styles>')
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        z.writestr("word/document.xml", f'<?xml version="1.0" encoding="UTF-8"?><w:document {W}><w:body>{body}</w:body></w:document>')
        z.writestr("word/styles.xml", styles)


def make_heading_pdf(path):
    """Single-column PDF: numbered sections plus an unnumbered bold 'Limitations' and an ALL-CAPS bold heading."""
    doc = fitz.open()
    pg = doc.new_page(width=612, height=792)
    y = 60

    def put(text, size=10, font="helv", gap=8):
        nonlocal y
        h = M.measure(text, 500, size, font) + 2
        pg.insert_textbox(fitz.Rect(56, y, 556, y + h), text, fontsize=size, fontname=font)
        y += h + gap
    put("Recovering Unnumbered Headings", 17, "hebo", 10)
    put("1 Introduction", 11, "hebo", 4)
    put("Papers often put limitations under an unnumbered heading inside the discussion section of the paper.")
    put("2 Experiments", 11, "hebo", 4)
    put("EXPERIMENTAL SETUP", 10, "hebo", 4)
    put("We trained every model for 30 epochs on a single machine with the same random seed for each run.")
    put("3 Discussion", 11, "hebo", 4)
    put("The method works on the synthetic pages that we generated for this test of the outline repair.")
    put("Limitations", 10, "hebo", 4)
    put("A limitation of this study is that only synthetic single-column pages were evaluated here.")
    doc.save(path)


def make_mixed_pdf(src, path):
    """Page 1-2 of sample A, then a page that is mostly a pasted raster image with one short caption line."""
    s = fitz.open(src)
    d = fitz.open()
    d.insert_pdf(s)
    pix = s[1].get_pixmap(dpi=60)
    pg = d.new_page(width=612, height=792)
    pg.insert_image(fitz.Rect(56, 80, 556, 600), pixmap=pix)
    pg.insert_text((56, 640), "Figure 2: Results pasted as an image.", fontsize=9, fontname="helv")
    pg.insert_text((56, 660), "The pasted image above holds the full score table; its numbers are not in the text layer.",
                   fontsize=9, fontname="helv")
    d.save(path)


def main(root, expect):
    # ---------------- A: Markdown primary + PDF supplement, roles in case.json, case_id 0 with case_id in contract
    d = os.path.join(root, "md_primary")
    os.makedirs(os.path.join(d, "input"), exist_ok=True)
    open(os.path.join(d, "input", "paper.md"), "w", encoding="utf-8").write(PAPER_MD)
    M.sample_a(os.path.join(d, "input", "supp.pdf"))
    case = {"case_id": 0, "materials": [{"path": "supp.pdf", "role": "supplement"}, {"path": "paper.md", "role": "primary"}],
            "output_contract": {"type": "object", "required": ["case_id", "paper_card", "limitations"],
                                "properties": {"case_id": {"type": "integer"}, "paper_card": {"type": "object"},
                                               "limitations": {"type": "array"}}}}
    json.dump(case, open(os.path.join(d, "input", "case.json"), "w"))
    W, O = os.path.join(d, "work"), os.path.join(d, "output")
    init = run("init", "--case", os.path.join(d, "input", "case.json"), "--out", O, "--work", W)
    expect("md_primary_selected_by_role", "paper.md", os.path.basename(init.get("primary") or ""))
    expect("md_supplement_parsed_as_S1", True, any("supp.pdf [supplement=S1]" in x for x in init.get("inputs", [])))
    expect("md_outline", ["1 Introduction", "2 Method", "3 Results", "Limitations", "References"],
           [" ".join(x.split()[2:]).rsplit(" pp", 1)[0].strip().replace(" [skip]", "") for x in init["outline"]][1:])
    expect("md_abstract_section", True, init["outline"][0].split()[2:3] == ["Abstract"], init["outline"][0])
    expect("env_sh_written", True, os.path.exists(os.path.join(W, "env.sh")))
    cues = json.load(open(os.path.join(W, "cues.json"), encoding="utf-8"))
    expect("cue_limitation_strong_first", True, bool(cues["limitations"]) and "A limitation of this study" in cues["limitations"][0]["anchor"],
           (cues["limitations"] or [{}])[0].get("anchor", "")[:60])
    expect("cue_table_row_ours", True, any(x["anchor"] == "Table 1: Ours 0.95" for x in cues["table_rows"]))
    expect("cue_conditions_epochs", True, any("90 epochs" in x["anchor"] for x in cues["conditions"][:3]))
    sys.path.insert(0, SKILL)
    import notes_lib as L
    D = L.Doc(os.path.join(O, "parsed", "paper"))

    def bid(q):
        return D._match_quote(q, D.order)[0]
    ln_intro = D.blocks[bid("This paper aims to keep every note")]["line_start"]
    sec = {s["title"]: s["id"] for s in D.sections}
    # notes written in parts: two fragment files + add commands (no full-draft rewrite)
    part1 = {"card": {
        "research_question": {"text": "Keep every note linked to its source", "a": [f"L{ln_intro}: aims to keep every note linked to its source"]},
        "data": {"text": "1,280,000 abstracts", "a": [f"{bid('We propose a section-aligned')}: evaluate it on 1,280,000 abstracts"]},
        "method": {"text": "参数规模约 60 亿，训练 90 个 epoch", "a": [f"{bid('Our model has about')}: about 6 billion parameters"]},
        "conditions": [{"text": "学习率 0.001", "a": [f"{bid('Our model has about')}: a learning rate of 0.001"], "label": "lr"},
                       {"text": "参数规模约 70 亿", "a": [f"{bid('Our model has about')}: about 6 billion parameters"], "label": "wrong_scale"}],
        "main_findings": [{"text": "Ours accuracy 95%", "a": ["Table 1: Ours 0.95"], "label": "pct"},
                          {"text": "本文方法准确率为0.66", "a": ["Table 1: Ours 0.95"], "label": "cjk_wrong"},
                          {"text": "覆盖 128 万篇摘要", "a": [f"{bid('We propose a section-aligned')}: 1,280,000 abstracts"], "label": "wan"},
                          {"text": "Supplement baseline order accuracy 0.61", "a": ["S1::Table 1: Baseline 0.61"], "label": "supp"},
                          {"text": "bad source", "a": ["S9::p1-b1: anything"], "label": "bad_source"}],
        "conclusion": {"text": "Outperforms the baseline", "a": [f"{bid('outperforms the baseline')}: outperforms the baseline"]},
        "limitations": {"text": "Small English sample", "a": [f"{bid('A limitation of this study')}: the small sample of English papers"]}}}
    part2 = {"sections": [{"section_id": "1", "purpose": {"text": "Link notes to sources", "a": [f"L{ln_intro}: keep every note linked"]}},
                          {"section_id": "2 Method", "method": {"text": "90 epochs", "a": [f"{bid('Our model has about')}: trained for 90 epochs"]}},
                          {"section_id": "s99", "results": {"text": "x", "a": []}}],
             "knowledge": [{"term": "CNN", "kind": "abbreviation", "definition": "encodes each page",
                            "a": [f"{bid('A convolutional neural network')}: encodes each page"]},
                           {"term": "convolutional neural network", "kind": "method", "definition": "network that encodes each page",
                            "a": [f"{bid('A convolutional neural network')}: A convolutional neural network (CNN)"]},
                           {"term": "SA", "aliases": ["self-attention"], "kind": "method", "definition": "links sections",
                            "a": [f"{bid('Self-attention (SA)')}: Self-attention (SA) links sections"]},
                           {"term": "SA", "aliases": ["simulated annealing"], "kind": "method", "definition": "an optimiser", "a": []},
                           {"term": "batch size", "kind": "variable", "definition": "32 samples per step", "section_id": sec["Method"]},
                           {"term": "batch-size", "kind": "variable", "definition": "64 samples per step", "section_id": sec["Results"]}]}
    for name, obj in (("part1.json", part1), ("part2.json", part2)):
        json.dump(obj, open(os.path.join(W, name), "w", encoding="utf-8"), ensure_ascii=False)
    m = run("merge", os.path.join(W, "part1.json"), os.path.join(W, "part2.json"), "--work", W)
    expect("merge_rejects_unknown_section", ["s99"], [x.get("section_id") for x in m.get("rejected", [])])
    run("add", "sections.3.results", "--text", "Outperforms the baseline", "--a", f"{bid('outperforms the baseline')}: outperforms the baseline", "--work", W)
    run("add", "sections.Limitations.key_points", "--text", "Small sample", "--a", f"{bid('A limitation of this study')}: small sample of English papers", "--work", W)
    run("add", "contract.paper_card", "--value", "@card", "--work", W)
    run("add", "unreported.card.future_work", "--reason", "no future work stated (searched Limitations)", "--work", W)
    dr = run("build", "--work", W, "--dry-run")
    expect("dry_run_writes_nothing", True, dr.get("dry_run") is True and json.load(open(os.path.join(O, "result.json"), encoding="utf-8"))["run_status"]["stage"] == "init")
    b = run("build", "--work", W)
    res = json.load(open(os.path.join(O, "result.json"), encoding="utf-8"))
    by = {it.get("label"): it for v in res["notes"]["paper_card"].values() for it in v if it.get("label")}
    card = res["notes"]["paper_card"]
    expect("line_anchor_verified", "verified", card["research_question"][0]["check"]["status"])
    expect("line_anchor_has_lines", True, card["research_question"][0]["anchors"][0].get("line_start") == ln_intro)
    expect("num_equiv_60yi_6billion", "verified", card["method"][0]["check"]["status"], json.dumps(card["method"][0]["check"], ensure_ascii=False)[:120])
    expect("num_equiv_wrong_scale_fails", "failed", by["wrong_scale"]["check"]["status"])
    expect("num_equiv_percent_decimal", "verified", by["pct"]["check"]["status"])
    expect("num_cjk_context_checked", "failed", by["cjk_wrong"]["check"]["status"])
    expect("num_equiv_128wan", "verified", by["wan"]["check"]["status"])
    expect("supplement_anchor_verified", ["verified", "S1"], [by["supp"]["check"]["status"], by["supp"]["anchors"][0].get("source")])
    expect("supplement_unknown_source_fails", "failed", by["bad_source"]["check"]["status"])
    kp = {k["term"]: k for k in res["notes"]["knowledge_points"]}
    expect("kp_abbr_merged_with_long_form", True, "CNN" in kp and "convolutional neural network" not in kp)
    expect("kp_abbr_collision_not_merged", 2, sum(1 for k in res["notes"]["knowledge_points"] if k["term"] == "SA"))
    expect("kp_collision_reported", True, any(c["kind"] == "abbreviation_collision" for c in res["verification"]["knowledge_conflicts"]))
    expect("kp_definition_conflict_numbers", True, bool(kp.get("batch size", {}).get("definition_conflict"))
           and any(c.get("kind") == "definition_conflict" for c in res["conflicts"]))
    expect("case_id_zero_kept", 0, res["case_id"])
    expect("case_id_contract_not_unreported", False, any(u.get("field") == "case_id" for u in res["unreported"]))
    expect("contract_limitations_auto", True, isinstance(res["limitations"], list) and bool(res["limitations"]))
    expect("sections_by_number_and_title", True, all(s["section_id"] not in (b.get("uncovered_sections") or []) for s in res["notes"]["section_notes"][:3])
           and not [x for x in res["verification"]["section_coverage"]["missing"] if "Introduction" in x or "Method" in x])
    # draft safety
    good = sha(os.path.join(O, "result.json"))
    dp = os.path.join(W, "draft.json")
    txt = open(dp, encoding="utf-8").read()
    open(dp, "w", encoding="utf-8").write(txt[: len(txt) // 2])  # truncated JSON
    bad = run("build", "--work", W)
    expect("broken_draft_exit_4", 4, bad["_code"])
    expect("broken_draft_result_untouched", good, sha(os.path.join(O, "result.json")))
    expect("broken_draft_error_file", True, os.path.exists(os.path.join(W, "build_error.json")) and "line" in bad.get("error", ""))
    obj = json.loads(txt)
    tc = json.dumps(obj, ensure_ascii=False, indent=1).replace('\n ]', ',\n ]', 1)  # trailing comma
    open(dp, "w", encoding="utf-8").write("```json\n" + tc + "\n```")
    rb = run("build", "--work", W)
    expect("lenient_draft_repaired", True, rb["_code"] == 0 and bool(rb.get("draft_repairs")), str(rb.get("draft_repairs")))
    open(dp, "w", encoding="utf-8").write(json.dumps({"card": {}, "sections": []}))
    rg = run("build", "--work", W)
    expect("regression_warning", True, "regression_warning" in rg and os.path.exists(os.path.join(W, "result.prev.json")))

    # ---------------- B: plain text, Chinese numbering, form-feed pages
    d = os.path.join(root, "txt_cn")
    os.makedirs(os.path.join(d, "input"), exist_ok=True)
    open(os.path.join(d, "input", "paper.txt"), "w", encoding="utf-8").write(PAPER_TXT)
    json.dump({"case_id": "txt", "output_contract": ["paper_card"]}, open(os.path.join(d, "input", "case.json"), "w"))
    W, O = os.path.join(d, "work"), os.path.join(d, "output")
    it = run("init", "--case", os.path.join(d, "input", "case.json"), "--out", O, "--work", W)
    expect("txt_cn_outline", ["一、 引言", "（一） 研究背景", "二、 研究方法", "1.1 数据集", "三、 结果", "局限性"],
           [" ".join(x.split()[2:]).rsplit(" pp", 1)[0].strip() for x in it["outline"]])
    expect("txt_cn_levels", ["L1", "L2", "L1", "L2", "L1", "L1"], [x.split()[1] for x in it["outline"]])
    D2 = L.Doc(os.path.join(O, "parsed", "paper"))
    hit = D2._match_quote("准确率达到", D2.order)[0]
    expect("txt_formfeed_page2", True, bool(hit) and hit.startswith("p2-"), str(hit))
    json.dump({"card": {"main_findings": {"text": "准确率 95.3%", "a": [f"{hit}: 准确率达到 95.3%"]}}}, open(os.path.join(W, "p.json"), "w", encoding="utf-8"), ensure_ascii=False)
    run("merge", os.path.join(W, "p.json"), "--work", W)
    run("build", "--work", W)
    r2 = json.load(open(os.path.join(O, "result.json"), encoding="utf-8"))
    expect("txt_cn_quote_verified", "verified", r2["notes"]["paper_card"]["main_findings"][0]["check"]["status"])

    # ---------------- C: Word document
    d = os.path.join(root, "docx")
    os.makedirs(os.path.join(d, "input"), exist_ok=True)
    make_docx(os.path.join(d, "input", "paper.docx"))
    json.dump({"case_id": "docx", "inputs": {"paper": "paper.docx"}, "output_contract": ["paper_card"]}, open(os.path.join(d, "input", "case.json"), "w"))
    W, O = os.path.join(d, "work"), os.path.join(d, "output")
    it = run("init", "--case", os.path.join(d, "input", "case.json"), "--out", O, "--work", W)
    expect("docx_outline", ["Introduction", "Method", "Training Setup", "Results"],
           [" ".join(x.split()[2:]).rsplit(" pp", 1)[0].strip() for x in it.get("outline", [])])
    D3 = L.Doc(os.path.join(O, "parsed", "paper"))
    expect("docx_table_row", "quote_in_table", D3.resolve("Table 1: Ours 0.88").get("check"))
    expect("docx_page_break", True, (D3._match_quote("Ours reaches 0.88", D3.order)[0] or "").startswith("p2-"))
    expect("docx_title", "Notes on Word Papers", next((b["text"] for b in D3.d["blocks"] if b["role"] == "title"), None))
    # real-paper regressions: merged table cells are None (crashed v1.0 on 'Table N: ...'); ToC lines are not headings
    D3.tables["9"] = {"caption": "Table 9: merged cells", "rows": [["Model", None, "Acc"], ["Ours", None, "0.88"]],
                      "cells": [{"text": None}, {"text": "0.88"}]}
    expect("table_none_cells_no_crash", "quote_in_table", D3.resolve("Table 9: Ours 0.88").get("check"))
    expect("toc_line_not_heading", [None, None, "appendix"],
           [L.classify_heading("Appendices 20"), L.classify_heading("3 Results ........ 12"),
            (L.classify_heading("Appendix A: Proofs") or {}).get("kind")])

    # ---------------- D: two PDFs, no roles: supplement-like file name loses
    d = os.path.join(root, "two_pdfs")
    os.makedirs(os.path.join(d, "input"), exist_ok=True)
    M.sample_a(os.path.join(d, "input", "paper_SI.pdf"))
    make_heading_pdf(os.path.join(d, "input", "main.pdf"))
    json.dump({"case_id": "two", "files": ["paper_SI.pdf", "main.pdf"], "output_contract": ["paper_card"]},
              open(os.path.join(d, "input", "case.json"), "w"))
    it = run("init", "--case", os.path.join(d, "input", "case.json"), "--out", os.path.join(d, "output"), "--work", os.path.join(d, "work"))
    expect("filename_supplement_not_primary", "main.pdf", os.path.basename(it.get("primary") or ""))
    # ---------------- E: unnumbered + ALL-CAPS headings recovered in a PDF (same main.pdf)
    ol = [" ".join(x.split()[1:]).rsplit(" pp", 1)[0].strip() for x in it["outline"]]
    expect("pdf_recovered_unnumbered_headings", ["L1 1 Introduction", "L1 2 Experiments", "L2 EXPERIMENTAL SETUP", "L1 3 Discussion", "L2 Limitations"], ol)
    cues = json.load(open(os.path.join(d, "work", "cues.json"), encoding="utf-8"))
    expect("pdf_limitations_section_of_interest", True, any("Limitations" in x for x in cues["sections_of_interest"]["limitations"]))

    # ---------------- F: mixed page (large raster image + a caption line)
    d = os.path.join(root, "mixed")
    os.makedirs(os.path.join(d, "input"), exist_ok=True)
    M.sample_a(os.path.join(d, "plain.pdf"))
    make_mixed_pdf(os.path.join(d, "plain.pdf"), os.path.join(d, "input", "paper.pdf"))
    os.remove(os.path.join(d, "plain.pdf"))
    json.dump({"case_id": "mixed", "output_contract": ["paper_card"]}, open(os.path.join(d, "input", "case.json"), "w"))
    W, O = os.path.join(d, "work"), os.path.join(d, "output")
    it = run("init", "--case", os.path.join(d, "input", "case.json"), "--out", O, "--work", W)
    expect("mixed_page_flagged", True, any(x.startswith("p3:") for x in it.get("visual_pages", [])), str(it.get("visual_pages")))
    expect("mixed_page_in_digest", True, "[p3 VISUAL]" in open(os.path.join(W, "digest.md"), encoding="utf-8").read())
    json.dump({"card": {"research_question": {"text": "x", "a": ["p1-b1: Layout-Aware Parsing"]}}}, open(os.path.join(W, "p.json"), "w"))
    run("merge", os.path.join(W, "p.json"), "--work", W)
    run("build", "--work", W)
    r3 = json.load(open(os.path.join(O, "result.json"), encoding="utf-8"))
    expect("mixed_page_unread_uncertainty", True, any(isinstance(u, dict) and u.get("auto") and u.get("page") == 3 for u in r3["uncertainty"]))
    run("add", "card.main_findings", "--text", "Plot shows results", "--a", "p3@56,80,556,600: table image with Baseline 0.61", "--work", W)
    run("build", "--work", W)
    r3 = json.load(open(os.path.join(O, "result.json"), encoding="utf-8"))
    expect("mixed_page_read_after_image_anchor", [True, "needs_review"],
           [r3["verification"]["visual_coverage"]["read"] == 1, r3["notes"]["paper_card"]["main_findings"][0]["check"]["status"]])
