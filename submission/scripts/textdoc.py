#!/usr/bin/env python3
"""textdoc: parse a paper given as Markdown (.md/.markdown), plain text (.txt) or Word (.docx) into the same
doc.json layout that parse_pdf.py writes, so outline repair, anchors and every check in notes.py work unchanged.

    python textdoc.py paper.md OUT_DIR

Locators kept for every block (no PDF geometry exists for these formats):
  * block id  p{page}-b{n}: page = form-feed page for .txt, rendered/explicit page breaks for .docx
    (approximate, as Word last laid the file out), 1 for Markdown;
  * line_start / line_end: 1-based lines in the source file (.md/.txt)  -> anchor 'L120: words';
  * source_para: paragraph index in word/document.xml (.docx)         -> shown in evidence.
Headings: Markdown '#', Word heading/title styles, and text patterns (1 / 1.1 / 一、 / （一） / 第N章 / II. /
Appendix A / Abstract, Methods, Limitations, 摘要, 局限性 ... / ALL-CAPS lines). Numbered candidates must keep
the numbering increasing, so numbered list items inside a section are not taken for headings.
Tables: Markdown pipe tables, Word tables (caption = adjacent 'Table N' / '表N' paragraph). Equations: '$$...$$'
blocks, Word OMML, or lines ending in '(N)' with math symbols. No network, no third-party packages.
"""
import hashlib
import json
import os
import re
import sys
import time
import zipfile
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import notes_lib as L  # noqa: E402

VERSION = "textdoc 1.0.0"
FORMATS = {".md": "markdown", ".markdown": "markdown", ".txt": "text", ".text": "text", ".docx": "docx"}
RE_CAPTION = re.compile(r"^\s*(?:\*\*|__)?\s*(Fig\.|Figure|FIGURE|Table|TABLE|Tab\.|图|表)\s*([A-Z]?\d+[a-z]?)\s*[.:：|．]?", re.I)
RE_EQ_NUM = re.compile(r"\(\s*((?:\d+\.)?\d+[a-z]?)\s*\)\s*$")
MATH = set("=+−×·∑∏∫∂∇√∞≈≠≤≥±∈⊂∀∃→αβγδεζηθλμνξπρσφχψωΓΔΘΛΣΦΨΩ^_\\")
SENT_END = re.compile(r"[.。!?！？;；]\s*$")


def read_text(path):
    raw = open(path, "rb").read()
    for enc in ("utf-8-sig", "gb18030"):
        try:
            return raw.decode(enc), enc, []
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1"), "latin-1", [{"code": "encoding_guess", "detail": "not UTF-8/GB18030; decoded as latin-1"}]


