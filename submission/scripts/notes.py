#!/usr/bin/env python3
"""paper-notes: section-aligned, field-structured, anchor-verified reading notes for a paper PDF.

    python notes.py init  [--case /input/case.json] [--out /app/output] [--work /app/work] [--pdf X.pdf]
                          [--pages 1-12] [--password PW] [--full-digest]
    python notes.py build [--draft /app/work/draft.json] [--out /app/output]
    python notes.py find  "query words" [--section 3.2] [--top 5]       (search, prints anchors ready to paste)

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
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def load_state(work):
    p = os.path.join(work, STATE)
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
CONTRACT_KEYS = ("output_contract", "outputs_contract", "output_schema", "required_outputs", "output_fields", "outputs")


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


def contract_fields(c):
    if c is None:
        return []
    if isinstance(c, dict):
        for k in ("fields", "required", "required_fields", "properties"):
            if k in c:
                return contract_fields(c[k])
        return list(c.keys())
    if isinstance(c, list):
        out = []
        for it in c:
            if isinstance(it, str):
                out.append(it)
            elif isinstance(it, dict):
                n = it.get("name") or it.get("field") or it.get("key") or it.get("id")
                if n:
                    out.append(n)
        return out
    return [c] if isinstance(c, str) else []


def pdf_strings(obj, acc):
    if isinstance(obj, dict):
        for v in obj.values():
            pdf_strings(v, acc)
    elif isinstance(obj, list):
        for v in obj:
            pdf_strings(v, acc)
    elif isinstance(obj, str) and obj.lower().endswith(".pdf"):
        acc.append(obj)
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
def digest_md(D, full, max_para=1400):
    d = D.d
    lines = []
    titles = [b for b in d["blocks"] if b.get("role") == "title"]
    auth = [b for b in d["blocks"] if b.get("role") == "author_affiliation"]
    lines.append(f"# DIGEST  {d['meta'].get('source_file', '')}")
    lines.append("Anchors: [p3-b12] = page 3 block 12 (cite as 'p3-b12: verbatim words'). "
                 "Sections follow the paper's own order. Tables/figures/equations listed under the section that cites them.")
    for b in titles:
        lines.append(f"[{b['id']}] TITLE: {b['text']}")
    for b in auth[:4]:
        lines.append(f"[{b['id']}] AUTHORS: {b['text'][:300]}")
    pre = [b for b in d["blocks"] if not b.get("section_id") and b.get("role") in ("body", "abstract")]
    for b in pre[:6]:
        lines.append(f"[{b['id']}] {b['text']}")
    budget_left = None if full else 45000
    for s in D.sections:
        hdr = "#" * min(1 + (s.get("level") or 1), 4)
        tag = " [REFERENCES - skip]" if s.get("skip") else (" [APPENDIX]" if s.get("appendix") else "")
        lines.append(f"\n{hdr} [{s['id']}] {s.get('number') or ''} {s.get('title')}{tag}  "
                     f"(pp. {s['pages'][0]}-{s['pages'][1]}; {s['first_block']}..{s['last_block']}; {s['n_chars']} chars)")
        if s.get("page_image"):
            pinfo = next((p for p in d.get("pages", []) if p["page"] == s["pages"][0]), {})
            dpi = pinfo.get("page_image_dpi") or 150
            lines.append(f"[p{s['pages'][0]} IMAGE-ONLY] {os.path.join(D.dir, s['page_image'])} ({dpi} dpi: PDF points = pixels*72/{dpi}); "
                         f"{len(pinfo.get('image_regions') or [])} ink regions in doc.json pages[].image_regions. "
                         f"Look at the image; cite what you read as 'p{s['pages'][0]}@x0,y0,x1,y1: text as read' (bbox in PDF points). "
                         f"Optional crop: python SKILL_DIR/scripts/crop_region.py {D.dir} --page {s['pages'][0]} --region p{s['pages'][0]}-r5")
            for r in (pinfo.get("image_regions") or [])[:60]:
                lines.append(f"  region {r['id']} bbox {r['bbox']}")
        extras = s.get("tables", []) + s.get("figures", []) + s.get("equations", [])
        if extras:
            lines.append("  contains: " + "; ".join(extras))
        if s.get("skip"):
            continue
        n_after_budget = 0
        for bid in s["block_ids"]:
            b = D.blocks[bid]
            role = b.get("role")
            if role in ("heading", "table", "reference"):
                continue
            txt = b.get("text") or ""
            if budget_left is not None and budget_left <= 0:
                # over budget: first sentence of the first 2 body paragraphs per section, captions kept short
                if role == "body":
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
            pre_tag = {"caption": "CAPTION ", "equation": "EQ ", "footnote": "FOOTNOTE "}.get(role, "")
            if role == "equation" and b.get("unicode_math"):
                txt = b["unicode_math"]
            lines.append(f"[{bid}] {pre_tag}{txt}")
    if budget_left is not None and budget_left <= 0:
        lines.append("\n[digest shortened after 45k chars: later body blocks show first sentence only; "
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


def cmd_init(a):
    t0 = time.time()
    os.makedirs(a.out, exist_ok=True)
    os.makedirs(a.work, exist_ok=True)
    case, case_err = {}, None
    if os.path.exists(a.case):
        try:
            case = load(a.case)
        except Exception as e:  # noqa: BLE001
            case_err = f"case.json unreadable: {e}"
    else:
        case_err = f"{a.case} not found"
    case_dir = os.path.dirname(os.path.abspath(a.case))
    task = next((p for p in (os.path.join(case_dir, "task.md"), "/input/task.md") if os.path.exists(p)), None)
    bases = [case_dir, "/input", os.getcwd()]
    pdfs = []
    for s in pdf_strings(case, []) + list(a.pdf or []):
        r = resolve_path(s, bases)
        if r and r not in pdfs:
            pdfs.append(r)
    if not pdfs:
        for b in (case_dir, "/input"):
            for p in sorted(glob.glob(os.path.join(b, "**", "*.pdf"), recursive=True)):
                if p not in pdfs:
                    pdfs.append(p)
    fields = contract_fields(find_contract(case))
    case_id = case.get("case_id") or case.get("id") or os.environ.get("CASE_ID")
    import parse_pdf  # noqa: E402
    sources, summary_docs = [], []
    for p in pdfs:
        stem = os.path.splitext(os.path.basename(p))[0]
        pdir = os.path.join(a.out, "parsed", stem)
        try:
            r = parse_pdf.parse(p, pdir, password=a.password, pages=parse_pdf.parse_pages(a.pages),
                                preview=False, cache_dir=os.path.join(a.work, "parse_cache"))
        except Exception as e:  # noqa: BLE001
            r = {"status": "failed", "error": f"parser crashed: {e}"}
        src = {"file": p, "sha256": sha256(p), "parsed_dir": pdir, "parse_status": r.get("status"),
               "parse_error": r.get("error"), "page_count": (r.get("meta") or {}).get("page_count"),
               "pages_parsed": r.get("pages_parsed"), "pages_not_parsed": r.get("pages_not_parsed"),
               "unresolved_pages": r.get("unresolved_pages", []), "ocr_pages": r.get("ocr_pages", []),
               "warnings": (r.get("warnings") or [])[:15]}
        sources.append(src)
        if r.get("status") != "failed" and os.path.exists(os.path.join(pdir, "doc.json")):
            D = L.Doc(pdir)
            summary_docs.append((src, D))
    # one primary document (first parsed); others listed as extra sources
    state = {"version": L.VERSION, "case": os.path.abspath(a.case), "case_id": case_id, "task": task,
             "contract_fields": fields, "sources": sources, "out": os.path.abspath(a.out),
             "work": os.path.abspath(a.work), "init_at": now()}
    outline = []
    if summary_docs:
        src, D = summary_docs[0]
        state["parsed_dir"] = src["parsed_dir"]
        with open(os.path.join(a.work, "digest.md"), "w", encoding="utf-8") as fh:
            fh.write(digest_md(D, a.full_digest))
        cues = D.cue_sentences()
        dump(cues, os.path.join(a.work, "cues.json"))
        outline = [{k: s.get(k) for k in ("id", "level", "number", "title", "parent", "pages", "first_block",
                                         "last_block", "n_words", "tables", "figures", "equations", "skip",
                                         "appendix", "pseudo", "rule")} for s in D.sections]
        dump({"sections": outline, "fixes": D.outline_fixes}, os.path.join(a.work, "outline.json"))
        draft_path = os.path.join(a.work, "draft.json")
        if not os.path.exists(draft_path) or a.force:
            dump(draft_template(D, fields), draft_path)
    dump(state, os.path.join(a.work, STATE))
    # valid partial result right away
    result = {"case_id": case_id}
    for f in fields:
        result.setdefault(f, None)
    failed = not summary_docs
    reason = None
    if not pdfs:
        reason = "no PDF found in case.json or the input directory"
    elif failed:
        reason = "; ".join(f"{os.path.basename(s['file'])}: {s['parse_error']}" for s in sources)
    result.update({
        "status": "failed" if failed else "partial",
        "run_status": {"stage": "init", "reason": reason or "notes not written yet", "case_error": case_err,
                       "seconds": round(time.time() - t0, 2), "tool": L.VERSION},
        "notes": None, "evidence": [], "sources": sources, "unreported": [], "uncertainty": [], "conflicts": [],
        "change_log": [{"at": now(), "step": "init", "detail": f"parsed {len(pdfs)} PDF(s)"}],
    })
    if failed and pdfs:
        result["unreported"] = [{"field": f, "reason": reason} for f in fields]
    dump(result, os.path.join(a.out, "result.json"))
    out = {"case_id": case_id, "contract_fields": fields, "task": task, "pdfs": pdfs,
           "parse_status": [s["parse_status"] for s in sources], "parse_error": [s["parse_error"] for s in sources if s["parse_error"]],
           "unresolved_pages": [s["unresolved_pages"] for s in sources],
           "digest": os.path.join(a.work, "digest.md"), "cues": os.path.join(a.work, "cues.json"),
           "draft": os.path.join(a.work, "draft.json"), "result": os.path.join(a.out, "result.json"),
           "outline": [f"{s['id']} L{s['level']} {s.get('number') or ''} {s['title']} pp{s['pages'][0]}-{s['pages'][1]}"
                       + (" [skip]" if s.get("skip") else "") + (" [appendix]" if s.get("appendix") else "")
                       for s in outline]}
    if len(summary_docs) > 1:
        out["note"] = "several PDFs: digest/draft built for the first; run init --pdf OTHER.pdf --work OTHER_WORK for others"
    print(json.dumps(out, ensure_ascii=False, indent=1))


# ------------------------------------------------------------------ build
def as_items(v):
    """Normalise a field value into a list of {'text', 'a'} items."""
    if v is None:
        return []
    if isinstance(v, str):
        return [{"text": v, "a": []}]
    if isinstance(v, dict):
        if "text" in v or "a" in v or "anchors" in v:
            return [{"text": v.get("text"), "a": v.get("a", v.get("anchors", [])) or [],
                     **{k: x for k, x in v.items() if k not in ("text", "a", "anchors")}}]
        return [{"text": json.dumps(v, ensure_ascii=False), "a": []}]
    if isinstance(v, list):
        out = []
        for x in v:
            out += as_items(x)
        return out
    return [{"text": str(v), "a": []}]


class Checker:
    def __init__(self, D):
        self.D = D
        self.records = []  # one per checked item
        self.evidence = []

    def check_item(self, item, where, section_id=None):
        D = self.D
        anchors = item.get("a") or []
        if isinstance(anchors, (str, dict)):
            anchors = [anchors]
        res = [D.resolve(x) for x in anchors]
        text = item.get("text") or ""
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
                if r.get("ok") and sid and sid != section_id and not D.is_ancestor(section_id, sid):
                    outside.append(f"{r.get('raw')} -> {sid}")
            if outside and len(outside) == len([r for r in res if r.get("ok")]):
                review.append("all anchors outside this section: " + "; ".join(outside)[:200])
        # numbers: every number in the note must occur in anchored evidence
        ev_nums = set()
        for r in res:
            if r.get("ok"):
                ev_nums |= L.numbers_in(D.evidence_text(r))
                ev_nums |= L.numbers_in(r.get("quote") or "")
        allowed_ctx = set()
        for r in res:  # the label number of an anchor (Table 2, Eq. 3), exact string only
            lab = str(r.get("raw")).split(":", 1)[0]
            if not re.match(r"^\s*p\d+[-@]", lab):
                allowed_ctx |= set(re.findall(r"\d+(?:\.\d+)*", lab))
        unsupported, minor = [], []
        for n in L.note_numbers(text):
            variants = L.numbers_in(n)
            if variants & ev_nums:
                continue
            ctx = re.search(r"(table|fig\.?|figure|eq\.?|section|sec\.?|§|表|图|式|第)\s*" + re.escape(n), text, re.I)
            if ctx or n in allowed_ctx:
                continue
            small = bool(re.fullmatch(r"-?\d", n))  # single-digit integers: too ambiguous to fail on
            (minor if small else unsupported).append(n)
        if unsupported:
            if res:
                problems.append("numbers_not_in_evidence:" + ",".join(unsupported))
        info = {"small_numbers_unchecked": minor} if minor else {}
        ok = not problems
        verified = ok and not review and any(r.get("check") in ("quote_verbatim", "quote_in_table", "quote_in_caption",
                                                                  "quote_in_neighbour_block", "table_exists",
                                                                  "equation_exists", "figure_exists") for r in res)
        status = "verified" if verified else ("needs_review" if ok else "failed")
        rec = {"where": where, "status": status, "problems": problems, "review": review,
               "numbers_checked": [n for n in L.note_numbers(text) if n not in unsupported + minor]}
        self.records.append(rec)
        clean = [{k: v for k, v in r.items() if k not in ("score",) or r.get("check") != "quote_verbatim"} for r in res]
        for r in clean:
            if r.get("ok"):
                self.evidence.append({"field": where, **{k: r.get(k) for k in (
                    "kind", "page", "block_id", "paragraph_id", "table", "figure", "equation", "bbox", "section_id",
                    "section", "quote", "check") if r.get(k) is not None}})
        out = {k: v for k, v in item.items() if k not in ("a", "anchors", "_prefilled")}
        out["anchors"] = clean
        out["check"] = {"status": status, **({"problems": problems} if problems else {}),
                        **({"review": review} if review else {}), **info}
        return out


def norm_term(t):
    t = L.nfkc(t or "").lower().strip()
    t = re.sub(r"[\s\-_]+", " ", t)
    t = re.sub(r"(?<=[a-z]{3})(es|s)$", "", t)
    return t


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
    if len(words) <= 6:
        return " ".join(words)
    return " ".join(words[-4:])


def merge_knowledge(items, D):
    groups, order, log = {}, [], []
    for it in items:
        if not it.get("term"):
            continue
        keys = {norm_term(it["term"])} | {norm_term(x) for x in it.get("aliases") or []}
        hit = next((g for g in order if keys & groups[g]["_keys"]), None)
        if hit is None:
            g = dict(it)
            g["aliases"] = list(dict.fromkeys(it.get("aliases") or []))
            g["a"] = list(it.get("a") or [])
            g["_keys"] = keys
            g["_defs"] = [it.get("definition")] if it.get("definition") else []
            groups[it["term"]] = g
            order.append(it["term"])
        else:
            g = groups[hit]
            log.append({"merged": it["term"], "into": hit})
            g["_keys"] |= keys
            for x in [it["term"]] + list(it.get("aliases") or []):
                if norm_term(x) != norm_term(hit) and norm_term(x) not in {norm_term(y) for y in g["aliases"]}:
                    g["aliases"].append(x)
            g["a"] += [x for x in it.get("a") or [] if x not in g["a"]]
            if it.get("definition") and it["definition"] not in g["_defs"]:
                g["_defs"].append(it["definition"])
    out = []
    full = " ".join(D.blocks[b].get("text") or "" for b in D.order)
    for t in order:
        g = groups[t]
        defs = g.pop("_defs")
        g.pop("_keys")
        g["definition"] = defs[0] if defs else g.get("definition")
        if len(defs) > 1:
            g["other_definitions"] = defs[1:]
            g["definition_conflict"] = "several definitions merged; check they agree"
        # abbreviation check: "Long Form (ABBR)" or "ABBR (Long Form)" printed in the paper
        abbrs = [x for x in [g["term"]] + g["aliases"] if re.fullmatch(r"[A-Z][A-Za-z0-9\-]{1,9}s?", x or "") and sum(c.isupper() for c in x) >= 2]
        if abbrs:
            ab = abbrs[0]
            pat = re.compile(r"([A-Za-z][\w\- ]{3,80}?)\s*\(\s*" + re.escape(ab) + r"\s*\)|" + re.escape(ab) + r"\s*\(([^)]{4,80})\)")
            m = pat.search(full)
            g["abbreviation"] = {"abbr": ab, "expansion_in_paper": expansion(ab, m.group(1) or m.group(2)) if m else None,
                                 "status": "found_in_text" if m else "expansion_not_printed"}
        g["text"] = g.get("definition") or g["term"]
        out.append(g)
    return out, log


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
            sec = D.sec_by_id.get(r.get("section_id"), {})
            secn = f"§{sec.get('number')}" if sec.get("number") else (sec.get("title") or "")[:20]
            refs.append(f"p.{r.get('page')} {secn} {lab}".replace("  ", " "))
        mark = {"verified": "", "needs_review": " ⚠", "failed": " ✗"}.get(it.get("check", {}).get("status"), "")
        return (" 〔" + "; ".join(refs) + "〕" if refs else " 〔no anchor〕") + mark

    def items_md(v, indent=""):
        out = []
        for it in v or []:
            out.append(f"{indent}- {it.get('text')}{cite(it)}")
        return out

    title = (card.get("title") or [{}])[0].get("text") if card.get("title") else "(title not found)"
    L_.append(f"# Notes: {title}")
    L_.append(f"\ncase_id: `{res.get('case_id')}` · source: `{os.path.basename(state['sources'][0]['file'])}` "
              f"(sha256 {state['sources'][0]['sha256'][:12]}…) · status: **{res['status']}** · built {now()} by {L.VERSION}")
    L_.append("\nCitation format: 〔p.PAGE §SECTION BLOCK〕; BLOCK = p{page}-b{n} in `parsed/*/doc.json`. "
              "⚠ = needs human review, ✗ = check failed.")
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
    (r"card|paper_card|summary_card|结构化|卡片", "@card"),
    (r"section|chapter|章节", "@sections"),
    (r"knowledge|concept|term|glossary|知识点|术语", "@knowledge"),
    (r"limitation|局限", "@card.limitations"),
    (r"finding|result|发现|结果", "@card.main_findings"),
    (r"research_question|question|问题", "@card.research_question"),
    (r"method|方法", "@card.method"),
    (r"data|数据", "@card.data"),
    (r"conclusion|结论", "@card.conclusion"),
    (r"evidence|source|anchor|证据|来源", "@evidence"),
    (r"notes?$|markdown|笔记", "@notes_md"),
]


def walk_anchors(v, ck, where):
    """Resolve anchors inside literal contract values (dicts with 'a'/'anchors')."""
    if isinstance(v, dict):
        if "a" in v or "anchors" in v:
            return ck.check_item({"text": v.get("text") or json.dumps({k: x for k, x in v.items() if k not in ("a", "anchors")}, ensure_ascii=False), **v}, where)
        return {k: walk_anchors(x, ck, f"{where}.{k}") for k, x in v.items()}
    if isinstance(v, list):
        return [walk_anchors(x, ck, f"{where}[{i}]") for i, x in enumerate(v)]
    return v


def cmd_build(a):
    t0 = time.time()
    work = a.work
    state = load_state(work)
    out = a.out or state["out"]
    draft = load(a.draft or os.path.join(work, "draft.json"))
    D = L.Doc(state["parsed_dir"])
    ck = Checker(D)
    # card
    card = {}
    for k in L.CARD_KEYS:
        items = as_items((draft.get("card") or {}).get(k))
        card[k] = [ck.check_item(it, f"card.{k}") for it in items if (it.get("text") or "").strip()]
    # sections: aligned to the paper's outline; unknown ids reported
    by_id = {}
    unknown = []
    for s in draft.get("sections") or []:
        sid = s.get("section_id")
        if sid not in D.sec_by_id:
            # tolerate heading numbers instead of ids
            m = next((x["id"] for x in D.sections if str(x.get("number")) == str(sid) or x.get("title") == s.get("heading")), None)
            if not m:
                unknown.append(sid)
                continue
            sid = m
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
    kps, merges = merge_knowledge(draft.get("knowledge") or [], D)
    kp_out = []
    for i, k in enumerate(kps):
        c = ck.check_item(k, f"knowledge[{i}]:{k.get('term')}", k.get("section_id") if k.get("section_id") in D.sec_by_id else None)
        if k.get("abbreviation", {}).get("status") == "expansion_not_printed":
            c["check"].setdefault("review", []).append("abbreviation expansion not printed in the paper")
            if c["check"]["status"] == "verified":
                c["check"]["status"] = "needs_review"
        kp_out.append(c)
    unreported = [u for u in draft.get("unreported") or [] if u.get("reason") and not str(u.get("reason")).startswith("e.g.")]
    unrep_fields = {str(u.get("field")).replace("card.", "") for u in unreported}
    card_missing = [k for k in L.CARD_REQUIRED if not card.get(k) and k not in unrep_fields]
    # coverage: every top-level non-reference section needs at least one note or a skip_reason
    required = [s for s in sec_notes if (s.get("level") or 1) <= 1]
    covered = [s for s in required if any(s.get(f) for f in L.SECTION_FIELDS + ["key_points"]) or s.get("skip_reason")]
    # children notes count for the parent
    for s in required:
        if s not in covered and any(any(c.get(f) for f in L.SECTION_FIELDS + ["key_points"])
                                    for c in sec_notes if c.get("parent") == s["section_id"]):
            covered.append(s)
    missing = [f"{s['section_id']} {s['heading']}" for s in required if s not in covered]
    recs = ck.records
    nv = sum(r["status"] == "verified" for r in recs)
    nr = sum(r["status"] == "needs_review" for r in recs)
    nf = sum(r["status"] == "failed" for r in recs)
    verification = {
        "n_items": len(recs), "n_verified": nv, "n_needs_review": nr, "n_failed": nf,
        "section_coverage": {"required": len(required), "covered": len(covered), "missing": missing},
        "unknown_section_ids_in_draft": unknown, "card_missing": card_missing,
        "knowledge_merges": merges, "outline_fixes": D.outline_fixes,
        "failed_items": [r for r in recs if r["status"] == "failed"][:60],
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
            prev = load(rp)
        except Exception:  # noqa: BLE001
            prev = {}
    status = "success"
    if nf or card_missing or missing or unknown:
        status = "partial"
    if not recs:
        status = "failed"
    res = {"case_id": state.get("case_id")}
    for f in state["contract_fields"]:
        res[f] = None
    res.update({
        "status": status,
        "run_status": {"stage": "build", "reason": None if status == "success" else
                       f"{nf} failed items, {len(missing)} uncovered sections, card missing {card_missing}, unknown ids {unknown}",
                       "n_needs_review": nr, "seconds": round(time.time() - t0, 2), "tool": L.VERSION,
                       "human_takeover": "see verification.failed_items / review_items (where = field path; anchors carry page+bbox)"},
        "notes": {"paper_card": card, "section_notes": sec_notes, "knowledge_points": kp_out,
                  "outline": [{k: s.get(k) for k in ("id", "level", "number", "title", "parent", "pages", "appendix", "pseudo")}
                              for s in D.sections]},
        "evidence": ck.evidence,
        "unreported": unreported,
        "uncertainty": draft.get("uncertainty") or [],
        "conflicts": draft.get("conflicts") or [],
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
    for f in state["contract_fields"]:
        v = cmap.get(f)
        if v is None:
            ref = next((r for pat, r in AUTO_MAP if re.search(pat, f, re.I)), None)
            if ref:
                v = ref
                res["change_log"].append({"at": now(), "step": "contract_auto_map", "detail": f"{f} <- {ref}"})
        val, is_ref = resolve_ref(v, res, md_path)
        if is_ref:
            res[f] = val
        elif v is not None:
            res[f] = walk_anchors(v, ck, f"contract.{f}")
        if res[f] in (None, [], {}) and not any(u.get("field") == f for u in unreported):
            res["unreported"].append({"field": f, "reason": "contract field not filled by the agent (no mapping)"})
            res["status"] = "partial"
    # re-count after contract literals added records
    res["verification"]["n_items"] = len(ck.records)
    res["verification"]["n_failed"] = sum(r["status"] == "failed" for r in ck.records)
    res["verification"]["n_verified"] = sum(r["status"] == "verified" for r in ck.records)
    res["verification"]["n_needs_review"] = sum(r["status"] == "needs_review" for r in ck.records)
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
    dump(res["verification"], os.path.join(out, "verification.json"))
    dump(res, rp)
    v = res["verification"]
    print(json.dumps({"status": res["status"], "items": v["n_items"], "verified": v["n_verified"],
                      "needs_review": v["n_needs_review"], "failed": v["n_failed"],
                      "uncovered_sections": v["section_coverage"]["missing"], "card_missing": card_missing,
                      "unknown_section_ids": unknown,
                      "fix_these": [{"where": r["where"], "problems": r["problems"]} for r in v["failed_items"][:25]],
                      "review": [{"where": r["where"], "review": r["review"][:2]} for r in v["review_items"][:12]],
                      "contract": {f: (type(res[f]).__name__ if res[f] is not None else None) for f in state["contract_fields"]},
                      "outputs": [os.path.join(out, x) for x in ("result.json", "notes.md", "paper_card.csv",
                                                                 "knowledge_points.jsonl", "verification.json")]},
                     ensure_ascii=False, indent=1))


# ------------------------------------------------------------------ find
def cmd_find(a):
    state = load_state(a.work)
    D = L.Doc(state["parsed_dir"])
    q = [t for t in re.findall(r"\w+", L.nfkc(a.query).lower()) if len(t) > 1]
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
        print(json.dumps({"anchor": f"{bid}: {sent[:200]}", "section": s.get("path"), "score": sc}, ensure_ascii=False))
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
    p.add_argument("--pages", default=None)
    p.add_argument("--password", default=None)
    p.add_argument("--full-digest", action="store_true")
    p.add_argument("--force", action="store_true", help="overwrite an existing draft.json")
    p = sub.add_parser("build")
    p.add_argument("--work", default="/app/work")
    p.add_argument("--out", default=None)
    p.add_argument("--draft", default=None)
    p = sub.add_parser("find")
    p.add_argument("query")
    p.add_argument("--work", default="/app/work")
    p.add_argument("--section", default=None)
    p.add_argument("--top", type=int, default=6)
    a = ap.parse_args()
    {"init": cmd_init, "build": cmd_build, "find": cmd_find}[a.cmd](a)


if __name__ == "__main__":
    main()
