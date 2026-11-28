#!/usr/bin/env python3
"""paper-notes: section-aligned, field-structured, anchor-verified reading notes for a paper
(PDF, Markdown, plain text or Word .docx; supplementary files anchorable as S1, S2, ...).

    python notes.py init  [--case /input/case.json] [--out /app/output] [--work /app/work] [--input X.docx]
                          [--primary FILE] [--pages 1-12] [--password PW] [--full-digest] [--force]
    python notes.py merge part1.json [part2.json ...] | --json '{"card": {...}}'   (write the draft in parts)
    python notes.py add   card.limitations --text "..." --a "p9-b3: words" [--append]   (one item)
    python notes.py build [part1.json ...] [--draft /app/work/draft.json] [--out /app/output] [--dry-run]
                          (parts given -> merged first; merge + check + write in one call)
    python notes.py find  "query words" [--section 3.2] [--source S1] [--top 5]   (search, prints anchors ready to paste)

init  : parse the PDF (parse_pdf.py), build the paper's own outline, write
        WORK/digest.md (reading text with anchors, by section), WORK/cues.json (candidate sentences per card
        field), WORK/draft.json (template to fill) and OUT/result.json (valid partial result, status partial).
build : resolve every anchor in the draft against the PDF text layer, check quotes, sections and numbers,
        merge duplicate knowledge points, fill contract fields, and write OUT/result.json, OUT/notes.md,
        OUT/paper_card.json, OUT/paper_card.csv, OUT/knowledge_points.jsonl, OUT/verification.json.
Run build again after fixing the draft; it is idempotent.
"""
import argparse
import csv
import glob
import hashlib
import json
import os
import re
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import notes_lib as L  # noqa: E402

STATE = ".paper_notes_state.json"


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def dump(obj, path):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1)


def load(path):
    # utf-8-sig: case.json / draft.json written by Windows PowerShell start with a BOM, which json rejects
    with open(path, encoding="utf-8-sig") as fh:
        return json.load(fh)


def load_state(work):
    p = os.path.join(work, STATE)
    if not os.path.exists(p) and os.path.exists("/input/case.json"):
        # init was skipped: run it with the defaults instead of failing (one request saved, no dead end)
        cmd_init(argparse.Namespace(case="/input/case.json", out="/app/output", work=work, pdf=[], input=[], primary=None,
                                    pages=None, password=None, full_digest=False, force=False))
    if not os.path.exists(p):
        print(json.dumps({"error": f"{p} not found", "hint": "run `notes.py init` first with the same --work directory"}))
        sys.exit(2)
    st = load(p)
    if not st.get("parsed_dir"):
        print(json.dumps({"error": "no parsed PDF (init failed)", "sources": st.get("sources"),
                          "hint": "result.json already records the failure; nothing to build"}, ensure_ascii=False))
        sys.exit(3)
    return st


# ------------------------------------------------------------------ case discovery
CONTRACT_KEYS = ("output_contract", "outputs_contract", "output_schema", "required_outputs", "output_fields", "outputs", "schema", "deliverables")


def find_contract(obj):
    if isinstance(obj, dict):
        for k in CONTRACT_KEYS:
            if k in obj:
                return obj[k]
        for v in obj.values():
            r = find_contract(v)
            if r is not None:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = find_contract(v)
            if r is not None:
                return r
    return None


def _collect_contracts(obj, acc):
    if isinstance(obj, dict):
        hits = [obj[k] for k in CONTRACT_KEYS if k in obj and obj[k] is not None]
        if hits:
            acc.extend(hits)
            return
        for v in obj.values():
            _collect_contracts(v, acc)
    elif isinstance(obj, list):
        for v in obj:
            _collect_contracts(v, acc)


def parse_contract(c):
    if c is None:
        return [], {}
    if isinstance(c, dict):
        if "schema" in c and "properties" not in c and "required" not in c:
            return parse_contract(c["schema"])
        if "output_schema" in c and "properties" not in c and "required" not in c:
            return parse_contract(c["output_schema"])
        if "properties" in c or "required" in c:
            props = c.get("properties") if isinstance(c.get("properties"), dict) else {}
            has_req = "required" in c and isinstance(c.get("required"), list)
            req = c.get("required") if has_req else []
            spec = {}
            for k, v in props.items():
                sp = dict(v) if isinstance(v, dict) else {}
                if has_req:
                    sp["_required"] = (k in req) or bool(sp.get("required"))
                else:
                    sp["_required"] = sp.get("required", True)
                spec[k] = sp
            for nm in req:
                if isinstance(nm, str) and nm not in spec:
                    spec[nm] = {"_required": True}
            return list(spec.keys()), spec
        for k in ("fields", "required_fields"):
            if k in c:
                return parse_contract(c[k])
        spec = {}
        for k, v in c.items():
            if isinstance(v, dict):
                sp = dict(v)
            elif isinstance(v, str) and v.lower() in ("string", "array", "object", "integer", "number", "boolean"):
                sp = {"type": v.lower()}
            else:
                sp = {}
            sp.setdefault("_required", sp.get("required", True))
            spec[k] = sp
        return list(spec.keys()), spec
    if isinstance(c, list):
        out, spec = [], {}
        for it in c:
            if isinstance(it, str):
                if it not in spec:
                    out.append(it)
                    spec[it] = {"_required": True}
            elif isinstance(it, dict):
                n = it.get("name") or it.get("field") or it.get("key") or it.get("id")
                if n:
                    if n not in spec:
                        out.append(n)
                    sp = dict(it)
                    sp.setdefault("_required", sp.get("required", True))
                    spec[n] = sp
        return out, spec
    return ([c], {c: {"_required": True}}) if isinstance(c, str) else ([], {})


def parse_case_contracts(case):
    blocks = []
    _collect_contracts(case, blocks)
    fields, spec = [], {}
    for blk in blocks:
        fs, sp = parse_contract(blk)
        for f in fs:
            if f not in spec:
                fields.append(f)
                spec[f] = sp.get(f, {})
            else:
                merged = dict(spec[f])
                merged.update(sp.get(f, {}))
                if spec[f].get("_required") or (sp.get(f) or {}).get("_required"):
                    merged["_required"] = True
                spec[f] = merged
    return fields, spec


def contract_fields(c):
    return parse_contract(c)[0]


INPUT_EXT = (".pdf", ".md", ".markdown", ".txt", ".text", ".docx")
NOT_MATERIAL = re.compile(r"(^|[\\/])(task\.md|case\.json|readme\.md|instructions?\.(md|txt))$", re.I)
ROLE_KEYS = ("role", "type", "kind", "label", "category", "usage", "purpose", "tag")
DESC_KEYS = ("name", "title", "description", "desc", "caption")
SUPP_DESC_RX = re.compile(r"(?i:\bsupplement(ary|al)?\b|\bappendix\b|\bsupporting information\b)|\bSI\b|附件|补充材料|附录")
PRIMARY_RX = re.compile(r"^(primary|main|main[ _-]?(paper|text|pdf|document|article|file)|paper|target|article|manuscript|"
                        r"full[ _-]?text|source[ _-]?paper|input[ _-]?paper|document|pdf|paper[ _-]?pdf|主文|正文|原文|论文|主论文)$", re.I)
SUPP_RX = re.compile(r"supp|supplement|appendi|\bsi\b|(^|[_\-. ])si([_\-. ]|$)|extended[ _-]?data|support|annex|附件|补充|附录|"
                     r"auxiliary|additional|extra|reference[ _-]?(material|paper)|related", re.I)


def input_candidates(obj, acc, key=None, role=None, order=None):
    """Every input-file string in case.json with the context it was found in (its key, the role of its dict)."""
    order = order if order is not None else [0]
    if isinstance(obj, dict):
        r = next((str(obj[k]) for k in ROLE_KEYS if isinstance(obj.get(k), str) and not obj[k].lower().endswith(INPUT_EXT)), None)
        flag = next((k for k in ("primary", "is_primary", "main", "is_main") if obj.get(k) is True), None)
        desc = " ".join(str(obj[k]) for k in DESC_KEYS if isinstance(obj.get(k), str) and not obj[k].lower().endswith(INPUT_EXT))
        n0 = len(acc)
        for k, v in obj.items():
            input_candidates(v, acc, k, (r or role) if not flag else "primary", order)
        for c in acc[n0:]:
            c.setdefault("desc", desc[:200] if desc else None)
    elif isinstance(obj, list):
        for v in obj:
            input_candidates(v, acc, key, role, order)
    elif isinstance(obj, str) and obj.lower().rstrip().endswith(INPUT_EXT) and not NOT_MATERIAL.search(obj.strip()):
        order[0] += 1
        acc.append({"path": obj.strip(), "key": key, "role_hint": role, "order": order[0]})
    return acc


def role_score(c, explicit=None):
    """Higher = more likely the primary paper. Explicit --primary > role=primary > key name > not a supplement by
    role/key/file name > format (pdf > docx > md > txt) > order in case.json."""
    name = os.path.basename(c.get("resolved") or c["path"])
    role, key = (c.get("role_hint") or "").strip(), str(c.get("key") or "")
    sc, why = 0.0, []
    if explicit:
        has_sep = os.sep in explicit or "/" in explicit
        if has_sep:
            if os.path.abspath(explicit) == os.path.abspath(c.get("resolved") or c["path"]):
                sc += 100
                why.append("--primary")
        elif os.path.basename(explicit) == name or explicit == c["path"]:
            sc += 100
            why.append("--primary")
    if role and PRIMARY_RX.match(role):
        sc += 50
        why.append(f"role={role}")
    elif role and SUPP_RX.search(role):
        sc -= 50
        why.append(f"role={role}")
    if key and PRIMARY_RX.match(key):
        sc += 30
        why.append(f"key={key}")
    elif key and SUPP_RX.search(key):
        sc -= 30
        why.append(f"key={key}")
    if c.get("desc") and SUPP_DESC_RX.search(c["desc"]):
        sc -= 10
        why.append("described as supplementary")
    if SUPP_RX.search(os.path.splitext(name)[0]):
        sc -= 20
        why.append("supplement-like file name")
    ext = os.path.splitext(name)[1].lower()
    sc += {".pdf": 3, ".docx": 2, ".md": 1.5, ".markdown": 1.5, ".txt": 1, ".text": 1}.get(ext, 0)
    sc -= 0.01 * c.get("order", 0)
    return sc, why


def pdf_strings(obj, acc):  # kept for callers of v1.0
    acc += [c["path"] for c in input_candidates(obj, []) if c["path"].lower().endswith(".pdf")]
    return acc


def resolve_path(p, bases):
    if os.path.isabs(p) and os.path.exists(p):
        return p
    for b in bases:
        q = os.path.join(b, p)
        if os.path.exists(q):
            return q
    for b in bases:
        hits = glob.glob(os.path.join(b, "**", os.path.basename(p)), recursive=True)
        if hits:
            return hits[0]
    return None