# ------------------------------------------------------------------ raw units
# unit = {"kind": heading|para|table|equation|image, "text", "line_start", "line_end", "page", "level"?, "rows"?,
#         "style"?, "bold"?, "source_para"?}
def units_markdown(text):
    lines = text.split("\n")
    units, buf, start, in_fence, in_math, i = [], [], None, False, False, 0
    fm_title = None
    if lines and lines[0].strip() == "---":  # YAML front matter
        for j in range(1, min(len(lines), 60)):
            if lines[j].strip() in ("---", "..."):
                for ln in lines[1:j]:
                    m = re.match(r"^\s*title\s*:\s*['\"]?(.+?)['\"]?\s*$", ln)
                    if m:
                        fm_title = m.group(1)
                i = j + 1
                break

    def flush(end):
        nonlocal buf, start
        if buf:
            units.append({"kind": "para", "text": " ".join(x.strip() for x in buf).strip(), "line_start": start, "line_end": end})
        buf, start = [], None

    if fm_title:
        units.append({"kind": "title", "text": fm_title, "line_start": 2, "line_end": 2})
    while i < len(lines):
        ln, no = lines[i], i + 1
        st = ln.strip()
        if st.startswith("```") or st.startswith("~~~"):
            flush(no - 1)
            j = i + 1
            while j < len(lines) and not lines[j].strip().startswith(st[:3]):
                j += 1
            body = "\n".join(lines[i + 1:j])
            if body.strip():
                units.append({"kind": "para", "text": body, "line_start": no + 1, "line_end": j, "code": True})
            i = j + 1
            continue
        if st.startswith("$$"):
            flush(no - 1)
            j = i
            if not (len(st) > 4 and st.endswith("$$")):
                j = i + 1
                while j < len(lines) and "$$" not in lines[j]:
                    j += 1
            expr = " ".join(x.strip() for x in lines[i:j + 1]).strip("$ ").strip()
            units.append({"kind": "equation", "text": expr, "line_start": no, "line_end": j + 1})
            i = j + 1
            continue
        m = re.match(r"^(#{1,6})\s+(.*?)\s*#*\s*$", ln)
        if m:
            flush(no - 1)
            units.append({"kind": "heading", "text": m.group(2), "level": len(m.group(1)), "line_start": no, "line_end": no,
                          "md": True})
            i += 1
            continue
        if i + 1 < len(lines) and st and re.match(r"^(=+|-+)\s*$", lines[i + 1]) and not buf and len(st) < 120:
            flush(no - 1)  # setext heading
            units.append({"kind": "heading", "text": st, "level": 1 if lines[i + 1].strip()[0] == "=" else 2,
                          "line_start": no, "line_end": no + 1, "md": True})
            i += 2
            continue
        if st.startswith("|") and st.count("|") >= 2:
            flush(no - 1)
            j, rows = i, []
            while j < len(lines) and lines[j].strip().startswith("|"):
                cells = [c.strip() for c in lines[j].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
                    rows.append([re.sub(r"\*\*|__", "", c) for c in cells])
                j += 1
            units.append({"kind": "table", "text": "\n".join(" | ".join(r) for r in rows), "rows": rows,
                          "line_start": no, "line_end": j})
            i = j
            continue
        im = re.match(r"^\s*!\[([^\]]*)\]\(([^)]+)\)\s*$", ln)
        if im:
            flush(no - 1)
            units.append({"kind": "image", "text": im.group(1), "src": im.group(2), "line_start": no, "line_end": no})
            i += 1
            continue
        if not st:
            flush(no - 1)
        else:
            if start is None:
                start = no
            # list items / block quotes start their own paragraph
            if buf and re.match(r"^\s*([-*+]|\d+[.)])\s+", ln):
                flush(no - 1)
                start = no
            buf.append(re.sub(r"^\s*>\s?", "", ln))
        i += 1
    flush(len(lines))
    for u in units:
        if u["kind"] in ("para", "heading", "title") and not u.get("code"):
            u["text"] = strip_md(u["text"])
    return units


def strip_md(t):
    t = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", t)
    t = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", t)
    t = re.sub(r"(\*\*|__)(.+?)\1", r"\2", t)
    t = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"\1", t)
    t = re.sub(r"`([^`]+)`", r"\1", t)
    t = re.sub(r"<[^>]{1,80}>", "", t)
    return re.sub(r"^\s*([-*+])\s+", "", t).strip()


def units_text(text):
    pages = text.split("\f")
    units, line_no = [], 0
    for pi, ptxt in enumerate(pages):
        lines = ptxt.split("\n")
        buf, start = [], None

        def flush(end):
            nonlocal buf, start
            if buf:
                units.append({"kind": "para", "text": " ".join(x.strip() for x in buf).strip(), "line_start": start,
                              "line_end": end, "page": pi + 1, "_lines": list(buf)})
            buf, start = [], None
        for k, ln in enumerate(lines):
            no = line_no + k + 1
            if not ln.strip():
                flush(no - 1)
                continue
            # a heading-like first line glued to its paragraph ("1 Introduction\nText ...") -> own unit
            if start is None and len(lines) > k + 1 and lines[k + 1].strip() and L.classify_heading(ln) \
                    and len(ln.strip()) < 90 and not SENT_END.search(ln.strip()):
                units.append({"kind": "para", "text": ln.strip(), "line_start": no, "line_end": no, "page": pi + 1,
                              "_lines": [ln], "_glued_heading": True})
                continue
            if start is None:
                start = no
            buf.append(ln)
        flush(line_no + len(lines))
        line_no += len(lines) - 1  # the form feed sits on the boundary line
    # de-hyphenate line breaks inside paragraphs
    for u in units:
        if len(u.get("_lines", [])) > 1:
            u["text"] = re.sub(r"(?<=[a-z])- (?=[a-z])", "", u["text"])
        if re.search(r"[一-鿿] [一-鿿]", u["text"]):
            u["text"] = re.sub(r"(?<=[一-鿿，。、；：]) (?=[一-鿿，。、；：])", "", u["text"])
    return units


W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
M = "{http://schemas.openxmlformats.org/officeDocument/2006/math}"