def sha256(p):
    with open(p, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


# ------------------------------------------------------------------ init
def visual_pages(D):
    """Pages whose content is (partly) only in an image: image-only/scanned pages and text pages dominated by a
    large raster image (a figure/table pasted as a picture). Their content is not in the text layer."""
    out = []
    for p in D.d.get("pages", []):
        vc = p.get("visual_check")
        if p.get("source") == "image_only" or p.get("page_image") and not vc:
            out.append({"page": p["page"], "reason": "image-only page (no usable text layer)",
                        "image": os.path.join(D.dir, p["page_image"]) if p.get("page_image") else None, "kind": "image_only"})
        elif vc:
            out.append({"page": p["page"], "reason": vc.get("reason"), "kind": "mixed",
                        "image": os.path.join(D.dir, vc["image"]) if vc.get("image") else None,
                        "image_bboxes": vc.get("image_bboxes")})
    return out


def digest_md(D, full, max_para=1400, prefix="", budget=45000, cues=None):
    d = D.d
    lines = []
    titles = [b for b in d["blocks"] if b.get("role") == "title"]
    auth = [b for b in d["blocks"] if b.get("role") == "author_affiliation"]
    fmt = (d.get("meta") or {}).get("format") or "pdf"
    has_lines = any(b.get("line_start") is not None for b in d["blocks"])

    def tag(b):
        return f"[{prefix}{b['id']}" + (f" L{b['line_start']}" + (f"-{b['line_end']}" if b.get("line_end") not in (None, b["line_start"]) else "")
                                         if b.get("line_start") is not None else "") + "]"
    lines.append(f"# DIGEST  {prefix}{d['meta'].get('source_file', '')}  (format: {fmt})")
    lines.append(f"Anchors: [{prefix}p3-b12] = page 3 block 12 (cite as '{prefix}p3-b12: verbatim words'). "
                 + (f"Text input: [p1-b12 L40-44] = source lines 40-44, '{prefix}L40: verbatim words' works too; "
                    f"page = {d['meta'].get('page_model') or 'page'}. " if has_lines or fmt != "pdf" else "")
                 + "Sections follow the paper's own order. Tables/figures/equations listed under the section that cites them.")
    if cues:
        soi = {k: v for k, v in (cues.get("sections_of_interest") or {}).items() if v}
        if soi:
            lines.append("WHERE TO LOOK (section titles matching card fields): "
                         + "; ".join(f"{k}: {', '.join(x.split(' ', 1)[0] for x in v)}" for k, v in soi.items()))
        if cues.get("table_rows"):
            lines.append("KEY TABLE ROWS (pre-checked anchors): " + "; ".join(f"'{x['anchor']}'" for x in cues["table_rows"][:6]))
    vis = visual_pages(D)
    if vis:
        lines.append("VISUAL PAGES (content only in an image; read the PNG, cite 'pN@x0,y0,x1,y1: what you read' or 'Fig. N: ...'): "
                     + "; ".join(f"p{v['page']} {v['reason']}" for v in vis))
    for b in titles:
        lines.append(f"{tag(b)} TITLE: {b['text']}")
    for b in auth[:4]:
        lines.append(f"{tag(b)} AUTHORS: {b['text'][:300]}")
    pre = [b for b in d["blocks"] if not b.get("section_id") and b.get("role") in ("body", "abstract")]
    for b in pre[:6]:
        lines.append(f"{tag(b)} {b['text']}")
    budget_left = None if full else budget
    tables_by_sec = {}
    for t in d.get("tables", []):
        cb = t.get("caption_block") or t.get("block_id")
        sid = D.blocks.get(cb, {}).get("section_id") if cb else None
        tables_by_sec.setdefault(sid, []).append(t)
    shown_vis = set()
    for s in D.sections:
        hdr = "#" * min(1 + (s.get("level") or 1), 4)
        tg = " [REFERENCES - skip]" if s.get("skip") else (" [APPENDIX]" if s.get("appendix") else "")
        span = [D.blocks[x].get("line_start") for x in s["block_ids"] if D.blocks[x].get("line_start") is not None]
        lspan = f"; lines {min(span)}-{max(span)}" if span else ""
        lines.append(f"\n{hdr} [{prefix}{s['id']}] {s.get('number') or ''} {s.get('title')}{tg}  "
                     f"(pp. {s['pages'][0]}-{s['pages'][1]}{lspan}; {s['first_block']}..{s['last_block']}; {s['n_chars']} chars)")
        if s.get("page_image"):
            pinfo = next((p for p in d.get("pages", []) if p["page"] == s["pages"][0]), {})
            dpi = pinfo.get("page_image_dpi") or 150
            lines.append(f"[p{s['pages'][0]} IMAGE-ONLY] {os.path.join(D.dir, s['page_image'])} ({dpi} dpi: PDF points = pixels*72/{dpi}); "
                         f"{len(pinfo.get('image_regions') or [])} ink regions in doc.json pages[].image_regions. "
                         f"Look at the image; cite what you read as 'p{s['pages'][0]}@x0,y0,x1,y1: text as read' (bbox in PDF points). "
                         f"Optional crop: \"$PY\" \"$SKILL_DIR/scripts/crop_region.py\" {D.dir} --page {s['pages'][0]} --region p{s['pages'][0]}-r5")
            for r in (pinfo.get("image_regions") or [])[:60]:
                lines.append(f"  region {r['id']} bbox {r['bbox']}")
        for v in vis:
            if v["kind"] == "mixed" and v["page"] not in shown_vis and s["pages"][0] <= v["page"] <= s["pages"][1]:
                shown_vis.add(v["page"])
                lines.append(f"[p{v['page']} VISUAL] {v['reason']}; page image: {v['image']}; image boxes (PDF points): "
                             f"{v.get('image_bboxes')}. The text layer does not contain what is drawn in the image: look at it "
                             f"before writing results from this page, cite 'p{v['page']}@x0,y0,x1,y1: what you read' (stays needs_review).")
        extras = s.get("tables", []) + s.get("figures", []) + s.get("equations", [])
        if extras:
            lines.append("  contains: " + "; ".join(extras))
        if s.get("skip"):
            continue
        for t in tables_by_sec.get(s["id"], [])[:6]:
            n = L.label_num(t.get("caption"), "table")
            rows = [r if isinstance(r, list) else [str(r)] for r in t.get("rows", [])]
            if not rows:
                continue
            lab = f"Table {n}" if n else f"(unnumbered table {t.get('id')})"
            lines.append(f"  [{prefix}{lab}] {(t.get('caption') or '')[:160]}")
            for r in rows[:9]:
                lines.append("    | " + " | ".join(str(c or "").strip()[:40] for c in r))
            if len(rows) > 9:
                lines.append(f"    ... {len(rows) - 9} more rows (table_query.py --table '{lab}')")
            if budget_left is not None:
                budget_left -= sum(len(" ".join(str(c or "") for c in r)) for r in rows[:9])
        n_after_budget = 0
        for bid in s["block_ids"]:
            b = D.blocks[bid]
            role = b.get("role")
            if role in ("heading", "table", "reference"):
                continue
            txt = b.get("text") or ""
            if budget_left is not None and budget_left <= 0:
                # over budget: first sentence of the first 2 body paragraphs per section, captions kept short
                if role in ("body", "abstract"):
                    n_after_budget += 1
                    if n_after_budget > 2:
                        continue
                    sents = L.split_sentences(txt)
                    txt = (sents[0][:300] + " [...]") if len(sents) > 1 or len(txt) > 300 else txt
                elif role == "caption":
                    txt = txt[:160] + (" [...]" if len(txt) > 160 else "")
                else:
                    continue
            elif len(txt) > max_para and not full:
                txt = txt[:max_para] + " [...]"
            if budget_left is not None:
                budget_left -= len(txt)
            pre_tag = {"caption": "CAPTION ", "equation": "EQ ", "footnote": "FOOTNOTE ", "abstract": "ABSTRACT "}.get(role, "")
            if role == "equation" and b.get("unicode_math"):
                txt = b["unicode_math"]
            lines.append(f"{tag(b)} {pre_tag}{txt}")
    for v in vis:  # visual pages that no (non-reference) section spans
        if v["kind"] == "mixed" and v["page"] not in shown_vis:
            lines.append(f"\n[p{v['page']} VISUAL] {v['reason']}; page image: {v['image']}; image boxes (PDF points): "
                         f"{v.get('image_bboxes')}. Not inside a detected section: read the image, cite 'p{v['page']}@x0,y0,x1,y1: what you read'.")
    if budget_left is not None and budget_left <= 0:
        lines.append(f"\n[digest shortened after {budget // 1000}k chars: later body blocks show first sentence only; "
                     "use `notes.py find` or `find_evidence.py --section N` for full text, or init --full-digest]")
    return "\n".join(lines)


def draft_template(D, fields):
    secs = []
    for s in D.sections:
        if s.get("skip"):
            continue
        secs.append({"section_id": s["id"], "heading": f"{s.get('number') or ''} {s.get('title')}".strip(),
                     "level": s.get("level"), "pages": s["pages"],
                     **{f: None for f in L.SECTION_FIELDS}, "key_points": []})
    titles = [b for b in D.d["blocks"] if b.get("role") == "title" and b["page"] == 1]
    auths = [b for b in D.d["blocks"] if b.get("role") == "author_affiliation" and b["page"] == 1][:4]
    card = {k: None for k in L.CARD_KEYS}
    if titles:
        card["title"] = {"text": " ".join(b["text"] for b in titles), "_prefilled": True,
                         "a": [f"{b['id']}: {b['text'][:120]}" for b in titles]}
    if auths:
        card["authors"] = {"text": " ; ".join(b["text"] for b in auths)[:400], "_prefilled": True,
                           "a": [f"{b['id']}: {b['text'][:80]}" for b in auths]}
    return {
        "_how_to": ("Fill and save, then run `notes.py build`. Every item = {\"text\": your note, \"a\": [anchors]}; "
                    "a field may hold one item or a list of items. Anchor = 'p3-b12: verbatim words copied from that "
                    "block' (6-25 words), or 'Table 2', 'Table 2: cell words', 'Fig. 4', 'Eq. 3'. Numbers in a note "
                    "must appear in its anchored block/table. Set a field to null only with an entry in 'unreported'. "
                    "Delete '_prefilled' keys you overwrite. Sections: fill 'purpose', 'method', 'results', "
                    "'conclusion' (null if not applicable to that section, e.g. Related Work has no results) and "
                    "'transition' (how this section links to the previous/next one). 'contract' maps each "
                    "output_contract field to a value or a reference: '@card', '@card.limitations', '@sections', "
                    "'@knowledge', '@notes_md', '@evidence'."),
        "card": card,
        "sections": secs,
        "knowledge": [{"term": None, "aliases": [], "kind": "concept|term|abbreviation|variable|method|dataset|metric|finding|assumption|formula",
                       "definition": None, "section_id": None, "a": []}],
        "unreported": [{"field": "card.limitations", "reason": "e.g. the paper states no limitations (searched sections ...)"}],
        "conflicts": [],
        "uncertainty": [],
        "contract": {f: None for f in fields},
        "language": "notes in the task's language; quotes stay verbatim in the paper's language",
    }


def parse_any(p, pdir, a, work):
    """PDF -> parse_pdf.py; .md/.markdown/.txt/.docx -> textdoc.py (same doc.json layout)."""
    ext = os.path.splitext(p)[1].lower()
    try:
        if ext == ".pdf":
            import parse_pdf  # noqa: E402
            return parse_pdf.parse(p, pdir, password=a.password, pages=parse_pdf.parse_pages(a.pages),
                                   preview=False, cache_dir=os.path.join(work, "parse_cache"))
        import textdoc  # noqa: E402
        res = textdoc.parse(p, pdir)
        if getattr(a, "pages", None):
            res.setdefault("warnings", []).append(f"--pages '{a.pages}' applies to PDF only; ignored for {ext} input")
        return res
    except Exception as e:  # noqa: BLE001
        return {"status": "failed", "error": f"parser crashed: {type(e).__name__}: {e}"}


def discover_inputs(case, a, case_dir):
    """All candidate input files with resolved paths, scored for the primary role (see role_score)."""
    bases = [case_dir, "/input", os.getcwd()]
    cands = input_candidates(case, [])
    for x in list(a.pdf or []) + list(getattr(a, "input", None) or []):
        cands.append({"path": x, "key": "cli", "role_hint": None, "order": 0})
    if a.primary:
        has_sep = os.sep in a.primary or "/" in a.primary
        if not any((os.path.abspath(c["path"]) == os.path.abspath(a.primary) if has_sep else os.path.basename(c["path"]) == os.path.basename(a.primary)) for c in cands):
            cands.append({"path": a.primary, "key": "cli", "role_hint": "primary", "order": 0})
    seen, out, missing, missing_primary = set(), [], [], []
    for c in cands:
        r = resolve_path(c["path"], bases)
        if not r:
            missing.append(c["path"])
            role_h = (c.get("role_hint") or "").strip()
            key_h = str(c.get("key") or "")
            is_exp = bool(
                (a.primary and (os.path.basename(a.primary) == os.path.basename(c["path"]) or a.primary == c["path"]))
                or (role_h and PRIMARY_RX.match(role_h))
                or (key_h and PRIMARY_RX.match(key_h))
            )
            if is_exp:
                missing_primary.append(c["path"])
            continue
        if os.path.abspath(r) in seen:
            continue
        seen.add(os.path.abspath(r))
        c["resolved"] = r
        out.append(c)
    if not out and not missing_primary:  # nothing named in case.json: every supported file next to it (task.md / case.json excluded)
        k = 0
        for b in (case_dir, "/input"):
            for ext in INPUT_EXT:
                for p in sorted(glob.glob(os.path.join(b, "**", "*" + ext), recursive=True)):
                    ap = os.path.abspath(p)
                    relative = os.path.relpath(ap, b)
                    if ap in seen or NOT_MATERIAL.search(relative) or {"output", "work"}.intersection(relative.split(os.sep)[:-1]):
                        continue
                    seen.add(ap)
                    k += 1
                    out.append({"path": p, "resolved": p, "key": "glob", "role_hint": None, "order": k})
    for c in out:
        c["score"], c["why"] = role_score(c, a.primary)
    out.sort(key=lambda c: -c["score"])
    return out, missing, missing_primary


def write_env(work):
    """work/env.sh: every later shell call can start with '. /app/work/env.sh' (shell state is not kept)."""
    py = sys.executable or "python3"
    skill = os.path.dirname(HERE)
    with open(os.path.join(work, "env.sh"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(f"PY='{py}'\nSKILL_DIR='{skill}'\nexport PY SKILL_DIR\n"
                 f"N() {{ \"$PY\" \"$SKILL_DIR/scripts/notes.py\" \"$@\"; }}\n")
    return os.path.join(work, "env.sh")


def write_result(result, fields, path, diagnostics):
    """Write the case contract and keep run metadata and verification beside it."""
    metadata = {k: result[k] for k in ("status", "run_status", "sources", "unreported", "uncertainty",
                                        "conflicts", "change_log", "outputs") if k in result}
    atomic_dump({**diagnostics, **metadata}, os.path.join(os.path.dirname(path), "verification.json"))
    if fields:  # the run status and its evidence/uncertainty/change records stay at the top level, beside the contract
        core = {"case_id": result.get("case_id"), "status": result.get("status"),
                "status_reason": (result.get("run_status") or {}).get("reason")}
        core.update({k: result[k] for k in ("sources", "uncertainty", "conflicts", "unreported", "change_log") if k in result})
        public = {k: v for k, v in core.items() if k not in fields}
        public.update({key: result.get(key) for key in dict.fromkeys(["case_id", *fields])})
    else:
        public = {k: v for k, v in result.items() if k not in {"verification", "run_status", "outputs"}}
    atomic_dump(public, path)


def previous_result(path):
    result = load(path)
    diagnostics = os.path.join(os.path.dirname(path), "verification.json")
    if os.path.isfile(diagnostics):
        meta = load(diagnostics)
        result.update({k: meta[k] for k in ("status", "run_status", "change_log") if k in meta})
        result["verification"] = meta
    return result


def cmd_init(a):
    t0 = time.time()
    os.makedirs(a.out, exist_ok=True)
    os.makedirs(a.work, exist_ok=True)
    case, case_err = {}, None
    if os.path.exists(a.case):
        try:
            case = load(a.case)
            if not isinstance(case, dict):
                case_err = f"case.json must be a JSON object (got {type(case).__name__})"
                case = {}
        except Exception as e:  # noqa: BLE001
            case_err = f"case.json unreadable: {e}"
    else:
        case_err = f"{a.case} not found"
    case_dir = os.path.dirname(os.path.abspath(a.case))
    task = next((p for p in (os.path.join(case_dir, "task.md"), "/input/task.md") if os.path.exists(p)), None)
    if case_err:
        inputs, missing, missing_primary = [], [], []
        fields, cspec = [], {}
        case_id = os.environ.get("CASE_ID")
    else:
        inputs, missing, missing_primary = discover_inputs(case, a, case_dir)
        fields, cspec = parse_case_contracts(case)
        case_id = case.get("case_id") if "case_id" in case else (case.get("id") or os.environ.get("CASE_ID"))
    sources, docs = [], []
    used_stems = set()
    for i, c in enumerate(inputs):
        p = c["resolved"]
        stem = os.path.splitext(os.path.basename(p))[0]
        while stem in used_stems:
            stem += "_"
        used_stems.add(stem)
        pdir = os.path.join(a.out, "parsed", stem)
        r = parse_any(p, pdir, a, a.work)
        src = {"file": p, "format": os.path.splitext(p)[1].lower().lstrip("."), "sha256": sha256(p), "parsed_dir": pdir,
               "parse_status": r.get("status"), "parse_error": r.get("error"), "page_count": (r.get("meta") or {}).get("page_count"),
               "pages_parsed": r.get("pages_parsed"), "pages_not_parsed": r.get("pages_not_parsed"),
               "unresolved_pages": r.get("unresolved_pages", []), "ocr_pages": r.get("ocr_pages", []),
               "warnings": (r.get("warnings") or [])[:15], "case_key": c.get("key"), "role_hint": c.get("role_hint"),
               "role_score": round(c["score"], 2), "role_reasons": c["why"],
               "_explicit_primary": any(w == "--primary" or w.startswith("role=") and PRIMARY_RX.match(w[5:])
                                        or w.startswith("key=") and PRIMARY_RX.match(w[4:]) for w in c["why"])}
        sources.append(src)
        if r.get("status") != "failed" and os.path.exists(os.path.join(pdir, "doc.json")):
            try:
                docs.append((src, L.Doc(pdir)))
            except Exception as e:  # noqa: BLE001
                src["parse_status"], src["parse_error"] = "failed", f"doc.json unusable: {e}"
    # primary = best-scored input that parsed, UNLESS an explicit primary was missing or failed to parse
    explicit_failed = [s_ for s_ in sources if s_.get("_explicit_primary") and s_.get("parse_status") == "failed"]
    if missing_primary or explicit_failed:
        primary = None
        supp = [(f"S{idx + 1}", src, D) for idx, (src, D) in enumerate(docs)]
    else:
        primary = docs[0] if docs else None
        supp = [(f"S{idx + 1}", src, D) for idx, (src, D) in enumerate(docs[1:])]
    for s_ in sources:
        s_.pop("_explicit_primary", None)
        s_["role"] = "primary" if primary and s_ is primary[0] else (
            next((k for k, x, _ in supp if x is s_), None) and "supplement" or "unparsed")
        s_["source_key"] = "primary" if s_["role"] == "primary" else next((k for k, x, _ in supp if x is s_), None)
    if primary:  # primary first in sources (notes.md / CSV cite sources[0])
        sources.sort(key=lambda x: {"primary": 0, "supplement": 1}.get(x["role"], 2))
    state = {"version": L.VERSION, "case": os.path.abspath(a.case), "case_id": case_id, "task": task,
             "contract_fields": fields, "contract_spec": cspec, "sources": sources, "out": os.path.abspath(a.out),
             "work": os.path.abspath(a.work), "init_at": now(), "missing_inputs": missing,
             "supplements": [{"key": k, "file": s_["file"], "parsed_dir": s_["parsed_dir"]} for k, s_, _ in supp]}
    outline = []
    if primary:
        src, D = primary
        state["parsed_dir"] = src["parsed_dir"]
        try:
            cues = D.cue_sentences()
        except Exception as e:  # noqa: BLE001  (cues are a shortcut; never block init)
            cues = {"error": f"cue extraction failed: {type(e).__name__}: {e}"}
        dg = digest_md(D, a.full_digest, cues=cues)
        if supp:
            dg += "\n\n# SUPPLEMENTARY SOURCES (cite with the prefix, e.g. 'S1::p2-b4: words', 'S1::Table 1: row value')\n"
            for k, s_, SD in supp:
                dg += (f"\n## {k}: {os.path.basename(s_['file'])} ({s_['format']}, {s_.get('page_count')} pages; "
                       f"full digest: {os.path.join(a.work, f'digest_{k}.md')})\n")
                dg += "\n".join(f"  [{k}::{x['id']}] {x.get('number') or ''} {x.get('title')} pp{x['pages'][0]}-{x['pages'][1]}"
                                + (f"  contains: {'; '.join(x.get('tables', []) + x.get('figures', []))}" if x.get("tables") or x.get("figures") else "")
                                for x in SD.sections if not x.get("skip")) + "\n"
                with open(os.path.join(a.work, f"digest_{k}.md"), "w", encoding="utf-8") as fh:
                    fh.write(digest_md(SD, a.full_digest, prefix=f"{k}::", budget=30000))
        with open(os.path.join(a.work, "digest.md"), "w", encoding="utf-8") as fh:
            fh.write(dg)
        dump(cues, os.path.join(a.work, "cues.json"))
        outline = [{k: s.get(k) for k in ("id", "level", "number", "title", "parent", "pages", "first_block",
                                         "last_block", "n_words", "tables", "figures", "equations", "skip",
                                         "appendix", "pseudo", "rule")} for s in D.sections]
        dump({"sections": outline, "fixes": D.outline_fixes, "visual_pages": visual_pages(D)}, os.path.join(a.work, "outline.json"))
        draft_path = os.path.join(a.work, "draft.json")
        if not os.path.exists(draft_path) or a.force:
            dump(draft_template(D, fields), draft_path)
    env = write_env(a.work)
    dump(state, os.path.join(a.work, STATE))
    # valid partial result right away
    result = {"case_id": case_id}
    for f in fields:
        result.setdefault(f, None)
    failed = primary is None or bool(case_err)
    reason = None
    if case_err:
        reason = case_err
    elif missing_primary or explicit_failed:
        parts = []
        if missing_primary:
            parts.append(f"explicit primary missing: {missing_primary}")
        if explicit_failed:
            parts.append("; ".join(f"{os.path.basename(s['file'])}: {s['parse_error']}" for s in explicit_failed))
        reason = "; ".join(parts)
    elif not inputs:
        reason = ("no input file (.pdf/.md/.txt/.docx) found in case.json or the input directory"
                  + (f"; named but missing: {missing}" if missing else ""))
    elif failed:
        reason = "; ".join(f"{os.path.basename(s['file'])}: {s['parse_error']}" for s in sources)
    result.update({
        "status": "failed" if failed else "partial",
        "run_status": {"stage": "init", "reason": reason or "notes not written yet", "case_error": case_err,
                       "seconds": round(time.time() - t0, 2), "tool": L.VERSION},
        "notes": None, "evidence": [], "sources": sources, "unreported": [], "uncertainty": [], "conflicts": [],
        "change_log": [{"at": now(), "step": "init", "detail": f"parsed {len(inputs)} input file(s); primary: "
                        + (os.path.basename(primary[0]['file']) if primary else "none")
                        + (f"; supplements: {', '.join(k + '=' + os.path.basename(s_['file']) for k, s_, _ in supp)}" if supp else "")}],
    })
    if missing:
        result["uncertainty"].append(f"input files named in case.json but not found: {missing}")
    if failed and (inputs or case_err):
        result["unreported"] = [{"field": f, "reason": reason} for f in fields]
    rp = os.path.join(a.out, "result.json")
    keep_prev = False
    if os.path.exists(rp):  # re-running init must not wipe notes already built (or overwrite with a failed --force)
        try:
            prev = previous_result(rp)
            prev_built = prev.get("case_id") == case_id and (prev.get("run_status") or {}).get("stage") == "build"
            keep_prev = prev_built and (not a.force or failed)
        except Exception:  # noqa: BLE001
            keep_prev = False
    if not keep_prev:
        write_result(result, fields, rp, {})
    out = {"case_id": case_id, "contract_fields": fields, "task": task,
           "coverage_checklist": {
               "research_question": "State the exact research question or objective.",
               "method": "Record the design, procedure, comparator, and evaluation.",
               "data": "Report samples, datasets, splits, and measurements.",
               "conditions": "Preserve assumptions, settings, units, and experimental conditions.",
               "main_findings": "Give quantitative results and comparisons.",
               "conclusion": "State the authors’ conclusion and the conditions under which it holds.",
               "limitations": "Report stated limitations and remaining uncertainty.",
           },
           "output_contract": {f: {"required": (cspec.get(f) or {}).get("_required", True),
                                   "schema": {k: v for k, v in (cspec.get(f) or {}).items() if k != "_required"},
                                   "draft_value": None} for f in fields},
           "source_index": [{"key": s["source_key"], "role": s["role"], "file": s["file"],
                             "status": s["parse_status"], "parsed_dir": s["parsed_dir"],
                             "digest": os.path.join(a.work, "digest.md" if s["role"] == "primary"
                                                    else f"digest_{s['source_key']}.md") if s["source_key"] and primary else None}
                            for s in sources],
           "inputs": [os.path.basename(s["file"]) + f" [{s['role']}{'=' + s['source_key'] if s.get('source_key') not in (None, 'primary') else ''}]"
                      + (f" ({', '.join(s['role_reasons'])})" if s["role_reasons"] else "") for s in sources],
           "primary": primary[0]["file"] if primary else None,
           "parse_status": [s["parse_status"] for s in sources], "parse_error": [s["parse_error"] for s in sources if s["parse_error"]],
           "missing_inputs": missing, "unresolved_pages": [s["unresolved_pages"] for s in sources],
           "digest": os.path.join(a.work, "digest.md"), "cues": os.path.join(a.work, "cues.json"),
           "draft": os.path.join(a.work, "draft.json"), "result": rp, "env": env,
           "outline": [f"{s['id']} L{s['level']} {s.get('number') or ''} {s['title']} pp{s['pages'][0]}-{s['pages'][1]}"
                       + (" [skip]" if s.get("skip") else "") + (" [appendix]" if s.get("appendix") else "")
                       for s in outline]}
    if primary:
        vp = visual_pages(primary[1])
        if vp:
            out["visual_pages"] = [f"p{v['page']}: {v['reason']}" for v in vp]
    if keep_prev:
        out["note_result"] = "result.json from an earlier build kept (use --force to reset it)"
    if supp:
        out["note"] = ("primary chosen by role/key/file name (see inputs); supplements are parsed too: cite them as "
                       "'S1::p2-b4: words'; their digests are digest_S1.md ...; use --primary FILE to override")
    if case_err:  # exit code stays 0 (the partial result is written), but a broken case must not pass silently
        print(f"WARNING: case input not usable: {case_err}", file=sys.stderr)
    print(json.dumps(out, ensure_ascii=False, indent=1))


# ------------------------------------------------------------------ build
ITEM_ANCHOR_KEYS = ("a", "anchors", "anchor", "evidence", "source", "sources", "cite", "citation", "refs", "locator")
ITEM_TEXT_KEYS = ("text", "note", "claim", "content", "summary", "statement", "value")
SRC_PREFIX = re.compile(r"^\s*(S\d{1,2})\s*::\s*(.+)$", re.S)
NUM_SUFFIX_CTX = r"\s*(节|章|页|段|部分|行|列|条|小节|篇)"
YEAR_CTX = re.compile(r"(\b(in|since|from|until|by|year|during|circa)\s+$)|^\s*(年|年度|年代)")


def item_anchor_key(v):
    return next((k for k in ITEM_ANCHOR_KEYS if k in v and v[k] not in (None, "", [])), None)


def item_anchors(v):
    k = item_anchor_key(v)
    x = v[k] if k else []
    return [x] if isinstance(x, (str, dict)) else list(x or [])


def as_items(v):
    """Normalise a field value into a list of {'text', 'a'} items (tolerates 'note'/'claim' for text and
    'anchors'/'evidence'/'source' for anchors, a bare string, or a list of either)."""
    if v is None:
        return []
    if isinstance(v, str):
        return [{"text": v, "a": []}] if v.strip() else []
    if isinstance(v, dict):
        if any(k in v for k in ITEM_TEXT_KEYS + ITEM_ANCHOR_KEYS):
            tk = next((k for k in ITEM_TEXT_KEYS if isinstance(v.get(k), str)), None)
            text = v.get(tk) if tk else None
            used = {tk, item_anchor_key(v), "a", "anchors"}
            return [{"text": text, "a": item_anchors(v), **{k: x for k, x in v.items() if k not in used}}]
        return [{"text": json.dumps(v, ensure_ascii=False), "a": []}]
    if isinstance(v, list):
        out = []
        for x in v:
            out += as_items(x)
        return out
    return [{"text": str(v), "a": []}]


class Checker:
    def __init__(self, D, supplements=None):
        self.D = D
        self.supp = dict(supplements or {})  # 'S1' -> Doc
        self.records = []  # one per checked item
        self.evidence = []

    def resolve(self, x):
        """Resolve one anchor in the primary paper, or in a supplement when prefixed 'S1::' / {'source': 'S1'}."""
        key, inner = None, x
        if isinstance(x, str):
            m = SRC_PREFIX.match(x)
            if m:
                key, inner = m.group(1).upper(), m.group(2)
        elif isinstance(x, dict) and str(x.get("source") or "").upper() in self.supp:
            key = str(x["source"]).upper()
        if key is None:
            return self.resolve_in(self.D, x), self.D
        Ds = self.supp.get(key)
        if Ds is None:
            return {"raw": x, "ok": False, "check": "source_not_found", "known_sources": sorted(self.supp)}, None
        r = self.resolve_in(Ds, inner)
        r["raw"] = x
        r["source"] = key
        r["source_file"] = os.path.basename((Ds.d.get("meta") or {}).get("source_file") or "")
        if r.get("section_id"):
            r["section_id"] = f"{key}:{r['section_id']}"
        return r, Ds

    @staticmethod
    def resolve_in(doc, anchor):
        r = doc.resolve(anchor)
        if not r.get("ok"):
            return r
        block = doc.blocks.get(r.get("block_id"), {})
        if not r.get("section"):
            page = r.get("page")
            r["section"] = ("Front matter" if block.get("role") in ("title", "author_affiliation") else
                            next((s["path"] for s in doc.sections if page is not None and s["pages"][0] <= page <= s["pages"][1]),
                                 "Section unavailable"))
        if r.get("check") == "quote_fuzzy":
            r["quote"] = r["source_sentence"]
        elif r.get("matched_rows"):
            r["quote"] = r["matched_rows"][0]
        elif r.get("weak") or r.get("check") == "figure_reading_unverified":
            source = r.get("caption") or block.get("text") or ""
            r["quote"] = next(iter(L.split_sentences(source)), None)
        elif r.get("check") == "equation_exists":
            r["quote"] = r.get("expr_unicode")
        return r

    def check_item(self, item, where, section_id=None):
        D = self.D
        anchors = item.get("a") or []
        if isinstance(anchors, (str, dict)):
            anchors = [anchors]
        pairs = [self.resolve(x) for x in anchors]
        res = [r for r, _ in pairs]
        text = item.get("text") or ""
        if not isinstance(text, str):
            text = json.dumps(text, ensure_ascii=False)
        problems, review = [], []
        if not text.strip():
            problems.append("empty_text")
        if not res:
            problems.append("no_anchor")
        for r in res:
            if not r.get("ok"):
                problems.append(f"anchor_failed:{r.get('check')}:{r.get('raw')}"[:200])
            elif r.get("needs_review") or r.get("check") in ("relocated",):
                review.append(f"{r.get('check')}:{r.get('raw')}"[:200])
            elif r.get("weak"):
                review.append(f"weak_anchor:{r.get('check')}:{r.get('raw')}"[:200])
            if r.get("warning"):
                review.append(r["warning"])
        # section alignment: section notes should cite inside the section (or its subsections)
        outside = []
        if section_id:
            for r in res:
                sid = r.get("section_id")
                if r.get("ok") and sid and sid != section_id and (r.get("source") or not D.is_ancestor(section_id, sid)):
                    outside.append(f"{r.get('raw')} -> {sid}")
            if outside and len(outside) == len([r for r in res if r.get("ok")]):
                review.append("all anchors outside this section: " + "; ".join(outside)[:200])
        # numbers: every number in the note must occur in anchored evidence (same value in another notation /
        # scale word counts: 60 亿 = 6 billion, 128 万 = 1.28 million, 95% = 0.95)
        ev_nums, ev_text = set(), []
        for r, Dx in pairs:
            if r.get("ok") and Dx is not None:
                t = Dx.evidence_text(r)
                ev_text += [t, r.get("quote") or ""]
                ev_nums |= L.numbers_in(t)
                ev_nums |= L.numbers_in(r.get("quote") or "")
        ev_q = None
        allowed_ctx = set()
        for r in res:  # the label number of an anchor (Table 2, Eq. 3), exact string only
            lab = SRC_PREFIX.sub(r"\2", str(r.get("raw"))).split(":", 1)[0]
            if not re.match(r"^\s*(p\d+[-@]|L\d|line)", lab, re.I):
                allowed_ctx |= set(re.findall(r"\d+(?:\.\d+)*", lab))
        unsupported, minor, equiv = [], [], []
        for n in L.note_numbers(text):
            variants = L.numbers_in(n)
            if variants & ev_nums:
                continue
            ctx = re.search(r"(table|fig\.?|figure|eq\.?|section|sec\.?|§|表|图|式|第|公式|附录|appendix)\s*" + re.escape(n), text, re.I) \
                or re.search(r"(?<![\d.])" + re.escape(n) + NUM_SUFFIX_CTX, text)
            if ctx or n in allowed_ctx:
                continue
            if ev_q is None:
                ev_q = L.quantity_set(" ".join(ev_text))
            eq = L.equivalent_number(n, text, ev_q)
            if eq:
                equiv.append(eq)
                continue
            small = bool(re.fullmatch(r"-?\d", n))  # single-digit integers: too ambiguous to fail on
            year = bool(re.fullmatch(r"(19|20)\d\d", n)) and any(
                YEAR_CTX.search(text[max(0, m.start() - 8):m.start()]) or YEAR_CTX.search(text[m.end():m.end() + 3])
                for m in re.finditer(r"(?<!\d)" + n + r"(?!\d)", text))
            (minor if small or year else unsupported).append(n)
        if unsupported:
            if res:
                problems.append("numbers_not_in_evidence:" + ",".join(unsupported))
        # metric / endpoint mismatch check (high-precision vocabulary; flags for human review)
        if res and ev_text:
            ev_joined = " ".join(ev_text)
            metric_groups = [
                ("HR", r"(?<![A-Za-z])HR(?![A-Za-z])|\bhazard\s+ratios?\b|风险比"),
                ("OR", r"(?<![A-Za-z])OR(?![A-Za-z])|\bodds\s+ratios?\b|比值比"),
                ("RR", r"(?<![A-Za-z])RR(?![A-Za-z])|\b(?:risk|rate)\s+ratios?\b|\brelative\s+risk\b|相对危险度"),
            ]
            note_m = {lbl for lbl, rx in metric_groups if re.search(rx, text, re.I if "hazard" in rx or "odds" in rx or "risk" in rx else 0)
                      and (lbl != "OR" or re.search(r"(?<![A-Za-z])OR(?![A-Za-z])|\bodds\s+ratios?\b|比值比", text))}
            ev_m = {lbl for lbl, rx in metric_groups if re.search(rx, ev_joined, re.I if "hazard" in rx or "odds" in rx or "risk" in rx else 0)
                    and (lbl != "OR" or re.search(r"(?<![A-Za-z])OR(?![A-Za-z])|\bodds\s+ratios?\b|比值比", ev_joined))}
            if note_m and ev_m and not (note_m & ev_m):
                review.append(f"metric_mismatch: note mentions {sorted(note_m)}, evidence mentions {sorted(ev_m)}")
            ep_groups = [
                ("mortality", r"\bmortality\b|\bdeaths?\b|死亡率?"),
                ("hospitalization", r"\bhospitali[sz]ations?\b|\breadmissions?\b|住院率?|再入院"),
                ("recurrence", r"\brecurrences?\b|\brelapses?\b|复发率?"),
                ("incidence", r"\bincidence\b|发病率"),
            ]
            note_ep = {lbl for lbl, rx in ep_groups if re.search(rx, text, re.I)}
            ev_ep = {lbl for lbl, rx in ep_groups if re.search(rx, ev_joined, re.I)}
            if note_ep and ev_ep and not (note_ep & ev_ep):
                review.append(f"endpoint_mismatch: note mentions {sorted(note_ep)}, evidence mentions {sorted(ev_ep)}")
        info = {"small_numbers_unchecked": minor} if minor else {}
        if equiv:
            info["number_equivalence"] = equiv
        ok = not problems
        verified = ok and not review and any(r.get("check") in ("quote_verbatim", "quote_in_table", "quote_in_caption",
                                                                  "quote_in_neighbour_block", "table_exists",
                                                                  "equation_exists", "figure_exists") for r in res)
        status = "verified" if verified else ("needs_review" if ok else "failed")
        rec = {"where": where, "status": status, "problems": problems, "review": review,
               "numbers_checked": [n for n in L.note_numbers(text) if n not in unsupported + minor]}
        rec.update(info)
        self.records.append(rec)
        clean = [{k: v for k, v in r.items() if k not in ("score",) or r.get("check") != "quote_verbatim"} for r in res]
        for r in clean:
            if r.get("ok"):
                self.evidence.append({"field": where, **{k: r.get(k) for k in (
                    "kind", "source", "source_file", "page", "block_id", "paragraph_id", "line_start", "line_end",
                    "source_paragraph", "table", "figure", "equation", "bbox", "section_id", "section", "quote", "check")
                    if r.get(k) is not None}})
        out = {k: v for k, v in item.items() if k not in ("a", "anchors", "_prefilled")}
        out["anchors"] = clean
        out["check"] = {"status": status, **({"problems": problems} if problems else {}),
                        **({"review": review} if review else {}), **info}
        if not verified:
            out["warn"] = ("Check the claim against the cited source." if any(r.get("ok") for r in res)
                           else "No source anchor was verified for this note.")
        return out


VARIANT_WORDS = {"图象": "图像", "其它": "其他", "帐户": "账户", "帐号": "账号", "部份": "部分", "份量": "分量",
                 "迭代次数": "迭代次数", "神经元网络": "神经网络", "colour": "color", "modelling": "modeling",
                 "optimisation": "optimization", "generalisation": "generalization", "normalisation": "normalization",
                 "regularisation": "regularization", "behaviour": "behavior", "analyse": "analyze"}


def norm_term(t):
    t = L.nfkc(t or "").lower().strip()
    for a_, b_ in VARIANT_WORDS.items():
        t = t.replace(a_, b_)
    t = re.sub(r"[\s\-_/·•]+", " ", t)
    t = re.sub(r"(?<=[一-鿿]) (?=[一-鿿])", "", t)
    t = re.sub(r"[\"'“”‘’「」『』《》〈〉]", "", t)
    t = re.sub(r"(?<=[a-z]{3})(es|s)$", "", t)
    return t.strip()


def split_term(t):
    """'卷积神经网络（CNN）' / 'Convolutional Neural Network (CNN)' -> ['卷积神经网络', 'CNN']."""
    t = L.nfkc(t or "").strip()
    m = re.match(r"^(.+?)\s*[(（]\s*([^()（）]{1,40})\s*[)）]\s*$", t)
    return [m.group(1).strip(), m.group(2).strip()] if m else [t]


def is_abbr(x):
    return bool(re.fullmatch(r"[A-Z][A-Za-z0-9\-]{1,9}s?", x or "") and sum(c.isupper() for c in x) >= 2)


def expansion(ab, phrase):
    """Shortest trailing run of words whose initials spell the abbreviation (else last 4 words)."""
    words = re.findall(r"[A-Za-z][\w\-]*", phrase or "")
    letters = re.sub(r"s$", "", ab).lower()
    for n in range(1, min(len(words), 10) + 1):
        tail = words[-n:]
        ini = "".join(w[0] for w in tail).lower()
        ini2 = "".join(p[0] for w in tail for p in w.split("-") if p).lower()
        if letters in (ini, ini2):
            return " ".join(tail)
    if re.search(r"[一-鿿]", phrase or ""):
        return (phrase or "").strip()[-20:]
    if len(words) <= 6:
        return " ".join(words)
    return " ".join(words[-4:])


def initials(phrase):
    ws = [w for w in re.findall(r"[A-Za-z][\w]*", L.nfkc(phrase or "")) if w.lower() not in ("of", "and", "the", "for", "in", "on", "a", "an", "to", "with")]
    return "".join(w[0] for p in ws for w in [p]).lower()


def _similar(a, b):
    ta, tb = set(re.findall(r"[a-z0-9]+|[一-鿿]", L.nfkc(a or "").lower())), set(re.findall(r"[a-z0-9]+|[一-鿿]", L.nfkc(b or "").lower()))
    if not ta or not tb:
        return 1.0
    return len(ta & tb) / max(1, min(len(ta), len(tb)))


def merge_knowledge(items, D):
    """One entry per concept. Merged when a normalised name/alias is shared (case, plural, hyphen, 中文空格/异形词,
    'Long Form (ABBR)'), or when an abbreviation's long form printed in the paper equals another entry's term.
    NOT merged when the only shared key is an abbreviation and the long forms differ ('SA' = self-attention vs
    simulated annealing): reported as abbreviation_collision. Definitions that disagree (low word overlap or
    different numbers) are flagged as definition_conflict, with the sections that define them."""
    groups, order, log, conflicts = {}, [], [], []
    full = " ".join(D.blocks[b].get("text") or "" for b in D.order)
    printed = {}  # ABBR -> long form printed in the paper

    def printed_long(ab):
        if ab not in printed:
            pat = re.compile(r"([A-Za-z一-鿿][\w\- 一-鿿]{1,80}?)\s*[(（]\s*" + re.escape(ab) + r"\s*[)）]|"
                             + re.escape(ab) + r"\s*[(（]([^)）]{4,80})[)）]")
            m = pat.search(full)
            printed[ab] = (expansion(ab, m.group(1) or m.group(2)) if m else None)
        return printed[ab]

    def keyset(it):
        names = []
        for x in [it.get("term")] + list(it.get("aliases") or []):
            if isinstance(x, str) and x.strip():
                names += split_term(x)
        longs = {norm_term(x) for x in names if not is_abbr(x)}
        abbrs = {x for x in names if is_abbr(x)}
        if not longs:  # a bare abbreviation takes the long form the paper prints for it
            for ab in abbrs:
                lf = printed_long(ab)
                if lf:
                    longs.add(norm_term(lf))
        return {norm_term(x) for x in names}, longs, abbrs, names

    for it in items:
        if not isinstance(it, dict) or not isinstance(it.get("term"), str) or not it["term"].strip():
            continue
        keys, longs, abbrs, names = keyset(it)
        hit = None
        for g in order:
            G = groups[g]
            shared = keys & G["_keys"]
            long_shared = longs & G["_longs"]
            if not shared and not long_shared:
                # abbreviation spelled by the other entry's long form ('CNN' vs 'convolutional neural network')
                if any(initials(lf) == ab.lower().rstrip("s") for ab in abbrs for lf in G["_longs"]) or \
                        any(initials(lf) == ab.lower().rstrip("s") for ab in G["_abbrs"] for lf in longs):
                    hit = g
                    break
                continue
            abbr_keys = {norm_term(x) for x in abbrs | G["_abbrs"]}
            only_abbr = bool(shared) and shared <= abbr_keys and not long_shared
            if only_abbr and longs and G["_longs"] and not (longs & G["_longs"]) and \
                    max(_similar(a_, b_) for a_ in longs for b_ in G["_longs"]) < 0.5:
                conflicts.append({"kind": "abbreviation_collision", "abbr": sorted(shared)[0], "terms": [G["term"], it["term"]],
                                  "note": "same abbreviation, different long forms: kept as two entries; check which one the paper means"})
                continue
            hit = g
            break
        if hit is None:
            g = dict(it)
            g["aliases"] = list(dict.fromkeys(x for x in (it.get("aliases") or []) if isinstance(x, str)))
            for x in names[1:] if len(split_term(it["term"])) > 1 else []:
                if norm_term(x) not in {norm_term(y) for y in g["aliases"]} and norm_term(x) != norm_term(it["term"]):
                    g["aliases"].append(x)
            g["a"] = item_anchors(it)
            g["_keys"], g["_longs"], g["_abbrs"] = set(keys), set(longs), set(abbrs)
            g["_defs"] = [(it.get("definition"), it.get("section_id"))] if it.get("definition") else []
            gk = len(order)  # keyed by position: two entries may share a term ('SA' vs 'SA')
            groups[gk] = g
            order.append(gk)
        else:
            g = groups[hit]
            log.append({"merged": it["term"], "into": g["term"]})
            g["_keys"] |= keys
            g["_longs"] |= longs
            g["_abbrs"] |= abbrs
            for x in [it["term"]] + [y for y in (it.get("aliases") or []) if isinstance(y, str)]:
                if norm_term(x) != norm_term(g["term"]) and norm_term(x) not in {norm_term(y) for y in g["aliases"]}:
                    g["aliases"].append(x)
            g["a"] += [x for x in item_anchors(it) if x not in g["a"]]
            if it.get("definition") and it["definition"] not in [d_ for d_, _ in g["_defs"]]:
                g["_defs"].append((it["definition"], it.get("section_id")))
    out = []
    for t in order:
        g = groups[t]
        defs = g.pop("_defs")
        for k in ("_keys", "_longs", "_abbrs"):
            g.pop(k)
        g["definition"] = defs[0][0] if defs else g.get("definition")
        if len(defs) > 1:
            g["other_definitions"] = [d_ for d_, _ in defs[1:]]
            base = defs[0][0]
            bad = []
            for d_, sid in defs[1:]:
                n0 = {x for x in L.note_numbers(base) if not re.fullmatch(r"-?\d", x)}
                n1 = {x for x in L.note_numbers(d_) if not re.fullmatch(r"-?\d", x)}
                if (n0 and n1 and n0 != n1) or _similar(base, d_) < 0.35:
                    bad.append({"definition": d_, "section_id": sid,
                                "why": "different numbers" if (n0 and n1 and n0 != n1) else "low word overlap"})
            if bad:
                g["definition_conflict"] = {"first": {"definition": base, "section_id": defs[0][1]}, "disagreeing": bad}
                conflicts.append({"kind": "definition_conflict", "term": g["term"], "sections": [defs[0][1]] + [b["section_id"] for b in bad],
                                  "note": "the same concept is defined differently; check the paper (cross-section definition drift?)"})
            else:
                g["definitions_agree"] = True
        abbrs = [y for x in [g["term"]] + g["aliases"] for y in split_term(x) if is_abbr(y)]
        if abbrs:
            ab = abbrs[0]
            lf = printed_long(ab)
            g["abbreviation"] = {"abbr": ab, "expansion_in_paper": lf, "status": "found_in_text" if lf else "expansion_not_printed"}
            mine = [y for x in [g["term"]] + g["aliases"] for y in split_term(x) if not is_abbr(y)]
            if lf and mine and not re.search(r"[一-鿿]", " ".join(mine)) and max(_similar(lf, m_) for m_ in mine) < 0.5:
                g["abbreviation"]["status"] = "expansion_mismatch"
                g["abbreviation"]["note"] = f"the paper expands {ab} as '{lf}', not as {mine}"
        g["text"] = g.get("definition") or g["term"]
        out.append(g)
    return out, log, conflicts


def render_md(res, D, state):
    n = res["notes"]
    L_ = []
    card = n["paper_card"]

    def cite(it):
        refs = []
        for r in it.get("anchors", []):
            if not r.get("ok"):
                refs.append(f"✗{r.get('raw')}")
                continue
            lab = r.get("block_id") or r.get("table") or r.get("figure") or r.get("equation") or f"p{r.get('page')}"
            if r.get("line_start") is not None:
                lab += f" L{r['line_start']}" + (f"-{r['line_end']}" if r.get("line_end") not in (None, r["line_start"]) else "")
            source = f"{r['source']}:{r.get('source_file') or ''} " if r.get("source") else ""
            quote = " ".join(str(r.get("quote") or "").split()).replace("|", "&#124;")
            excerpt = f' · “{quote}”' if quote else ""
            refs.append(f"{source}p.{r.get('page')} {r.get('section') or 'Section unavailable'} {lab}{excerpt}")
        warning = f" ⚠ {it['warn']}" if it.get("warn") else ""
        return (" 〔" + "; ".join(refs) + "〕" if refs else " 〔no anchor〕") + warning

    def items_md(v, indent=""):
        out = []
        for it in v or []:
            out.append(f"{indent}- {it.get('text')}{cite(it)}")
        return out

    title = (card.get("title") or [{}])[0].get("text") if card.get("title") else "(title not found)"
    L_.append(f"# Notes: {title}")
    L_.append(f"\ncase_id: `{res.get('case_id')}` · source: `{os.path.basename(state['sources'][0]['file'])}` "
              f"(sha256 {state['sources'][0]['sha256'][:12]}…) · status: **{res['status']}** · built {now()} by {L.VERSION}")
    for sp in state.get("supplements") or []:
        L_.append(f"supplement `{sp['key']}`: `{os.path.basename(sp['file'])}` (cited as 〔{sp['key']}:file p.PAGE BLOCK〕)")
    L_.append("\nCitation format: 〔p.PAGE §SECTION BLOCK〕; BLOCK = p{page}-b{n} in `parsed/*/doc.json`"
              + (" (text inputs add source lines L..)" if (D.d.get("meta") or {}).get("format") not in (None, "pdf") else "")
              + ". ⚠ = needs human review, ✗ = check failed.")
    L_.append("\n## 1. Paper card")
    for k, desc, _ in L.CARD_FIELDS:
        v = card.get(k)
        L_.append(f"\n**{k}** — {desc}")
        if not v:
            why = next((u["reason"] for u in res["unreported"] if u.get("field") in (k, "card." + k)), "not filled")
            L_.append(f"- *not reported:* {why}")
        else:
            L_ += items_md(v)
    L_.append("\n## 2. Section-by-section notes (paper's own order)")
    for s in n["section_notes"]:
        sec = D.sec_by_id.get(s["section_id"], {})
        h = "###" if (sec.get("level") or 1) <= 1 else "####"
        L_.append(f"\n{h} {s.get('heading')}  (pp. {s['pages'][0]}–{s['pages'][1]}, `{s['section_id']}`)")
        empty = True
        for f in L.SECTION_FIELDS + ["key_points"]:
            v = s.get(f)
            if v:
                empty = False
                L_.append(f"- *{f}*:")
                L_ += items_md(v, "  ")
        if empty:
            L_.append("- *(no notes for this section)*" + (f" — {s.get('skip_reason')}" if s.get("skip_reason") else ""))
    L_.append("\n## 3. Knowledge points")
    L_.append("\n| term | aliases | kind | definition / statement | where |\n|---|---|---|---|---|")
    for k in n["knowledge_points"]:
        al = ", ".join(k.get("aliases") or [])
        ab = k.get("abbreviation")
        if ab:
            al += f" (abbr. check: {ab['status']})"
        L_.append(f"| {k.get('term')} | {al} | {k.get('kind') or ''} | {(k.get('definition') or '').replace('|', '/')} |{cite(k)} |")
    L_.append("\n## 4. Not reported / uncertain / conflicts")
    for u in res["unreported"]:
        L_.append(f"- unreported `{u.get('field')}`: {u.get('reason')}")
    for u in res["uncertainty"]:
        L_.append(f"- uncertain: {u if isinstance(u, str) else json.dumps(u, ensure_ascii=False)}")
    for c in res["conflicts"]:
        L_.append(f"- conflict: {c if isinstance(c, str) else json.dumps(c, ensure_ascii=False)}")
    v = res["verification"]
    L_.append("\n## 5. Verification summary")
    L_.append(f"- items: {v['n_items']} · verified {v['n_verified']} · needs review {v['n_needs_review']} · failed {v['n_failed']}")
    L_.append(f"- section coverage: {v['section_coverage']['covered']}/{v['section_coverage']['required']} top-level sections; "
              f"missing: {', '.join(v['section_coverage']['missing']) or 'none'}")
    L_.append(f"- card fields missing without reason: {', '.join(v['card_missing']) or 'none'}")
    L_.append("- machine-checked: anchor exists, quote verbatim in the cited block, page/section of the anchor, numbers in note ⊂ anchored text, "
              "abbreviation expansions. Human check needed: whether the note's wording is a faithful reading of the quote, figure readings, "
              "page-image readings, fuzzy quotes.")
    return "\n".join(L_) + "\n"


def resolve_ref(ref, res, md_path):
    n = res["notes"]
    if not isinstance(ref, str) or not ref.startswith("@"):
        return None, False
    r = ref[1:]
    if r == "card":
        return n["paper_card"], True
    if r.startswith("card."):
        return n["paper_card"].get(r[5:]), True
    if r == "sections":
        return n["section_notes"], True
    if r == "knowledge":
        return n["knowledge_points"], True
    if r == "notes_md":
        return os.path.basename(md_path), True
    if r == "evidence":
        return res["evidence"], True
    if r == "verification":
        return res["verification"], True
    return None, False


AUTO_MAP = [
    (r"(?<![a-z0-9])(?:card|paper_card|summary_card)(?![a-z0-9])|结构化|卡片", "@card"),
    (r"(?<![a-z0-9])(?:sections?|chapters?)(?![a-z0-9])|章节", "@sections"),
    (r"(?<![a-z0-9])(?:knowledge|concepts?|terms?|glossary)(?![a-z0-9])|知识点|术语", "@knowledge"),
    (r"(?<![a-z0-9])limitations?(?![a-z0-9])|局限", "@card.limitations"),
    (r"(?<![a-z0-9])(?:main_findings|findings|results?)(?![a-z0-9])|发现|结果", "@card.main_findings"),
    (r"(?<![a-z0-9])(?:research_question|question)(?![a-z0-9])|问题", "@card.research_question"),
    (r"(?<![a-z0-9])methods?(?![a-z0-9])|方法", "@card.method"),
    (r"(?<![a-z0-9])(?:conditions?|settings?)(?![a-z0-9])|条件|设置", "@card.conditions"),
    (r"(?<![a-z0-9])(?:data|dataset|datasets|data_source)(?![a-z0-9])|数据", "@card.data"),
    (r"(?<![a-z0-9])conclusions?(?![a-z0-9])|结论", "@card.conclusion"),
    (r"(?<![a-z0-9])(?:evidence|sources?|anchors?)(?![a-z0-9])|证据|来源", "@evidence"),
    (r"(?<![a-z0-9])(?:notes?|markdown)(?![a-z0-9])|笔记", "@notes_md"),
    (r"(?<![a-z0-9])(?:summary|overview|answer|report)(?![a-z0-9])|摘要|总结|报告", "@card"),
]


def validate_and_coerce_contract(val, sp, path="contract"):
    """Validate and safely coerce a contract value against JSON-schema-like spec. Returns (val, gaps)."""
    gaps = []
    if val is None or not isinstance(sp, dict):
        return val, gaps
    t = sp.get("type").lower() if isinstance(sp.get("type"), str) else None
    if t == "string":
        if isinstance(val, str):
            pass
        elif isinstance(val, list) and all(isinstance(x, str) for x in val):
            val = "\n".join(val)
        else:
            val = json.dumps(val, ensure_ascii=False)
    elif t == "integer":
        if isinstance(val, int) and not isinstance(val, bool):
            pass
        elif isinstance(val, float) and val.is_integer():
            val = int(val)
        elif isinstance(val, str) and re.fullmatch(r"\s*[+-]?\d+\s*", val):
            val = int(val.strip())
        else:
            gaps.append({"field": path, "reason": f"expected integer, got {type(val).__name__}: {repr(val)[:60]}"})
            return val, gaps
    elif t == "number":
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            pass
        elif isinstance(val, str):
            try:
                f = float(val.strip())
                if f != f or f in (float("inf"), float("-inf")):
                    raise ValueError("non-finite")
                val = f
            except ValueError:
                gaps.append({"field": path, "reason": f"expected number, got string: {repr(val)[:60]}"})
                return val, gaps
        else:
            gaps.append({"field": path, "reason": f"expected number, got {type(val).__name__}: {repr(val)[:60]}"})
            return val, gaps
    elif t == "boolean":
        if isinstance(val, bool):
            pass
        elif isinstance(val, str):
            s = val.strip().lower()
            if s in ("true", "1", "yes", "on"):
                val = True
            elif s in ("false", "0", "no", "off"):
                val = False
            else:
                gaps.append({"field": path, "reason": f"expected boolean, got string: {repr(val)[:40]}"})
                return val, gaps
        elif isinstance(val, int) and val in (0, 1):
            val = bool(val)
        else:
            gaps.append({"field": path, "reason": f"expected boolean, got {type(val).__name__}"})
            return val, gaps
    elif t == "array":
        if not isinstance(val, list):
            if isinstance(sp.get("items"), dict):
                gaps.append({"field": path, "reason": f"expected array, got {type(val).__name__}"})
                return val, gaps
            val = [{"key": k, "value": v} for k, v in val.items()] if isinstance(val, dict) else [val]
        if isinstance(sp.get("items"), dict):
            new_list = []
            for i, elem in enumerate(val):
                ce, eg = validate_and_coerce_contract(elem, sp["items"], f"{path}[{i}]")
                new_list.append(ce)
                gaps.extend(eg)
            val = new_list
    elif t == "object" or (isinstance(sp.get("properties"), dict) and isinstance(val, dict)):
        if not isinstance(val, dict):
            if isinstance(sp.get("properties"), dict):
                gaps.append({"field": path, "reason": f"expected object, got {type(val).__name__}"})
                return val, gaps
            val = {"items": val} if isinstance(val, list) else {"value": val}
        elif isinstance(sp.get("properties"), dict):
            props = sp["properties"]
            has_req = "required" in sp and isinstance(sp.get("required"), list)
            req_list = sp.get("required") if has_req else []
            out_obj = dict(val)
            for pk, psp in props.items():
                psp_d = psp if isinstance(psp, dict) else {}
                is_req = (pk in req_list) or bool(psp_d.get("required")) or (not has_req and psp_d.get("required") is not False)
                if pk in out_obj and out_obj[pk] is not None:
                    cv, cg = validate_and_coerce_contract(out_obj[pk], psp_d, f"{path}.{pk}")
                    out_obj[pk] = cv
                    gaps.extend(cg)
                elif is_req:
                    gaps.append({"field": f"{path}.{pk}", "reason": "required nested property missing"})
            for rk in req_list:
                if isinstance(rk, str) and rk not in props and (rk not in out_obj or out_obj[rk] is None):
                    gaps.append({"field": f"{path}.{rk}", "reason": "required nested property missing"})
            val = out_obj
    if isinstance(sp.get("enum"), list) and val not in sp["enum"]:
        gaps.append({"field": path, "reason": f"value {repr(val)[:40]} not in enum {sp['enum'][:10]}"})
    return val, gaps


def _coerce_contract(val, sp):
    return validate_and_coerce_contract(val, sp)[0]


def walk_anchors(v, ck, where, dropped=None):
    """Resolve anchors inside literal contract values (dicts with 'a'/'anchors')."""
    if isinstance(v, dict):
        if "a" in v or "anchors" in v:
            it = ck.check_item({**v, "a": item_anchors(v),
                                "text": v.get("text") or json.dumps({k: x for k, x in v.items() if k not in ("a", "anchors")}, ensure_ascii=False)}, where)
            if (it.get("check") or {}).get("status") == "failed" and not any(r.get("ok") for r in it["anchors"]):
                if dropped is not None:
                    dropped.append(dict(it, where=where))
                return None
            return it
        out_d = {}
        for k, x in v.items():
            wx = walk_anchors(x, ck, f"{where}.{k}", dropped)
            if wx is None and x is not None:
                continue
            out_d[k] = wx
        return out_d
    if isinstance(v, list):
        out_l = []
        for i, x in enumerate(v):
            wx = walk_anchors(x, ck, f"{where}[{i}]", dropped)
            if wx is None and x is not None:
                continue
            out_l.append(wx)
        return out_l
    return v


# ------------------------------------------------------------------ draft safety (load / normalise / merge)
class DraftError(Exception):
    pass


def _strip_trailing_commas(t):
    """Remove ',' before '}' / ']' outside strings."""
    out, ins, esc, i = [], False, False, 0
    while i < len(t):
        ch = t[i]
        if ins:
            out.append(ch)
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                ins = False
        elif ch == '"':
            ins = True
            out.append(ch)
        elif ch == ",":
            j = i + 1
            while j < len(t) and t[j] in " \t\r\n":
                j += 1
            if j < len(t) and t[j] in "}]":
                i += 1
                continue
            out.append(ch)
        else:
            out.append(ch)
        i += 1
    return "".join(out)


def lenient_json(text, what="draft"):
    """Strict JSON first; then the repairs an LLM-written file most often needs: BOM, ```json fences, leading
    prose, trailing commas, Python literals. Returns (obj, repairs). Raises DraftError with line/column context."""
    repairs = []
    t = text.lstrip("﻿")
    try:
        return json.loads(t), repairs
    except json.JSONDecodeError as e:
        first = e
    m = re.search(r"```(?:json)?\s*\n(.*?)\n```", t, re.S)
    if m:
        t = m.group(1)
        repairs.append("removed ``` code fence")
    if t.strip() and t.strip()[0] not in "{[":
        k = t.find("{")
        if k > 0:
            t = t[k:]
            repairs.append("dropped text before the first '{'")
    t2 = _strip_trailing_commas(t)
    if t2 != t:
        repairs.append("removed trailing commas")
    try:
        return json.loads(t2), repairs
    except json.JSONDecodeError:
        pass
    try:
        import ast
        py = re.sub(r"\bnull\b", "None", re.sub(r"\btrue\b", "True", re.sub(r"\bfalse\b", "False", t2)))
        obj = ast.literal_eval(py)
        if isinstance(obj, (dict, list)):
            return json.loads(json.dumps(obj, ensure_ascii=False)), repairs + ["parsed as a Python literal (single quotes / None)"]
    except Exception:  # noqa: BLE001
        pass
    ln = text.splitlines()
    ctx = "\n".join(f"{i + 1:5d}| {ln[i][:160]}" for i in range(max(0, first.lineno - 3), min(len(ln), first.lineno + 2)))
    raise DraftError(f"{what} is not valid JSON: {first.msg} at line {first.lineno} column {first.colno}\n{ctx}")


def load_draft_file(path):
    if not os.path.exists(path):
        raise DraftError(f"{path} not found (run init first, or pass --draft)")
    with open(path, encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    if not text.strip():
        raise DraftError(f"{path} is empty")
    obj, rep = lenient_json(text, os.path.basename(path))
    if not isinstance(obj, dict):
        raise DraftError(f"{path} must hold a JSON object (got {type(obj).__name__})")
    return obj, rep


TOP_ALIASES = {"paper_card": "card", "cards": "card", "section_notes": "sections", "section_summaries": "sections",
               "knowledge_points": "knowledge", "knowledge_items": "knowledge", "glossary": "knowledge", "terms": "knowledge",
               "not_reported": "unreported", "uncertainties": "uncertainty", "conflict": "conflicts", "output_contract": "contract"}
CARD_ALIASES = {"limitation": "limitations", "findings": "main_findings", "results": "main_findings", "main_results": "main_findings",
                "key_findings": "main_findings", "question": "research_question", "research_questions": "research_question",
                "problem": "research_question", "dataset": "data", "datasets": "data", "materials": "data", "methods": "method",
                "methodology": "method", "approach": "method", "assumptions": "conditions", "condition": "conditions",
                "settings": "conditions", "setup": "conditions", "future": "future_work", "future_directions": "future_work",
                "contribution": "contributions", "venue": "venue_year", "year": "venue_year", "motivation": "motivation_gap",
                "gap": "motivation_gap", "conclusions": "conclusion", "author": "authors", "paper_title": "title"}
SECTION_ALIASES = {"summary": "key_points", "notes": "key_points", "points": "key_points", "result": "results",
                   "methods": "method", "conclusions": "conclusion", "goal": "purpose", "aim": "purpose", "link": "transition"}


def _section_target(D, sid, heading=None):
    """Draft section id -> outline id (accepts 's4', '3.1', '3.1 Title', a heading text)."""
    if sid in D.sec_by_id:
        return sid
    cand = str(sid or "").strip()
    for x in D.sections:
        num = str(x.get("number") or "")
        full = f"{num} {x.get('title')}".strip()
        if cand and (cand == num or cand == full or cand == x.get("title") or cand.split(" ", 1)[0] == num and num):
            return x["id"]
        if heading and (heading == full or heading == x.get("title")):
            return x["id"]
    return None


def normalise_draft(draft, D):
    """Tolerant reading of a draft: key aliases, card-key typos, sections as a dict, section ids given as heading
    numbers. Returns (draft, warnings); unknown card keys are reported, not silently dropped."""
    import difflib
    warn = []
    d = {}
    for k, v in draft.items():
        k2 = TOP_ALIASES.get(k, k)
        if k2 != k:
            warn.append(f"top-level key '{k}' read as '{k2}'")
        if k2 in d and isinstance(d[k2], dict) and isinstance(v, dict):
            d[k2].update(v)
        else:
            d[k2] = v
    card = d.get("card")
    if card is not None and not isinstance(card, dict):
        warn.append("card is not an object: ignored")
        card = {}
    card2 = {}
    for k, v in (card or {}).items():
        if k in L.CARD_KEYS:
            card2[k] = v
            continue
        k2 = CARD_ALIASES.get(k) or next(iter(difflib.get_close_matches(k, L.CARD_KEYS, 1, 0.8)), None)
        if k2:
            warn.append(f"card.{k} read as card.{k2}")
            card2[k2] = card2.get(k2) if card2.get(k2) and v is None else (v if not card2.get(k2) else as_list(card2[k2]) + as_list(v))
        elif not k.startswith("_"):
            warn.append(f"unknown card field '{k}' ignored (fields: {', '.join(L.CARD_KEYS)})")
    d["card"] = card2
    secs = d.get("sections")
    if isinstance(secs, dict):
        secs = [dict(v, section_id=v.get("section_id", k)) if isinstance(v, dict) else {"section_id": k, "key_points": v}
                for k, v in secs.items()]
        warn.append("sections given as an object: read as a list")
    norm = []
    for s in secs or []:
        if not isinstance(s, dict):
            warn.append(f"section entry ignored (not an object): {str(s)[:60]}")
            continue
        s = dict(s)
        for k, k2 in SECTION_ALIASES.items():
            if k in s and k2 not in s:
                s[k2] = s.pop(k)
        norm.append(s)
    d["sections"] = norm
    kn = d.get("knowledge")
    if isinstance(kn, dict):
        kn = [dict(v, term=v.get("term", k)) if isinstance(v, dict) else {"term": k, "definition": v} for k, v in kn.items()]
        warn.append("knowledge given as an object: read as a list")
    d["knowledge"] = [x for x in (kn or []) if isinstance(x, dict)]
    un = []
    for u in d.get("unreported") or []:
        if isinstance(u, str):
            f, _, r = u.partition(":")
            u = {"field": f.strip(), "reason": r.strip() or "not reported in the paper"}
        if isinstance(u, dict):
            un.append(u)
    d["unreported"] = un
    if d.get("contract") is not None and not isinstance(d["contract"], dict):
        warn.append("contract is not an object: ignored")
        d["contract"] = {}
    return d, warn


def as_list(v):
    return v if isinstance(v, list) else ([] if v is None else [v])


def draft_status(draft, D, fields):
    """What is still missing in the draft (cheap, no anchor resolution)."""
    card = draft.get("card") or {}
    unrep = {str(u.get("field", "")).replace("card.", "") for u in draft.get("unreported") or [] if isinstance(u, dict)
             and u.get("reason") and not str(u.get("reason")).startswith("e.g.")}
    filled = {}
    for s in draft.get("sections") or []:
        t = _section_target(D, s.get("section_id"), s.get("heading"))
        if t and (any(as_items(s.get(f)) for f in L.SECTION_FIELDS + ["key_points"]) or s.get("skip_reason")):
            filled[t] = True
    tops = [x for x in D.sections if (x.get("level") or 1) <= 1 and not x.get("skip")]
    empty = [f"{x['id']} {x.get('number') or ''} {x.get('title')}".replace("  ", " ") for x in tops
             if not filled.get(x["id"]) and not any(filled.get(c["id"]) for c in D.sections if c.get("parent") == x["id"])]
    return {"card_missing": [k for k in L.CARD_REQUIRED if not as_items(card.get(k)) and k not in unrep],
            "sections_empty": empty,
            "knowledge_items": len([k for k in draft.get("knowledge") or [] if isinstance(k, dict) and k.get("term")]),
            "contract_unmapped": [f for f in fields if (draft.get("contract") or {}).get(f) is None]}


def atomic_dump(obj, path):
    tmp = path + ".tmp"
    dump(obj, tmp)
    os.replace(tmp, path)


def merge_fragment(draft, frag, D):
    """Merge a partial draft (any subset of card / sections / knowledge / unreported / uncertainty / conflicts /
    contract) into the full draft. card fields and section fields are replaced, knowledge / lists appended
    (exact duplicates skipped), contract keys updated. Returns (draft, merged, rejected)."""
    frag, warn = normalise_draft(frag, D)
    merged, rejected = list(warn), []
    draft.setdefault("card", {})
    for k, v in (frag.get("card") or {}).items():
        draft["card"][k] = v
        merged.append(f"card.{k}")
    secs = draft.setdefault("sections", [])
    for s in frag.get("sections") or []:
        t = _section_target(D, s.get("section_id"), s.get("heading"))
        if not t:
            rejected.append({"section_id": s.get("section_id"), "reason": "no such section in the outline",
                             "known": [f"{x['id']} {x.get('number') or ''} {x.get('title')}".replace("  ", " ") for x in D.sections][:40]})
            continue
        cur = next((x for x in secs if _section_target(D, x.get("section_id"), x.get("heading")) == t), None)
        if cur is None:
            sec = D.sec_by_id[t]
            cur = {"section_id": t, "heading": f"{sec.get('number') or ''} {sec.get('title')}".strip(), "level": sec.get("level"),
                   "pages": sec["pages"], **{f: None for f in L.SECTION_FIELDS}, "key_points": []}
            secs.append(cur)
        for f, v in s.items():
            if f in ("section_id", "heading", "level", "pages"):
                continue
            cur[f] = v
            merged.append(f"sections.{t}.{f}")
    kn = [k for k in draft.get("knowledge") or [] if isinstance(k, dict) and k.get("term")]
    seen = {json.dumps(k, sort_keys=True, ensure_ascii=False) for k in kn}
    for k in frag.get("knowledge") or []:
        if not k.get("term"):
            rejected.append({"knowledge": k, "reason": "term missing"})
            continue
        j = json.dumps(k, sort_keys=True, ensure_ascii=False)
        if j not in seen:
            kn.append(k)
            seen.add(j)
            merged.append(f"knowledge:{k['term']}")
    draft["knowledge"] = kn
    for lk in ("uncertainty", "conflicts"):
        cur = list(draft.get(lk) or [])
        for x in frag.get(lk) or []:
            if x not in cur:
                cur.append(x)
                merged.append(lk)
        draft[lk] = cur
    if frag.get("unreported"):
        cur = [u for u in draft.get("unreported") or [] if isinstance(u, dict) and not str(u.get("reason", "")).startswith("e.g.")]
        for u in frag["unreported"]:
            cur = [x for x in cur if x.get("field") != u.get("field")] + [u]
            merged.append(f"unreported:{u.get('field')}")
        draft["unreported"] = cur
    if frag.get("contract"):
        draft.setdefault("contract", {}).update(frag["contract"])
        merged += [f"contract.{k}" for k in frag["contract"]]
    return draft, merged, rejected


def cmd_merge(a, quiet=False):
    """notes.py merge part1.json [part2.json ...] | --json '{"card": {...}}'  -> merged into WORK/draft.json.
    A part that is not valid JSON is rejected (listed under `rejected`); the other parts are still merged."""
    state = load_state(a.work)
    D = L.Doc(state["parsed_dir"])
    dp = a.draft or os.path.join(a.work, "draft.json")
    try:
        draft, rep = load_draft_file(dp)
    except DraftError as e:
        bak = os.path.join(os.path.dirname(dp), "draft.bak.json")
        if not (a.parts or a.json):
            print(json.dumps({"error": str(e), "hint": "the draft itself is broken; fix it or restore WORK/draft.bak.json"}, ensure_ascii=False))
            sys.exit(4)
        # parts given: start again from the last good draft (or an empty one) instead of stopping
        try:
            draft, rep = load_draft_file(bak)
            rep = rep + [f"draft.json unreadable ({e}); merged onto draft.bak.json"]
        except (DraftError, OSError):
            draft, rep = {}, [f"draft.json unreadable ({e}); merged onto an empty draft"]
    draft, w0 = normalise_draft(draft, D)
    frags, rejected = [], []
    for p in a.parts or []:
        try:
            frags.append((p, load_draft_file(p)[0]))
        except (DraftError, OSError) as e:
            rejected.append({"file": p, "reason": str(e), "fix": "rewrite this part file and merge/build again"})
    if a.json:
        try:
            frags.append(("--json", lenient_json(a.json, "--json")[0]))
        except DraftError as e:
            rejected.append({"file": "--json", "reason": str(e)})
    if not frags and rejected:
        print(json.dumps({"error": "no part could be read; draft unchanged", "rejected": rejected}, ensure_ascii=False, indent=1))
        sys.exit(4)
    merged = []
    for name, fr in frags:
        if not isinstance(fr, dict):
            rejected.append({"file": name, "reason": "fragment must be a JSON object"})
            continue
        draft, m, r = merge_fragment(draft, fr, D)
        merged += m
        rejected += [dict(x, file=name) for x in r]
    if os.path.exists(dp):
        shutil.copyfile(dp, os.path.join(os.path.dirname(dp), "draft.bak.json"))
    atomic_dump(draft, dp)
    rep_ = {"merged": merged, "rejected": rejected, "repairs": rep + w0,
            "draft_status": draft_status(draft, D, state.get("contract_fields") or []), "next": "notes.py build"}
    if quiet:
        return rep_
    print(json.dumps(rep_, ensure_ascii=False, indent=1))


def cmd_add(a):
    """notes.py add PATH --text T --a ANCHOR [--a ...]   PATH = card.<field> | sections.<id or number>.<field> |
    knowledge (--term, --kind, --definition, --alias) | unreported.<field> (--reason) | uncertainty | conflicts |
    contract.<field> (--value '@card' or JSON). --append adds to a card/section field instead of replacing it."""
    state = load_state(a.work)
    D = L.Doc(state["parsed_dir"])
    item = {"text": a.text, "a": a.a or []}
    p = a.path
    frag = {}
    if p.startswith("card."):
        k = p[5:]
        cur = []
        if a.append:
            try:
                cur = as_list(normalise_draft(load_draft_file(a.draft or os.path.join(a.work, "draft.json"))[0], D)[0]["card"].get(k))
            except DraftError:
                cur = []
        frag = {"card": {k: cur + [item] if a.append else item}}
    elif p.startswith("sections."):
        rest = p[len("sections."):]
        sid, _, f = rest.rpartition(".")
        if not sid:
            print(json.dumps({"error": "use sections.<id>.<field>, e.g. sections.s3.results"}))
            sys.exit(2)
        t = _section_target(D, sid)
        cur = []
        if a.append and t:
            try:
                dd = normalise_draft(load_draft_file(a.draft or os.path.join(a.work, "draft.json"))[0], D)[0]
                cur = as_list(next((s.get(f) for s in dd["sections"] if _section_target(D, s.get("section_id")) == t), None))
            except DraftError:
                cur = []
        frag = {"sections": [{"section_id": t or sid, f: cur + [item] if a.append else ([item] if f == "key_points" else item)}]}
    elif p == "knowledge":
        frag = {"knowledge": [{"term": a.term, "aliases": a.alias or [], "kind": a.kind, "definition": a.definition or a.text,
                               "section_id": a.section, "a": a.a or []}]}
    elif p.startswith("unreported."):
        frag = {"unreported": [{"field": p[len("unreported."):], "reason": a.reason or a.text}]}
    elif p in ("uncertainty", "conflicts"):
        frag = {p: [a.text if not a.a else item]}
    elif p.startswith("contract."):
        v = a.value
        if v is not None and not v.startswith("@"):
            try:
                v = json.loads(v)
            except json.JSONDecodeError:
                pass
        frag = {"contract": {p[len("contract."):]: v if v is not None else item}}
    else:
        print(json.dumps({"error": f"unknown path '{p}'", "paths": ["card.<field>", "sections.<id>.<field>", "knowledge",
                                                                    "unreported.<field>", "uncertainty", "conflicts", "contract.<field>"]}))
        sys.exit(2)
    a.parts, a.json = [], json.dumps(frag, ensure_ascii=False)
    cmd_merge(a)


def build_failed(work, msg, code, extra=None):
    """A build that cannot run never touches OUT/result.json (the last good result stays valid)."""
    err = {"error": msg, "result_json_untouched": True, "at": now(), **(extra or {}),
           "hint": "fix the draft (or write it in parts: `notes.py merge part.json`, `notes.py add card.data --text .. --a ..`), "
                   "check with `notes.py build --dry-run`, then build again"}
    try:
        dump(err, os.path.join(work, "build_error.json"))
    except OSError:
        pass
    print(json.dumps(err, ensure_ascii=False, indent=1))
    sys.exit(code)


def cmd_build(a):
    work = a.work
    state = load_state(work)
    a.merge_report = None
    dp = a.draft or os.path.join(work, "draft.json")
    if getattr(a, "parts", None):  # build part1.json part2.json = merge + build in one call
        dp_merge = dp
        if getattr(a, "dry_run", False) and os.path.exists(dp):
            import tempfile
            tf = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
            tf.close()
            shutil.copyfile(dp, tf.name)
            dp_merge = tf.name
        try:
            mr = cmd_merge(argparse.Namespace(work=work, draft=dp_merge, parts=a.parts, json=None), quiet=True)
            a.merge_report = {k: mr[k] for k in ("merged", "rejected") if mr.get(k)}
            raw, repairs = load_draft_file(dp_merge)
        except DraftError as e:
            build_failed(work, str(e), 4)
        finally:
            if dp_merge != dp and os.path.exists(dp_merge):
                os.unlink(dp_merge)
    else:
        try:
            raw, repairs = load_draft_file(dp)
        except DraftError as e:
            build_failed(work, str(e), 4)
    try:
        return _build(a, state, raw, repairs)
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001
        import traceback
        build_failed(work, f"build crashed: {type(e).__name__}: {e}", 5, {"trace": traceback.format_exc()[-1500:]})


def _build(a, state, raw, repairs):
    t0 = time.time()
    work = a.work
    out = a.out or state["out"]
    D = L.Doc(state["parsed_dir"])
    draft, norm_warn = normalise_draft(raw, D)
    supp = {}
    for s_ in state.get("supplements") or []:
        if os.path.exists(os.path.join(s_["parsed_dir"], "doc.json")):
            supp[s_["key"]] = L.Doc(s_["parsed_dir"])
    ck = Checker(D, supp)
    # card
    card = {}
    for k in L.CARD_KEYS:
        items = as_items((draft.get("card") or {}).get(k))
        card[k] = [ck.check_item(it, f"card.{k}") for it in items if (it.get("text") or "").strip()]
    auto_filled = []
    if not card.get("title"):
        tb = next((b for b in D.d.get("blocks") or [] if b.get("role") == "title" and (b.get("text") or "").strip()), None)
        if tb:
            t_ = re.sub(r"\s+", " ", tb["text"]).strip()
            card["title"] = [ck.check_item({"text": t_, "a": [f"{tb['id']}: {t_[:150]}"]}, "card.title")]
            auto_filled.append("card.title")
    # sections: aligned to the paper's outline; unknown ids reported
    by_id = {}
    unknown = []
    for s in draft.get("sections") or []:
        sid = _section_target(D, s.get("section_id"), s.get("heading"))  # tolerates heading numbers / titles
        if not sid:
            if any(as_items(s.get(f)) for f in L.SECTION_FIELDS + ["key_points"]):
                unknown.append(s.get("section_id"))
            continue
        if sid in by_id:  # the same section twice: keep both sets of notes
            for f in L.SECTION_FIELDS + ["key_points"]:
                if s.get(f):
                    by_id[sid] = dict(by_id[sid], **{f: as_list(by_id[sid].get(f)) + as_list(s.get(f))})
            continue
        by_id[sid] = s
    sec_notes = []
    for sec in D.sections:
        if sec.get("skip"):
            continue
        s = by_id.get(sec["id"], {})
        rec = {"section_id": sec["id"], "number": sec.get("number"), "heading": f"{sec.get('number') or ''} {sec.get('title')}".strip(),
               "level": sec.get("level"), "parent": sec.get("parent"), "pages": sec["pages"],
               "block_span": [sec["first_block"], sec["last_block"]], "appendix": bool(sec.get("appendix"))}
        for f in L.SECTION_FIELDS + ["key_points"]:
            rec[f] = [ck.check_item(it, f"sections.{sec['id']}.{f}", sec["id"]) for it in as_items(s.get(f))
                      if (it.get("text") or "").strip()]
        if s.get("skip_reason"):
            rec["skip_reason"] = s["skip_reason"]
        sec_notes.append(rec)
    kps, merges, kconf = merge_knowledge(draft.get("knowledge") or [], D)
    kp_out = []
    for i, k in enumerate(kps):
        c = ck.check_item(k, f"knowledge[{i}]:{k.get('term')}", k.get("section_id") if k.get("section_id") in D.sec_by_id else None)
        flag = {"expansion_not_printed": "abbreviation expansion not printed in the paper",
                "expansion_mismatch": (k.get("abbreviation") or {}).get("note")}.get((k.get("abbreviation") or {}).get("status"))
        if k.get("definition_conflict"):
            flag = (flag + "; " if flag else "") + "definitions disagree (see definition_conflict)"
        if any(x.get("kind") == "abbreviation_collision" and k.get("term") in x["terms"] for x in kconf):
            flag = (flag + "; " if flag else "") + "abbreviation shared with another entry that has a different long form"
        if flag:
            c.setdefault("warn", flag)
            c["check"].setdefault("review", []).append(flag)
            if c["check"]["status"] == "verified":
                c["check"]["status"] = "needs_review"
                rec = next((r for r in reversed(ck.records) if r["where"].startswith(f"knowledge[{i}]:")), None)
                if rec:
                    rec["status"] = "needs_review"
                    rec["review"].append(flag)
        kp_out.append(c)
    # Preserve claims with a usable source location even if a numeric check or another anchor fails.
    dropped = []

    def _keep(lst, where, keep_unanchored=False):
        out_ = []
        for it in lst:
            ch = it.get("check") or {}
            # an unanchored glossary entry stays visible (marked failed) so collisions/conflicts keep both sides
            if (ch.get("status") == "failed" and not any(r.get("ok") for r in it["anchors"])
                    and not (keep_unanchored and set(ch.get("problems") or []) <= {"no_anchor"})):
                dropped.append(dict(it, where=where))
            else:
                out_.append(it)
        return out_
    for k in list(card):
        card[k] = _keep(card[k], f"card.{k}")
    for rec in sec_notes:
        for f in L.SECTION_FIELDS + ["key_points"]:
            rec[f] = _keep(rec[f], f"sections.{rec['section_id']}.{f}")
    kp_out = _keep(kp_out, "knowledge", keep_unanchored=True)
    unreported = [u for u in draft.get("unreported") or [] if u.get("reason") and not str(u.get("reason")).startswith("e.g.")]
    unrep_fields = {str(u.get("field")).replace("card.", "") for u in unreported}
    card_missing = [k for k in L.CARD_REQUIRED if not card.get(k) and k not in unrep_fields]
    for k in card_missing:  # recorded honestly: the notes lack it - not a claim that the paper lacks it
        unreported.append({"field": f"card.{k}", "auto": True,
                           "reason": "no verified note in these notes (not filled, or its note failed verification); "
                                     "this does not claim the paper omits it - human check needed"})
    # coverage: every top-level non-reference section needs at least one note or a skip_reason
    required = [s for s in sec_notes if (s.get("level") or 1) <= 1]
    covered = [s for s in required if any(s.get(f) for f in L.SECTION_FIELDS + ["key_points"]) or s.get("skip_reason")]
    # children notes count for the parent
    for s in required:
        if s not in covered and any(any(c.get(f) for f in L.SECTION_FIELDS + ["key_points"])
                                    for c in sec_notes if c.get("parent") == s["section_id"]):
            covered.append(s)
    missing = [f"{s['section_id']} {s['heading']}" for s in required if s not in covered]
    # pages whose content is only in an image: read = some anchor cites that page's image region or figure
    vis = []
    for v in visual_pages(D):
        read = any(e.get("page") == v["page"] and not e.get("source") and (e.get("kind") in ("image", "figure") or e.get("figure"))
                   for e in ck.evidence)
        vis.append(dict(v, read=read))
    recs = ck.records
    nv = sum(r["status"] == "verified" for r in recs)
    nr = sum(r["status"] == "needs_review" for r in recs)
    nf = sum(r["status"] == "failed" for r in recs)
    verification = {
        "n_items": len(recs), "n_verified": nv, "n_needs_review": nr, "n_failed": nf,
        "section_coverage": {"required": len(required), "covered": len(covered), "missing": missing},
        "unknown_section_ids_in_draft": unknown, "card_missing": card_missing,
        "knowledge_merges": merges, "knowledge_conflicts": kconf, "outline_fixes": D.outline_fixes,
        "visual_pages": vis, "visual_coverage": {"pages": len(vis), "read": sum(v["read"] for v in vis)},
        "draft_repairs": repairs + norm_warn,
        "supplements": [{"key": k, "file": os.path.basename((x.d.get("meta") or {}).get("source_file") or "")} for k, x in supp.items()],
        "failed_items": [r for r in recs if r["status"] == "failed"][:60],
        "dropped_items": [{x: it.get(x) for x in ("where", "label", "text", "a", "anchors", "check") if it.get(x) is not None}
                          for it in dropped][:60],
        "auto_filled": auto_filled,
        "review_items": [r for r in recs if r["status"] == "needs_review"][:60],
        "machine_checkable": ["anchor exists", "quote verbatim in cited block (or relocated)", "anchor page/section",
                              "numbers in note appear in anchored text", "section coverage/order", "card fields present",
                              "duplicate knowledge points merged", "abbreviation expansion printed"],
        "human_review": ["note is a faithful paraphrase of its quote", "figure/page-image readings",
                         "fuzzy quotes", "completeness of limitations/conditions"],
    }
    prev = {}
    rp = os.path.join(out, "result.json")
    if os.path.exists(rp):
        try:
            prev = previous_result(rp)
        except Exception:  # noqa: BLE001
            prev = {}
    if not recs and not getattr(a, "dry_run", False):
        prev_stage = (prev.get("run_status") or {}).get("stage")
        pv = prev.get("verification") or {}
        prev_items = pv.get("n_items", 0)
        prev_verified = pv.get("n_verified", 0)
        if prev.get("status") == "success" or (prev_stage == "build" and prev_items > 0):
            prev_copy = os.path.join(work, "result.prev.json")
            try:
                shutil.copyfile(rp, prev_copy)
            except OSError:
                pass
            reg_msg = (f"this build verifies 0 items, the previous one {prev_verified}: "
                       f"refusing to overwrite valid result.json; previous result saved as {prev_copy}")
            build_failed(work, "draft produced 0 valid note items; refusing to overwrite existing result.json", 4,
                         {"previous_status": prev.get("status"), "previous_items": prev_items,
                          "regression_warning": reg_msg})
    unread_vis = [v["page"] for v in vis if not v["read"]]
    warns = []
    if nf:
        warns.append(f"{nf} item(s) failed verification. See the inline warnings and verification.json.")
    if card_missing:
        warns.append(f"card fields recorded as not filled: {card_missing}")
    if missing:
        warns.append(f"{len(missing)} top-level section(s) without notes: {missing[:6]}")
    if unknown:
        warns.append(f"draft section ids not in the outline (ignored): {unknown}")
    if unread_vis:
        warns.append(f"image-only content on pages {unread_vis} not read (listed in uncertainty)")
    status = "success"
    res = {"case_id": state.get("case_id")}
    RESERVED_CORE = {"case_id", "status", "run_status", "verification", "sources", "outputs", "change_log"}
    for f in state["contract_fields"]:
        if f not in RESERVED_CORE:  # a contract that lists case_id/core keeps the real values (0 included)
            res[f] = None
    res.update({
        "status": status,
        "run_status": {"stage": "build", "reason": None, "warnings": warns,
                       "seconds": round(time.time() - t0, 2), "tool": L.VERSION,
                       "human_takeover": "see verification.failed_items / review_items (where = field path; anchors carry page+bbox)"},
        "notes": {"paper_card": card, "section_notes": sec_notes, "knowledge_points": kp_out,
                  "outline": [{k: s.get(k) for k in ("id", "level", "number", "title", "parent", "pages", "appendix", "pseudo")}
                              for s in D.sections]},
        "evidence": ck.evidence,
        "unreported": unreported,
        "uncertainty": list(draft.get("uncertainty") or []) + [
            {"auto": True, "page": v["page"], "detail": f"page {v['page']}: {v['reason']}; its image content was not read, "
                                                       "so results drawn only in that image are missing from these notes"}
            for v in vis if not v["read"]] + ([f"input files named in case.json but not found: {state['missing_inputs']}"]
                                               if state.get("missing_inputs") else []),
        "conflicts": list(draft.get("conflicts") or []) + [dict(c, auto=True) for c in kconf if c["kind"] == "definition_conflict"],
        "verification": verification,
        "sources": state["sources"],
        "outputs": {"notes_md": "notes.md", "paper_card_json": "paper_card.json", "paper_card_csv": "paper_card.csv",
                    "knowledge_jsonl": "knowledge_points.jsonl", "verification": "verification.json"},
        "change_log": (prev.get("change_log") or []) + [{"at": now(), "step": "build",
                                                          "detail": f"{len(recs)} items: {nv} verified, {nr} review, {nf} failed"}],
    })
    md_path = os.path.join(out, "notes.md")
    # contract fields
    cmap = dict(draft.get("contract") or {})
    cspec = state.get("contract_spec") or {}
    contract_gaps = []
    for f in state["contract_fields"]:
        sp = cspec.get(f) or {}
        is_req = sp.get("_required", True)
        v = cmap.get(f)
        if f == "case_id":
            if v is not None and state.get("case_id") is None:
                res["case_id"] = v
            continue
        if f in RESERVED_CORE:
            continue
        if v is None and f in ("notes", "evidence", "unreported", "uncertainty", "conflicts"):
            res[f], cg = validate_and_coerce_contract(res.get(f), sp, f"contract.{f}")
            contract_gaps.extend(cg)
            continue
        if v is None:
            ref = next((r for pat, r in AUTO_MAP if re.search(pat, f, re.I)), None)
            if ref:
                v = ref
                res["change_log"].append({"at": now(), "step": "contract_auto_map", "detail": f"{f} <- {ref}"})
        val, is_ref = resolve_ref(v, res, md_path)
        if is_ref:
            res[f], cg = validate_and_coerce_contract(val, sp, f"contract.{f}")
            contract_gaps.extend(cg)
        elif v is not None:
            walked = walk_anchors(v, ck, f"contract.{f}", dropped)
            res[f], cg = validate_and_coerce_contract(walked, sp, f"contract.{f}")
            contract_gaps.extend(cg)
        if res.get(f) in (None, [], {}) and is_req:
            card_ref = v[6:] if isinstance(v, str) and v.startswith("@card.") else None
            declared = any(str(u.get("field")).replace("card.", "") in (f, card_ref) for u in res["unreported"])
            if is_ref:  # mapped to the notes, but that part is empty: say so, do not block
                if not declared:
                    res["unreported"].append({"field": f, "auto": True, "reason": f"mapped to {v}, which has no verified note"})
                warns.append(f"contract field '{f}' is empty ({v})")
            elif not declared:
                res["unreported"].append({"field": f, "reason": "contract field not filled by the agent (no mapping)"})
                contract_gaps.append({"field": f, "reason": "required contract field not filled"})
    # re-count after contract literals added records
    res["verification"]["n_items"] = len(ck.records)
    res["verification"]["n_failed"] = sum(r["status"] == "failed" for r in ck.records)
    res["verification"]["n_verified"] = sum(r["status"] == "verified" for r in ck.records)
    res["verification"]["n_needs_review"] = sum(r["status"] == "needs_review" for r in ck.records)
    res["verification"]["dropped_items"] = dropped
    res["verification"]["failed_items"] = [r for r in ck.records if r["status"] == "failed"][:60]
    res["verification"]["review_items"] = [r for r in ck.records if r["status"] == "needs_review"][:60]
    warns += [f"contract {g['field']}: {g['reason']}" for g in contract_gaps]
    res["verification"]["contract_gaps"] = contract_gaps
    weak_core = [k for k in L.CARD_REQUIRED if card.get(k) and all((it.get("check") or {}).get("status") == "needs_review" for it in card[k])]
    if weak_core:
        warns.append(f"core card fields have only needs_review evidence (check metric, direction, and comparison): {weak_core}")
    substantive = any(k not in ("title", "authors") and v for k, v in card.items()) or any(
        s[f] for s in sec_notes for f in L.SECTION_FIELDS + ["key_points"]) or any(
        it.get("definition") and any(r.get("ok") for r in it["anchors"]) for it in kp_out)
    literal_answer = any(f not in RESERVED_CORE | {"notes", "evidence", "unreported", "uncertainty", "conflicts"}
                         and cmap.get(f) is not None and not resolve_ref(cmap[f], res, md_path)[1]
                         and res.get(f) not in (None, "", [], {}) for f in state["contract_fields"])
    if not (substantive or literal_answer):
        res["status"] = "partial" if recs else "failed"
        res["run_status"]["reason"] = "no substantive notes were produced"
    elif warns:
        res["run_status"]["reason"] = "completed with warnings (see verification.json)"
    v = res["verification"]
    res["run_status"]["n_needs_review"] = v["n_needs_review"]
    summary = {"status": res["status"], "reason": res["run_status"]["reason"], "warnings": warns,
               **({"merge": a.merge_report} if getattr(a, "merge_report", None) else {}),
               "items": v["n_items"], "verified": v["n_verified"],
               "needs_review": v["n_needs_review"], "failed": v["n_failed"],
               "uncovered_sections": v["section_coverage"]["missing"], "card_missing": card_missing,
               "unknown_section_ids": unknown,
               "fix_these": [{"where": r["where"], "problems": r["problems"]} for r in v["failed_items"][:25]],
               "next": ("optional: fix `fix_these` / `contract_gaps` in one part file and run `N build part_fix.json` once; otherwise done"
                        if (v["n_failed"] or contract_gaps) else "done"),
               "review": [{"where": r["where"], "review": r["review"][:2]} for r in v["review_items"][:12]],
               "contract": {f: (type(res.get(f)).__name__ if res.get(f) is not None else None) for f in state["contract_fields"]},
               **({"contract_gaps": contract_gaps} if contract_gaps else {}),
               **({"draft_repairs": v["draft_repairs"]} if v["draft_repairs"] else {}),
               **({"visual_pages_unread": unread_vis} if unread_vis else {}),
               **({"knowledge_conflicts": kconf} if kconf else {})}
    if getattr(a, "dry_run", False):
        print(json.dumps(dict(summary, dry_run=True, written=None), ensure_ascii=False, indent=1))
        return
    # regression guard: keep the previous result and say so when this build is clearly worse
    if prev:
        try:
            shutil.copyfile(rp, os.path.join(work, "result.prev.json"))
        except OSError:
            pass
        pv = prev.get("verification") or {}
        if pv.get("n_verified", 0) >= 6 and v["n_verified"] < 0.5 * pv["n_verified"]:
            summary["regression_warning"] = (f"this build verifies {v['n_verified']} items, the previous one {pv['n_verified']}: "
                                             f"was part of the draft lost? previous result saved as {os.path.join(work, 'result.prev.json')}")
    with open(md_path, "w", encoding="utf-8") as fh:
        fh.write(render_md(res, D, state))
    dump(card, os.path.join(out, "paper_card.json"))
    with open(os.path.join(out, "paper_card.csv"), "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["case_id", "source_sha256"] + L.CARD_KEYS)
        w.writerow([res["case_id"], state["sources"][0]["sha256"]] +
                   [" | ".join(f"{it.get('text')} [{', '.join(str(r.get('block_id') or r.get('table') or r.get('figure') or r.get('page')) for r in it['anchors'] if r.get('ok'))}]"
                               for it in card.get(k) or []) or "NOT REPORTED" for k in L.CARD_KEYS])
    with open(os.path.join(out, "knowledge_points.jsonl"), "w", encoding="utf-8") as fh:
        for k in kp_out:
            fh.write(json.dumps({x: k.get(x) for x in ("term", "aliases", "kind", "definition", "other_definitions",
                                                      "definition_conflict", "abbreviation", "section_id", "anchors", "check")
                                 if k.get(x) is not None}, ensure_ascii=False) + "\n")
    write_result(res, state["contract_fields"], rp, res["verification"])
    summary["outputs"] = [os.path.join(out, x) for x in ("result.json", "notes.md", "paper_card.csv",
                                                         "knowledge_points.jsonl", "verification.json")]
    print(json.dumps(summary, ensure_ascii=False, indent=1))


# ------------------------------------------------------------------ find
def cmd_find(a):
    state = load_state(a.work)
    pre = ""
    if a.source and a.source.upper() != "PRIMARY":
        sp = next((x for x in state.get("supplements") or [] if x["key"] == a.source.upper()), None)
        if not sp:
            print(json.dumps({"error": f"no source {a.source}", "known": [x["key"] for x in state.get("supplements") or []]}))
            sys.exit(2)
        D, pre = L.Doc(sp["parsed_dir"]), sp["key"] + "::"
    else:
        D = L.Doc(state["parsed_dir"])
    q = []
    for t in re.findall(r"\w+", L.nfkc(a.query).lower()):
        if len(t) > 1:
            q.append(t)
        if re.fullmatch(r"[一-鿿]{4,}", t):  # long Chinese run: also score by its 2-char pieces
            q += [t[i:i + 2] for i in range(0, len(t) - 1, 2)]
    hits = []
    secs = None
    if a.section:
        secs = {s["id"] for s in D.sections if str(s.get("number")) == a.section or s["id"] == a.section
                or str(s.get("number", "")).startswith(a.section + ".")}
    for bid in D.order:
        b = D.blocks[bid]
        if secs is not None and b.get("section_id") not in secs:
            continue
        if b.get("role") in ("reference",):
            continue
        for sent in L.split_sentences(b.get("text") or ""):
            low = L.nfkc(sent).lower()
            sc = sum(1 for t in q if t in low)
            if sc:
                hits.append((sc, bid, sent))
    hits.sort(key=lambda x: -x[0])
    for sc, bid, sent in hits[:a.top]:
        s = D.sec_by_id.get(D.blocks[bid].get("section_id"), {})
        ln = D.blocks[bid].get("line_start")
        print(json.dumps({"anchor": f"{pre}{bid}: {sent[:200]}", "section": s.get("path"), "score": sc,
                          **({"lines": [ln, D.blocks[bid].get("line_end")]} if ln is not None else {})}, ensure_ascii=False))
    if not hits:
        print(json.dumps({"hits": 0, "hint": "try other words, --section, or read WORK/digest.md"}))


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("init")
    p.add_argument("--case", default="/input/case.json")
    p.add_argument("--out", default="/app/output")
    p.add_argument("--work", default="/app/work")
    p.add_argument("--pdf", nargs="*", default=[])
    p.add_argument("--input", nargs="*", default=[], help="extra input files (.pdf/.md/.txt/.docx)")
    p.add_argument("--primary", default=None, help="file name/path of the primary paper (overrides role detection)")
    p.add_argument("--pages", default=None)
    p.add_argument("--password", default=None)
    p.add_argument("--full-digest", action="store_true")
    p.add_argument("--force", action="store_true", help="overwrite an existing draft.json")
    p = sub.add_parser("build", help="[part.json ...] merge parts (optional), check every note, write OUT/result.json")
    p.add_argument("parts", nargs="*")
    p.add_argument("--work", default="/app/work")
    p.add_argument("--out", default=None)
    p.add_argument("--draft", default=None)
    p.add_argument("--dry-run", action="store_true", help="check the draft and print the report; write nothing")
    p = sub.add_parser("merge", help="merge partial draft files (or --json) into WORK/draft.json")
    p.add_argument("parts", nargs="*")
    p.add_argument("--json", default=None)
    p.add_argument("--work", default="/app/work")
    p.add_argument("--draft", default=None)
    p = sub.add_parser("add", help="add/replace one note: add card.data --text .. --a 'p3-b2: ..'")
    p.add_argument("path")
    p.add_argument("--text", default=None)
    p.add_argument("--a", action="append", default=[], help="anchor (repeatable)")
    p.add_argument("--append", action="store_true")
    p.add_argument("--term", default=None)
    p.add_argument("--kind", default=None)
    p.add_argument("--definition", default=None)
    p.add_argument("--alias", action="append", default=[])
    p.add_argument("--section", default=None)
    p.add_argument("--reason", default=None)
    p.add_argument("--value", default=None)
    p.add_argument("--work", default="/app/work")
    p.add_argument("--draft", default=None)
    p = sub.add_parser("find")
    p.add_argument("query")
    p.add_argument("--work", default="/app/work")
    p.add_argument("--section", default=None)
    p.add_argument("--source", default=None, help="S1, S2 ... to search a supplement")
    p.add_argument("--top", type=int, default=6)
    a = ap.parse_args()
    {"init": cmd_init, "build": cmd_build, "find": cmd_find, "merge": cmd_merge, "add": cmd_add}[a.cmd](a)


if __name__ == "__main__":
    main()