def units_docx(path):
    z = zipfile.ZipFile(path)
    names = set(z.namelist())
    if "word/document.xml" not in names:
        raise ValueError("not a Word document (word/document.xml missing)")
    styles = {}
    if "word/styles.xml" in names:
        for st in ET.fromstring(z.read("word/styles.xml")).iter(W + "style"):
            nm = st.find(W + "name")
            styles[st.get(W + "styleId")] = (nm.get(W + "val") if nm is not None else st.get(W + "styleId")) or ""
    root = ET.fromstring(z.read("word/document.xml"))
    body = root.find(W + "body")
    units, page, pidx = [], 1, 0
    # Word writes lastRenderedPageBreak where it last laid out a page; explicit page breaks are usually
    # followed by one, so use the rendered marks when present and explicit breaks only otherwise.
    use_rendered = root.find(".//" + W + "lastRenderedPageBreak") is not None

    def run_text(el):
        """(text, bold, page of first text, chars outside math)"""
        nonlocal page
        parts, bold_chars, all_chars, first_page, plain = [], 0, 0, None, 0
        for node in el.iter():
            tag = node.tag
            if tag == W + "lastRenderedPageBreak" and use_rendered:
                page += 1
            elif tag == W + "br" and node.get(W + "type") == "page":
                if not use_rendered:
                    page += 1
            elif tag in (W + "t", M + "t") and node.text:
                if first_page is None and node.text.strip():
                    first_page = page
                parts.append(node.text)
                if tag == W + "t":
                    plain += len(node.text.strip())
            elif tag == W + "tab":
                parts.append(" ")
            elif tag == W + "br":
                parts.append(" ")
        for r in el.iter(W + "r"):
            t = "".join(x.text or "" for x in r.iter(W + "t"))
            all_chars += len(t)
            rpr = r.find(W + "rPr")
            if rpr is not None and rpr.find(W + "b") is not None and rpr.find(W + "b").get(W + "val") not in ("0", "false"):
                bold_chars += len(t)
        return "".join(parts), (all_chars > 0 and bold_chars >= 0.6 * all_chars), first_page or page, plain

    def children(node):  # body order, content controls (w:sdt) expanded
        for el in list(node):
            if el.tag == W + "sdt":
                c = el.find(W + "sdtContent")
                if c is not None:
                    yield from children(c)
            else:
                yield el

    for el in children(body) if body is not None else []:
        if el.tag == W + "p":
            pidx += 1
            ppr = el.find(W + "pPr")
            sid = ppr.find(W + "pStyle").get(W + "val") if ppr is not None and ppr.find(W + "pStyle") is not None else ""
            sname = (styles.get(sid) or sid or "").lower()
            has_math = el.find(".//" + M + "oMath") is not None
            txt, bold, start_page, plain = run_text(el)
            txt = re.sub(r"\s+", " ", txt).strip()
            if not txt:
                continue
            u = {"text": txt, "page": start_page, "source_para": pidx, "style": sname, "bold": bold}
            hm = re.search(r"(?:heading|标题)\s*(\d)", sname)
            if sname in ("title", "标题") or sname.startswith("title"):
                u["kind"] = "title"
            elif hm:
                u.update(kind="heading", level=int(hm.group(1)), styled=True)
            elif sname in ("subtitle", "副标题"):
                u["kind"] = "para"
            elif has_math and plain < 20 and len(txt) < 300 and ("caption" not in sname):  # display equation
                u["kind"] = "equation"
            else:
                u["kind"] = "para"
            if "caption" in sname or "题注" in sname:
                u["caption_style"] = True
            units.append(u)
        elif el.tag == W + "tbl":
            pidx += 1
            rows = []
            for tr in el.iter(W + "tr"):
                cells = []
                for tc in tr.findall(W + "tc"):
                    t = run_text(tc)[0]
                    cells.append(re.sub(r"\s+", " ", t).strip())
                rows.append(cells)
            if rows:
                units.append({"kind": "table", "rows": rows, "text": "\n".join(" | ".join(r) for r in rows),
                              "page": page, "source_para": pidx})
    return units, {"page_model": "docx page breaks (explicit + last rendered by Word); approximate"}


# ------------------------------------------------------------------ units -> doc.json
def build_doc(units, path, fmt, extra_meta=None, warnings=None):
    warnings = list(warnings or [])
    blocks, sections, tables, figures, equations, paragraphs = [], [], [], [], [], []
    per_page = {}
    numbered_seen = []  # numbering monotonicity (tuples) for pattern headings
    stack = []
    in_refs = False
    title_done = any(u["kind"] == "title" for u in units)
    md_levels = sorted({u["level"] for u in units if u["kind"] == "heading" and u.get("md")})
    md_h1 = [u for u in units if u["kind"] == "heading" and u.get("md") and u["level"] == 1]
    md_offset = 0
    # a single leading '# Title' (first unit of the file) is the paper title, not a section
    if md_h1 and len(md_h1) == 1 and not title_done and units and units[0] is md_h1[0] \
            and not L.NAMED_SECTION.match(md_h1[0]["text"]) and not L.classify_heading(md_h1[0]["text"]):
        md_h1[0]["kind"] = "title"
        title_done = True
        md_offset = 1 if len(md_levels) > 1 else 0
    cn_style = False  # Chinese hierarchy 一、 > （一） > 1. > （1）: arabic numbers restart under each 一、/（一）
    first_heading_seen = False
    authors_left = 3

    def new_block(u, role):
        pg = u.get("page") or 1
        per_page[pg] = per_page.get(pg, 0) + 1
        b = {"id": f"p{pg}-b{per_page[pg]}", "page": pg, "bbox": None, "role": role, "text": u["text"],
             "section_id": stack[-1]["id"] if stack else None, "size": None, "bold": bool(u.get("bold"))}
        for k in ("line_start", "line_end", "source_para"):
            if u.get(k) is not None:
                b[k] = u[k]
        blocks.append(b)
        return b

    def open_section(u, hc, b):
        lvl = max(1, hc["level"])
        while stack and stack[-1]["level"] >= lvl:
            stack.pop()
        sec = {"id": f"s{len(sections) + 1}", "level": lvl, "number": hc.get("number"), "title": hc["title"],
               "page": b["page"], "block_id": b["id"], "parent": stack[-1]["id"] if stack else None,
               "rule": hc.get("rule", f"{fmt}: {hc['kind']} heading")}
        if hc.get("appendix"):
            sec["appendix"] = True
        sections.append(sec)
        stack.append(sec)
        b["section_id"] = sec["id"]
        return sec

    for idx, u in enumerate(units):
        kind, txt = u["kind"], (u.get("text") or "").strip()
        if kind == "title":
            if not txt:
                continue
            new_block(u, "title")
            continue
        if kind == "table":
            b = new_block(u, "table")
            cap_b = None
            for j in (idx - 1, idx + 1):  # caption = adjacent 'Table N' paragraph
                if 0 <= j < len(units) and units[j]["kind"] == "para" and re.match(r"^\s*(?:\*\*)?\s*(table|tab\.|表)\s*[A-Z]?\d", units[j]["text"], re.I):
                    cap_b = units[j]
                    break
            tables.append({"id": f"T{len(tables) + 1}", "page": b["page"], "bbox": None, "rows": u["rows"],
                           "cells": [{"text": c} for r in u["rows"] for c in r], "caption": cap_b["text"] if cap_b else None,
                           "_cap_unit": id(cap_b) if cap_b else None, "block_id": b["id"],
                           "line_start": u.get("line_start"), "line_end": u.get("line_end")})
            continue
        if kind == "image":
            b = new_block(dict(u, text=txt or "(image)"), "figure_text")
            figures.append({"id": f"F{len(figures) + 1}", "page": b["page"], "bbox": None, "kind": "image",
                            "caption": txt if RE_CAPTION.match(txt or "") else None, "src": u.get("src"), "block_id": b["id"],
                            "_alt": txt})
            continue
        if kind == "equation":
            b = new_block(u, "equation")
            m = RE_EQ_NUM.search(txt) or re.search(r"\\tag\{(\d+[a-z]?)\}", txt)
            equations.append({"number": m.group(1) if m else None, "block_id": b["id"], "page": b["page"], "bbox": None,
                              "expr_unicode": txt, "transcription_status": "auto"})
            continue
        # heading decision
        hc = None
        if kind == "heading":
            hc = L.classify_heading(txt) or {"kind": "styled", "number": None, "title": txt, "level": 1}
            hc = dict(hc)
            lvl = (u["level"] - md_offset) if u.get("md") else u["level"]
            hc["level"] = max(1, lvl)
            if hc.get("kind") == "numeric" and hc.get("num_key"):
                numbered_seen.append(hc["num_key"])
            if hc.get("kind") not in ("numeric", "appendix", "cn1", "cn2", "cn_chapter", "cn_section", "roman"):
                hc["number"] = None
                hc["title"] = txt
            hc["rule"] = f"{fmt}: {'markdown #' if u.get('md') else 'Word heading style'}"
        elif kind == "para" and not u.get("code") and len(txt) <= 120 and "\n" not in txt:
            cand = L.classify_heading(txt)
            nxt_list = [x for x in units[idx + 1: idx + 3] if x["kind"] == "para"]
            if cand and fmt == "docx" and cand["kind"] in ("caps",) and not u.get("bold"):
                cand = None
            if cand and in_refs and cand["kind"] not in ("named", "appendix"):
                cand = None  # inside References only 'Appendix ...' / named end matter opens a section
            if cand and cand["kind"] == "numeric":
                # numbering must increase (else it is a numbered list item / affiliation mark); a run of
                # consecutive numbered lines is a list; before the first heading only '1 Introduction'-like titles
                key = cand["num_key"]
                ok = not numbered_seen or key > numbered_seen[-1]
                prv = units[idx - 1] if idx and units[idx - 1]["kind"] == "para" else None
                looks_list = len(key) == 1 and bool(
                    (nxt_list and re.match(r"^\s*" + str(key[0] + 1) + r"[.)、]?\s*\S", nxt_list[0]["text"]))
                    or (prv and key[0] > 1 and re.match(r"^\s*" + str(key[0] - 1) + r"[.)、]?\s*\S", prv["text"])
                        and not (blocks and blocks[-1]["role"] == "heading")))
                affil = re.search(r",|@|universit|institut|department|college|laborator|大学|学院|研究所|研究院|实验室", txt, re.I)
                pre = not first_heading_seen and not L.NAMED_SECTION.match(cand["title"]) and not re.match(
                    r"(introduction|background|overview|motivation|preliminar|引言|绪论|前言|背景|概述|研究背景|问题的提出)", cand["title"], re.I)
                if not ok or looks_list or affil or pre or (len(txt.split()) > 10 and not u.get("bold")):
                    cand = None
                else:
                    numbered_seen.append(key)
                    if cn_style and stack:  # '1.' / '1.1' under '一、'/'（一）' is the next level down
                        cand = dict(cand, level=stack[-1]["level"] + 1)
            if cand and cand["kind"] == "named" and len(txt.split()) > 6:
                cand = None
            hc = cand
            if hc:
                hc = dict(hc, rule=f"{fmt}: {hc['kind']} heading pattern")
        if hc and hc["kind"] == "caps" and not title_done and not blocks:
            hc = None  # an ALL-CAPS first line is the paper title
        if hc:
            if hc["kind"] in ("cn1", "cn2", "cn_chapter", "cn_section"):
                cn_style = True
                numbered_seen.clear()
            b = new_block(u, "heading")
            first_heading_seen = True
            sec = open_section(u, hc, b)
            in_refs = bool(L.SKIP_SECTION.match(sec["title"] or ""))
            continue
        # body text
        if not title_done and not blocks and len(txt) < 200 and not SENT_END.search(txt):
            new_block(u, "title")
            title_done = True
            continue
        if not first_heading_seen and title_done and authors_left > 0 and len(txt) < 300 and not re.match(r"^\s*(abstract|摘\s*要)", txt, re.I) \
                and not SENT_END.search(txt) and blocks and blocks[-1]["role"] in ("title", "author_affiliation"):
            new_block(u, "author_affiliation")
            authors_left -= 1
            continue
        am = re.match(r"^\s*(abstract|摘\s*要)\s*[:：.—\-]\s*(.+)$", txt, re.I | re.S)
        if am and not stack:
            b = new_block(u, "abstract")
            open_section(u, {"kind": "named", "number": None, "title": am.group(1).strip().title() if am.group(1).isascii() else "摘要",
                             "level": 1, "rule": f"{fmt}: paragraph starting 'Abstract:'"}, b)
            continue
        if in_refs:
            new_block(u, "reference")
            continue
        role = "body"
        if RE_CAPTION.match(txt) and (len(txt) < 400 or u.get("caption_style")):
            role = "caption"
        elif RE_EQ_NUM.search(txt) and len(txt) < 200 and sum(c in MATH for c in txt) >= 2:
            role = "equation"
        b = new_block(u, role)
        if role == "equation":
            equations.append({"number": RE_EQ_NUM.search(txt).group(1), "block_id": b["id"], "page": b["page"], "bbox": None,
                              "expr_unicode": RE_EQ_NUM.sub("", txt).strip(), "transcription_status": "auto"})
        if role == "caption":
            m = RE_CAPTION.match(txt)
            label = m.group(1).lower()
            if label.startswith(("tab", "表")):
                for t in tables:
                    if t.get("_cap_unit") == id(u):
                        t["caption_block"] = b["id"]
            else:
                img = next((f for f in reversed(figures) if not f.get("caption") and f["page"] == b["page"]
                            and blocks.index(next(x for x in blocks if x["id"] == f["block_id"])) >= len(blocks) - 3), None)
                if img:
                    img["caption"], img["caption_block"] = txt, b["id"]
                else:
                    figures.append({"id": f"F{len(figures) + 1}", "page": b["page"], "bbox": None, "kind": "caption_only",
                                    "caption": txt, "caption_block": b["id"]})
    # tables whose caption paragraph came before the table were captioned before the block existed
    for t in tables:
        if t.get("caption") and not t.get("caption_block"):
            cb = next((b for b in blocks if b["text"] == t["caption"] and b["role"] in ("caption", "body")), None)
            if cb:
                cb["role"] = "caption"
                t["caption_block"] = cb["id"]
        t.pop("_cap_unit", None)
    for f in figures:
        f.pop("_alt", None)
    for i, b in enumerate(blocks):
        if b["role"] in ("body", "abstract", "list", "caption", "footnote", "equation"):
            paragraphs.append({"id": f"para{len(paragraphs) + 1}", "text": b["text"], "page": b["page"],
                               "section_id": b["section_id"], "sources": [{"block_id": b["id"], "page": b["page"]}]})
    pages = sorted({b["page"] for b in blocks} or {1})
    meta = {"source_file": os.path.abspath(path), "format": fmt, "parser": VERSION, "page_count": max(pages),
            "page_model": {"markdown": "single logical page; cite lines (L..)", "text": "form-feed pages (\\f); cite lines (L..)"}.get(fmt),
            **(extra_meta or {})}
    if os.path.exists(path):
        meta["sha256"] = hashlib.sha256(open(path, "rb").read()).hexdigest()
    if not sections:
        warnings.append({"code": "no_headings", "detail": "no heading detected; page/line based pseudo sections will be used"})
    status = "success" if blocks else "failed"
    return {
        "status": status, "error": None if blocks else "no_text", "meta": meta,
        "pages_parsed": pages, "pages_not_parsed": [], "warnings": warnings,
        "pages": [{"page": p, "width": None, "height": None, "source": fmt} for p in pages],
        "ocr_pages": [], "unresolved_pages": [], "sections": sections, "blocks": blocks, "headers_footers": [],
        "paragraphs": paragraphs, "tables": tables, "figures": figures, "equations": equations,
        "footnotes": [], "references": [b["text"] for b in blocks if b["role"] == "reference"],
        "stats": {"n_blocks": len(blocks), "n_sections": len(sections), "n_tables": len(tables), "n_figures": len(figures),
                  "n_equations": len(equations)},
    }


def parse(path, out_dir):
    """Parse a .md/.txt/.docx file into out_dir/doc.json (same layout as parse_pdf.parse)."""
    t0 = time.time()
    os.makedirs(out_dir, exist_ok=True)
    ext = os.path.splitext(path)[1].lower()
    fmt = FORMATS.get(ext)
    try:
        if fmt is None:
            raise ValueError(f"unsupported input format '{ext}' (supported: .pdf {' '.join(FORMATS)})")
        if fmt == "docx":
            try:
                units, extra = units_docx(path)
            except zipfile.BadZipFile:
                raise ValueError("docx is not a valid zip package (corrupt, encrypted/IRM-protected, or an old binary .doc)")
            warnings = []
        else:
            text, enc, warnings = read_text(path)
            units = units_markdown(text) if fmt == "markdown" else units_text(text)
            extra = {"encoding": enc}
        r = build_doc(units, path, fmt, extra, warnings)
    except Exception as e:  # noqa: BLE001
        r = {"status": "failed", "error": f"{type(e).__name__}: {e}", "meta": {"source_file": os.path.abspath(path), "format": fmt}}
    r.setdefault("stats", {})["seconds"] = round(time.time() - t0, 3)
    with open(os.path.join(out_dir, "doc.json"), "w", encoding="utf-8") as fh:
        json.dump(r, fh, ensure_ascii=False, indent=1)
    return r


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(2)
    res = parse(sys.argv[1], sys.argv[2])
    print(json.dumps({"status": res["status"], "error": res.get("error"),
                      "sections": [f"{s['id']} L{s['level']} {s.get('number') or ''} {s['title']}" for s in res.get("sections", [])],
                      "stats": res.get("stats")}, ensure_ascii=False, indent=1))
