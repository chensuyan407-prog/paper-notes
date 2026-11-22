#!/usr/bin/env python3
"""Shared logic for paper-notes: outline building, sentence anchors, anchor
resolution and checks. Works on doc.json written by parse_pdf.py.

Anchor shorthand accepted in drafts (one string per anchor):
    "p3-b12: verbatim words from that block"   block anchor (best)
    "para14: verbatim words"                    paragraph anchor (resolved to its block)
    "Table 2" / "Table 2: words of the caption or a cell"
    "Fig. 4" / "Figure 4: words"                figure (caption) anchor
    "Eq. 3"                                     numbered equation
    "p2@x0,y0,x1,y1: what you read"             page-image region (scans); never machine-verified
    "s4"                                        whole section: allowed but flagged coarse
A dict {"block_id"|"table"|"figure"|"equation"|"page", "quote"} is accepted too.
"""
import difflib
import json
import os
import re
import unicodedata

VERSION = "paper-notes 1.0.0"

# Unified paper-card fields (same keys for every paper, so cards can be compared side by side).
CARD_FIELDS = [
    ("title", "Paper title as printed", True),
    ("authors", "Authors (and affiliations if useful)", True),
    ("venue_year", "Venue / year / arXiv id if printed in the PDF", False),
    ("research_question", "The question or problem the paper sets out to answer", True),
    ("motivation_gap", "Why it matters / what gap in prior work it addresses", False),
    ("contributions", "What the authors claim as their contributions", False),
    ("data", "Data, datasets, samples, corpora, benchmarks, materials (with sizes/splits as printed)", True),
    ("method", "Approach / model / experimental or analytical design", True),
    ("conditions", "Assumptions, settings, hyper-parameters, scope conditions the conclusions depend on", True),
    ("main_findings", "Main results, with numbers as printed", True),
    ("conclusion", "What the authors conclude", True),
    ("limitations", "Limitations stated by the authors (or 'not reported' + reason)", True),
    ("future_work", "Open problems / future work stated", False),
]
CARD_KEYS = [k for k, _, _ in CARD_FIELDS]
CARD_REQUIRED = [k for k, _, r in CARD_FIELDS if r]
SECTION_FIELDS = ["purpose", "method", "results", "conclusion", "transition"]
KP_KINDS = ["concept", "term", "abbreviation", "variable", "method", "dataset", "metric", "finding", "assumption", "formula"]

SKIP_SECTION = re.compile(r"^(references?|bibliography|acknowledg|致谢|参考文献)", re.I)
APPENDIX_RE = re.compile(r"^(appendix|supplementar|附录)", re.I)

CUES = {
    "research_question": r"\b(we (propose|present|introduce|study|investigate|address|ask|explore|examine)|this (paper|work|study|article)|our (goal|aim|objective)|the (goal|aim|purpose) of|research question|we seek|we aim)\b|本文|本研究|旨在|研究问题|提出了",
    "contributions": r"\b(contribution|our main|we make|to summarize|in summary, we|novel)\b|贡献|创新",
    "data": r"\b(dataset|data set|corpus|corpora|benchmark|samples?|participants|subjects|cohort|images|collected|training set|test set|validation set|split)\b|数据|样本|语料",
    "method": r"\b(we (use|adopt|train|apply|employ|formulate|define|model)|our (method|model|approach|framework|algorithm)|architecture|procedure|algorithm)\b|方法|模型|算法",
    "conditions": r"\b(assum|provided that|only (when|if)|under (the|these|this)|hyper-?parameter|learning rate|batch size|we set|is set to|fixed|held constant|condition)\w*|假设|条件|设定|参数",
    "main_findings": r"(\d+(\.\d+)?\s?%|\b(outperform|achiev|improv|reduc|increas|decreas|significant|state-of-the-art|show(s|ed)? that|we (find|found|observe)|results (show|indicate|suggest)|better than|lower|higher)\w*)|结果表明|显著|提高|优于",
    "conclusion": r"\b(in conclusion|we conclude|conclusion|these results (suggest|indicate|show)|overall|in this (paper|work), we)\b|结论|综上",
    "limitations": r"\b(limitation|limited|caveat|shortcoming|drawback|does not|do not|cannot|fail(s|ed)?|not (yet|clear|well)|remains? (unclear|open)|restricted to|only (applies|valid)|weakness|bias)\w*|局限|不足|限制",
    "future_work": r"\b(future (work|research|direction)|we (plan|leave|hope)|left for future|open (question|problem))\b|未来|今后|后续工作",
}
CUE_RE = {k: re.compile(v, re.I) for k, v in CUES.items()}
SECTION_HINT = {
    "research_question": r"abstract|introduction|引言|摘要|背景",
    "contributions": r"introduction|引言",
    "data": r"data|experiment|setup|material|method|evaluation|数据|实验",
    "method": r"method|approach|model|architecture|framework|learning|方法|模型",
    "conditions": r"implementation|setup|setting|training|experiment|method|实验|设置",
    "main_findings": r"result|experiment|evaluation|analysis|abstract|结果|实验",
    "conclusion": r"conclusion|discussion|summary|abstract|结论|讨论",
    "limitations": r"limitation|discussion|conclusion|future|局限|讨论|结论",
    "future_work": r"conclusion|discussion|future|结论|展望",
}

NUM_RE = re.compile(r"(?<![\w.\-−–])[-−–]?\d+(?:,\d{3})*(?:\.\d+)?(?:\s?%)?")
SENT_SPLIT = re.compile(r"(?<=[.!?。！？；;])\s+(?=[A-Z0-9\"“(\[])|(?<=[。！？；])")
ANCHOR_RE = re.compile(
    r"^\s*(?:(?P<block>p\d+-[bmg]\d+)|(?P<para>para\d+)|(?P<sec>s\d+)"
    r"|(?P<img>p(?P<ipage>\d+)@(?P<bbox>[\d.\s,]+))"
    r"|(?P<tab>(?:table|tab\.?|表)\s*(?P<tabn>[A-Z]?\d+[a-z]?))"
    r"|(?P<fig>(?:figure|fig\.?|图)\s*(?P<fign>[A-Z]?\d+[a-z]?))"
    r"|(?P<eq>(?:equation|eq\.?|eqn\.?|公式|式)\s*\(?(?P<eqn>[A-Z]?\d+[a-z]?)\)?))"
    r"\s*(?:[:：]\s*(?P<quote>.*))?$", re.I | re.S)


# ---------------------------------------------------------------- text utils
def nfkc(s):
    s = unicodedata.normalize("NFKC", s or "")
    for a, b in (("‘", "'"), ("’", "'"), ("“", '"'), ("”", '"'), ("–", "-"), ("—", "-"), ("−", "-"),
                 ("­", ""), ("×", "x"), ("·", "."), ("…", "...")):
        s = s.replace(a, b)
    return s


def tight(s):
    """Comparison form: NFKC, lower case, only letters/digits/CJK (hyphenation, spacing, quotes ignored)."""
    return "".join(ch for ch in nfkc(s).lower() if ch.isalnum())


NUM_ANY = re.compile(r"(?<![\d.])[-−–]?\d+(?:,\d{3})*(?:\.\d+)?(?:\s?%)?")


def numbers_in(s):
    """Numbers in evidence text (liberal: also 'ResNet-152', 'top-5')."""
    out = set()
    for m in NUM_ANY.findall(nfkc(s or "")) + NUM_RE.findall(nfkc(s or "")):
        v = m.replace(",", "").replace(" ", "").replace("−", "-").replace("–", "-").rstrip("%")
        v = v.lstrip("+")
        if v in ("", "-"):
            continue
        out.add(v)
        out.add(v.lstrip("-"))
        try:
            f = float(v)
            out.add(repr(f).rstrip("0").rstrip(".") if "." in repr(f) else str(int(f)))
        except ValueError:
            pass
    return out


def note_numbers(s):
    """Numbers stated in a note (years and single digits kept but marked minor)."""
    res = []
    for m in NUM_RE.findall(nfkc(s or "")):
        v = m.replace(",", "").replace(" ", "").rstrip("%")
        if v in ("", "-"):
            continue
        res.append(v)
    return res


def split_sentences(text):
    parts = [p.strip() for p in SENT_SPLIT.split(text or "") if p and p.strip()]
    return parts or ([text.strip()] if text and text.strip() else [])


# ---------------------------------------------------------------- doc loading
def load_doc(parsed_dir):
    p = parsed_dir if parsed_dir.endswith(".json") else os.path.join(parsed_dir, "doc.json")
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


def label_num(caption, kind):
    pat = {"table": r"^\s*(?:table|tab\.?|表)\s*([A-Z]?\d+[a-z]?)",
           "figure": r"^\s*(?:figure|fig\.?|图)\s*([A-Z]?\d+[a-z]?)"}[kind]
    m = re.match(pat, caption or "", re.I)
    return m.group(1).upper() if m else None


class Doc:
    def __init__(self, parsed_dir):
        self.dir = parsed_dir
        self.d = load_doc(parsed_dir)
        d = self.d
        self.blocks = {b["id"]: b for b in d.get("blocks", [])}
        for b in d.get("headers_footers", []):
            self.blocks.setdefault(b["id"], dict(b, removed=True))
        self.order = [b["id"] for b in d.get("blocks", [])]
        self.pos = {bid: i for i, bid in enumerate(self.order)}
        self.paras = {p["id"]: p for p in d.get("paragraphs", [])}
        self.block_para = {}
        for p in d.get("paragraphs", []):
            for s in p.get("sources", []):
                self.block_para[s["block_id"]] = p["id"]
        self.tables = {}
        for t in d.get("tables", []):
            n = label_num(t.get("caption"), "table")
            if n and n not in self.tables:
                self.tables[n] = t
        self.figures = {}
        for f in d.get("figures", []):
            n = label_num(f.get("caption"), "figure")
            if n and n not in self.figures:
                self.figures[n] = f
        self.equations = {}
        for e in d.get("equations", []):
            if e.get("number") is not None:
                self.equations.setdefault(str(e["number"]).upper(), e)
        self.sections = self._sections()
        self.sec_by_id = {s["id"]: s for s in self.sections}
        self._tight_cache = {}

    # -- outline -------------------------------------------------------
    def _sections(self):
        raw = [dict(s) for s in self.d.get("sections", [])]
        fixes = []
        ref_ids = {s["id"] for s in raw if SKIP_SECTION.match(s.get("title") or "")}
        for s in raw:
            # parse_pdf nests appendix letters (A, B, ...) under References; lift them out.
            if s.get("parent") in ref_ids and re.match(r"^[A-Z](\.\d+)*$", str(s.get("number") or "")):
                fixes.append({"section": s["id"], "fix": "appendix section lifted out of References"})
                s["parent"] = None
                s["level"] = 1 if "." not in str(s["number"]) else s.get("level", 2)
                s["appendix"] = True
            s["skip"] = bool(SKIP_SECTION.match(s.get("title") or ""))
            s["appendix"] = s.get("appendix") or bool(APPENDIX_RE.match(s.get("title") or ""))
        self.outline_fixes = fixes
        if raw and all(s.get("block_id") in self.pos for s in raw):
            raw = self._repair_headings(raw, fixes)
        # block membership and spans
        members = {s["id"]: [] for s in raw}
        for bid in self.order:
            b = self.blocks[bid]
            sid = b.get("section_id")
            if sid in members:
                members[sid].append(bid)
        for s in raw:
            bl = members[s["id"]]
            s["block_ids"] = bl
            body = [x for x in bl if self.blocks[x].get("role") in ("body", "equation", "list", "footnote")]
            s["n_words"] = sum(len((self.blocks[x].get("text") or "").split()) for x in body)
            s["n_chars"] = sum(len(self.blocks[x].get("text") or "") for x in body)
            pages = [self.blocks[x]["page"] for x in bl] or [s.get("page")]
            s["pages"] = [min(pages), max(pages)]
            s["first_block"] = bl[0] if bl else s.get("block_id")
            s["last_block"] = bl[-1] if bl else s.get("block_id")
            s["paragraph_ids"] = sorted({self.block_para[x] for x in bl if x in self.block_para},
                                        key=lambda p: int(re.sub(r"\D", "", p) or 0))
        # tables/figures/equations attached via their caption/equation block's section
        for kind, coll in (("tables", self.d.get("tables", [])), ("figures", self.d.get("figures", []))):
            for s in raw:
                s[kind] = []
            for t in coll:
                cb = t.get("caption_block")
                sid = self.blocks.get(cb, {}).get("section_id") if cb else None
                if sid is None:
                    sid = self._section_at(t.get("page"), t.get("bbox"))
                for s in raw:
                    if s["id"] == sid:
                        n = label_num(t.get("caption"), kind[:-1])
                        lab = (f"{'Table' if kind == 'tables' else 'Figure'} {n}" if n else (t.get("caption") or "")[:24]) or t.get("id")
                        s[kind].append(lab)
        for s in raw:
            s["equations"] = []
        for e in self.d.get("equations", []):
            sid = self.blocks.get(e.get("block_id"), {}).get("section_id")
            for s in raw:
                if s["id"] == sid and e.get("number") is not None:
                    s["equations"].append(f"Eq. {e['number']}")
        if not raw:
            raw = self._pseudo_sections()
        # path strings
        byid = {s["id"]: s for s in raw}
        for s in raw:
            path, p = [], s
            while p:
                path.append(((str(p.get("number")) + " ") if p.get("number") else "") + (p.get("title") or ""))
                p = byid.get(p.get("parent"))
            s["path"] = " > ".join(reversed(path))
        return raw

    def _repair_headings(self, raw, fixes):
        """Drop junk numbered headings ('1 N' from footnote marks), recover numbered headings the parser
        classified as body text when their number continues the paper's numbering, then reassign every
        block to the last heading before it in reading order. Every change is logged in outline_fixes."""
        def ntuple(n):
            try:
                return tuple(int(x) for x in str(n).split("."))
            except ValueError:
                return None
        keep = []
        for s in raw:
            t = (s.get("title") or "").strip()
            n_lat = len(re.sub(r"[^A-Za-z]", "", t))
            n_cjk = len(re.sub(r"[^一-鿿]", "", t))
            if s.get("number") and n_lat < 3 and n_cjk < 2:
                fixes.append({"section": s["id"], "fix": f"rejected junk heading '{s.get('number')} {t}' (merged into previous section)"})
                continue
            keep.append(s)
        raw = keep
        heads = {s["block_id"] for s in raw}
        body_sizes = sorted(self.blocks[b].get("size") or 0 for b in self.order if self.blocks[b].get("role") == "body")
        med = body_sizes[len(body_sizes) // 2] if body_sizes else 10
        hrx = re.compile(r"^\s*(\d+(?:\.\d+){0,3})\.?\s+([A-Z][^\n]{2,110})$")
        added = []
        used = {str(s.get("number")) for s in raw if s.get("number")}
        for bid in self.order:
            b = self.blocks[bid]
            if bid in heads or b.get("role") not in ("body", "list"):
                continue
            txt = (b.get("text") or "").strip()
            m = hrx.match(txt)
            if not m or len(txt.split()) > 16 or txt.endswith((".", ",", ";", ":")):
                continue
            if not (b.get("bold") or (b.get("size") or 0) > med + 0.5):
                continue
            num, title = m.group(1), m.group(2).strip()
            tu = ntuple(num)
            if not tu or num in used:
                continue
            # number must continue the numbering: previous numbered heading (in reading order) < num < next one
            prev = next_ = None
            for s in sorted(raw + added, key=lambda x: self.pos.get(x["block_id"], 0)):
                st = ntuple(s.get("number")) if s.get("number") else None
                if not st:
                    continue
                if self.pos[s["block_id"]] < self.pos[bid]:
                    prev = st
                elif next_ is None:
                    next_ = st
            if (prev and tu <= prev) or (next_ and tu >= next_):
                continue
            if len(tu) > 1 and prev and tu[:-1] != prev[:len(tu) - 1] and tu[:-1] != prev:
                continue
            new = {"id": f"sx{len(added) + 1}", "level": len(tu), "number": num, "title": title.replace("- ", "-"),
                   "page": b["page"], "block_id": bid, "parent": None, "rule": "recovered: bold numbered line continuing the numbering",
                   "skip": False, "appendix": False}
            added.append(new)
            used.add(num)
            b["role"] = "heading"
            fixes.append({"section": new["id"], "fix": f"recovered heading '{num} {title}' at {bid}"})
        raw = sorted(raw + added, key=lambda x: self.pos[x["block_id"]])
        # parents by numbering
        last_by_num = {}
        for s in raw:
            n = str(s.get("number") or "")
            if n and "." in n and re.match(r"^[\dA-Z]+(\.\d+)+$", n):
                par = last_by_num.get(n.rsplit(".", 1)[0])
                if par:
                    s["parent"] = par
                    s["level"] = n.count(".") + 1
            elif n and re.match(r"^\d+$", n):
                s["parent"] = None
                s["level"] = 1
            if n:
                last_by_num[n] = s["id"]
        # numbering gaps (a missed heading the parser could not see)
        nums = [ntuple(s["number"]) for s in raw if s.get("number") and ntuple(s["number"])]
        for a_, b_ in zip(nums, nums[1:]):
            if len(a_) == len(b_) and a_[:-1] == b_[:-1] and b_[-1] - a_[-1] > 1:
                fixes.append({"fix": f"numbering gap between {'.'.join(map(str, a_))} and {'.'.join(map(str, b_))}: "
                                     "a heading was not detected; its text sits in the previous section"})
            elif len(b_) == 1 and len(a_) >= 1 and b_[0] - a_[0] > 1:
                fixes.append({"fix": f"numbering gap before section {b_[0]}: a heading was not detected"})
        # reassign blocks
        start = {s["block_id"]: s["id"] for s in raw}
        cur = None
        for bid in self.order:
            if bid in start:
                cur = start[bid]
            if cur is not None or self.blocks[bid].get("section_id"):
                self.blocks[bid]["section_id"] = cur
        return raw

    def _section_at(self, page, bbox):
        best = None
        for bid in self.order:
            b = self.blocks[bid]
            if b["page"] > (page or 0):
                break
            if b.get("section_id"):
                best = b["section_id"]
        return best

    def _pseudo_sections(self):
        """No headings detected: page-based pseudo sections, marked so the agent knows alignment is weak."""
        out = []
        pages = sorted({self.blocks[b]["page"] for b in self.order} | {p["page"] for p in self.d.get("pages", [])})
        for i, pg in enumerate(pages):
            bl = [b for b in self.order if self.blocks[b]["page"] == pg]
            for b in bl:
                self.blocks[b]["section_id"] = f"s{i + 1}"
            pinfo = next((p for p in self.d.get("pages", []) if p["page"] == pg), {})
            label = "image-only page, read the page image" if pinfo.get("page_image") and not bl else "no heading detected"
            out.append({"id": f"s{i + 1}", "level": 1, "number": None, "title": f"[page {pg}, {label}]",
                        "page_image": pinfo.get("page_image"),
                        "page": pg, "block_id": bl[0] if bl else None, "parent": None, "rule": "pseudo: page split",
                        "pseudo": True, "skip": False, "appendix": False, "block_ids": bl,
                        "n_words": sum(len((self.blocks[b].get("text") or "").split()) for b in bl),
                        "n_chars": sum(len(self.blocks[b].get("text") or "") for b in bl),
                        "pages": [pg, pg], "first_block": bl[0] if bl else None, "last_block": bl[-1] if bl else None,
                        "paragraph_ids": [], "tables": [], "figures": [], "equations": []})
        self.outline_fixes.append({"fix": "no section headings detected; page-based pseudo sections used"})
        return out

    def section_of_block(self, bid):
        return self.blocks.get(bid, {}).get("section_id")

    def is_ancestor(self, anc, sid):
        p = self.sec_by_id.get(sid)
        while p:
            if p["id"] == anc:
                return True
            p = self.sec_by_id.get(p.get("parent"))
        return False

    def tight_of(self, bid):
        if bid not in self._tight_cache:
            self._tight_cache[bid] = tight(self.blocks[bid].get("text"))
        return self._tight_cache[bid]

    # -- anchor resolution ----------------------------------------------
    def resolve(self, a):
        """Return a full anchor record with check results for one shorthand anchor."""
        rec = {"raw": a}
        if isinstance(a, dict):
            quote = a.get("quote")
            if a.get("block_id"):
                kind, key = "block", a["block_id"]
            elif a.get("table"):
                kind, key = "table", str(a["table"]).split()[-1]
            elif a.get("figure"):
                kind, key = "figure", str(a["figure"]).split()[-1]
            elif a.get("equation"):
                kind, key = "equation", str(a["equation"]).strip("() ").split()[-1]
            elif a.get("bbox") is not None:
                kind, key = "image", (a.get("page"), a.get("bbox"))
            else:
                return dict(rec, ok=False, check="anchor_unparseable")
        else:
            m = ANCHOR_RE.match(str(a))
            if not m:
                return dict(rec, ok=False, check="anchor_unparseable",
                            hint="use 'p3-b12: verbatim words', 'Table 2', 'Fig. 3', 'Eq. 2' or 'p2@x0,y0,x1,y1: text'")
            quote = (m.group("quote") or "").strip().strip('"“”') or None
            if m.group("block"):
                kind, key = "block", m.group("block")
            elif m.group("para"):
                kind, key = "para", m.group("para")
            elif m.group("sec"):
                kind, key = "section", m.group("sec")
            elif m.group("img"):
                kind, key = "image", (int(m.group("ipage")), [float(x) for x in re.split(r"[\s,]+", m.group("bbox").strip()) if x])
            elif m.group("tab"):
                kind, key = "table", m.group("tabn").upper()
            elif m.group("fig"):
                kind, key = "figure", m.group("fign").upper()
            else:
                kind, key = "equation", m.group("eqn").upper()
        rec["kind"], rec["quote"] = kind, quote
        return getattr(self, "_res_" + kind)(rec, key, quote)

    def _block_rec(self, rec, bid):
        b = self.blocks[bid]
        sid = b.get("section_id")
        s = self.sec_by_id.get(sid, {})
        rec.update(block_id=bid, page=b["page"], bbox=b.get("bbox"), role=b.get("role"), section_id=sid,
                   section=s.get("path"), paragraph_id=self.block_para.get(bid))
        if b.get("removed"):
            rec["warning"] = "block is removed header/footer/figure text: weak evidence for body claims"
        return rec

    def _match_quote(self, quote, cand_ids):
        tq = tight(quote)
        for bid in cand_ids:
            if tq and tq in self.tight_of(bid):
                return bid, 1.0
        # quote spanning two consecutive blocks (column/page break)
        for i in range(len(cand_ids) - 1):
            j = tight(self.blocks[cand_ids[i]].get("text")) + tight(self.blocks[cand_ids[i + 1]].get("text"))
            if tq and tq in j:
                return cand_ids[i], 1.0
        return None, 0.0

    def _fuzzy(self, quote, cand_ids):
        tq = tight(quote)
        best = (0.0, None, None)
        if not tq:
            return best
        for bid in cand_ids:
            for sent in split_sentences(self.blocks[bid].get("text") or ""):
                ts = tight(sent)
                if not ts:
                    continue
                sm = difflib.SequenceMatcher(None, tq, ts, autojunk=False)
                # share of the quote covered by runs of >= 4 identical chars (ignores scattered letters)
                score = sum(m.size for m in sm.get_matching_blocks() if m.size >= 4) / max(len(tq), 1)
                if score > best[0]:
                    best = (score, bid, sent)
        return best

    def neighbours(self, bid, k=2):
        i = self.pos.get(bid)
        if i is None:
            return [bid]
        ids = self.order[max(0, i - k): i + k + 1]
        pid = self.block_para.get(bid)
        if pid:
            ids = [s["block_id"] for s in self.paras[pid]["sources"]] + [x for x in ids]
        seen, out = set(), []
        for x in [bid] + ids:
            if x not in seen and x in self.blocks:
                seen.add(x)
                out.append(x)
        return out

    def _res_block(self, rec, bid, quote, from_para=False):
        if bid not in self.blocks:
            # tolerate a wrong id when the quote is unique in the document
            if quote:
                hit, _ = self._match_quote(quote, self.order)
                if hit:
                    self._block_rec(rec, hit)
                    return dict(rec, ok=True, check="relocated", requested_block=bid,
                                note="block id did not exist; quote found verbatim in " + hit)
            return dict(rec, ok=False, check="block_not_found")
        if not quote:
            self._block_rec(rec, bid)
            return dict(rec, ok=True, check="no_quote", weak=True,
                        note="block exists but no quote: claim-to-text match not checkable")
        hit, _ = self._match_quote(quote, [bid])
        if hit:
            self._block_rec(rec, bid)
            return dict(rec, ok=True, check="quote_verbatim")
        hit, _ = self._match_quote(quote, self.neighbours(bid))
        if hit:
            self._block_rec(rec, hit)
            return dict(rec, ok=True, check="quote_in_neighbour_block", requested_block=bid,
                        note=f"quote is in {hit} (same paragraph or adjacent), anchor moved")
        hit, _ = self._match_quote(quote, self.order)
        if hit:
            self._block_rec(rec, hit)
            return dict(rec, ok=True, check="relocated", requested_block=bid,
                        note=f"quote not in {bid}; found verbatim in {hit} (anchor moved, check the claim)")
        score, fb, sent = self._fuzzy(quote, self.neighbours(bid, 3))
        if score < 0.85:
            s2, fb2, sent2 = self._fuzzy(quote, self.order)
            if s2 > score:
                score, fb, sent = s2, fb2, sent2
        if fb and score >= 0.85:
            self._block_rec(rec, fb)
            return dict(rec, ok=True, check="quote_fuzzy", score=round(score, 3), source_sentence=sent,
                        requested_block=bid, needs_review=True,
                        note="quote is not verbatim; closest source sentence attached")
        self._block_rec(rec, bid)
        return dict(rec, ok=False, check="quote_not_found", score=round(score, 3),
                    closest_sentence=sent, closest_block=fb)

    def _res_para(self, rec, pid, quote):
        p = self.paras.get(pid)
        if not p:
            return dict(rec, ok=False, check="paragraph_not_found")
        ids = [s["block_id"] for s in p["sources"]]
        if quote:
            hit, _ = self._match_quote(quote, ids)
            if hit:
                return self._res_block(rec, hit, quote)
        return self._res_block(rec, ids[0], quote)

    def _res_section(self, rec, sid, quote):
        s = self.sec_by_id.get(sid)
        if not s:
            return dict(rec, ok=False, check="section_not_found")
        if quote:
            hit, _ = self._match_quote(quote, s["block_ids"])
            if hit:
                return self._res_block(rec, hit, quote)
        rec.update(section_id=sid, section=s["path"], page=s["pages"][0], pages=s["pages"])
        return dict(rec, ok=True, check="coarse_section_anchor", weak=True,
                    note="whole-section anchor: too coarse to verify a specific claim")

    def _res_table(self, rec, n, quote):
        t = self.tables.get(n)
        if not t:
            return dict(rec, ok=False, check="table_not_found", known=sorted(self.tables))
        cb = t.get("caption_block")
        sid = self.blocks.get(cb, {}).get("section_id") if cb else None
        rec.update(table=f"Table {n}", table_id=t.get("id"), page=t.get("page"), bbox=t.get("bbox"),
                   caption=(t.get("caption") or "")[:200], caption_block=cb, section_id=sid,
                   section=self.sec_by_id.get(sid, {}).get("path"))
        if not quote:
            return dict(rec, ok=True, check="table_exists")
        texts = [t.get("caption") or ""] + [" ".join(r) if isinstance(r, list) else str(r) for r in t.get("rows", [])]
        texts += [c.get("text") or "" for c in t.get("cells", [])]
        tq = tight(quote)
        rows = [" | ".join(r) if isinstance(r, list) else str(r) for r in t.get("rows", [])]
        hits = [r for r in rows if tq and tq in tight(r)]
        if not hits:
            # "row label ... value": every token of the quote inside one row
            toks = [tight(x) for x in re.split(r"[\s|;,]+", quote) if tight(x)]
            hits = [r for r in rows if toks and all(tk in tight(r) for tk in toks)]
        if hits:
            return dict(rec, ok=True, check="quote_in_table", matched_rows=hits[:3])
        for tx in texts:
            if tq and tq in tight(tx):
                return dict(rec, ok=True, check="quote_in_table")
        return dict(rec, ok=False, check="quote_not_in_table",
                    hint="quote = words of one row (row label + value) or of the caption")

    def _res_figure(self, rec, n, quote):
        f = self.figures.get(n)
        if not f:
            return dict(rec, ok=False, check="figure_not_found", known=sorted(self.figures))
        cb = f.get("caption_block")
        sid = self.blocks.get(cb, {}).get("section_id") if cb else None
        rec.update(figure=f"Figure {n}", figure_id=f.get("id"), page=f.get("page"), bbox=f.get("bbox"),
                   caption=(f.get("caption") or "")[:200], caption_block=cb, section_id=sid,
                   section=self.sec_by_id.get(sid, {}).get("path"))
        if not quote:
            return dict(rec, ok=True, check="figure_exists",
                        note="figure content (curves, images) is not machine-readable; only the caption is checked")
        if tight(quote) in tight(f.get("caption") or ""):
            return dict(rec, ok=True, check="quote_in_caption")
        return dict(rec, ok=True, check="figure_reading_unverified", needs_review=True,
                    note="quote not in caption: treated as a reading of the figure, needs human check")

    def _res_equation(self, rec, n, quote):
        e = self.equations.get(n)
        if not e:
            return dict(rec, ok=False, check="equation_not_found", known=sorted(self.equations))
        sid = self.blocks.get(e.get("block_id"), {}).get("section_id")
        rec.update(equation=f"Eq. {e.get('number')}", page=e.get("page"), bbox=e.get("bbox"),
                   block_id=e.get("block_id"), section_id=sid, section=self.sec_by_id.get(sid, {}).get("path"),
                   expr_unicode=e.get("expr_unicode"), transcription_status=e.get("transcription_status"))
        return dict(rec, ok=True, check="equation_exists",
                    needs_review=e.get("transcription_status") != "auto")

    def _res_image(self, rec, key, quote):
        page, bbox = key
        pages = {p["page"]: p for p in self.d.get("pages", [])}
        if page not in pages:
            return dict(rec, ok=False, check="page_not_found")
        rec.update(page=page, bbox=bbox, transcription=quote)
        pw, ph = pages[page].get("width") or 1e9, pages[page].get("height") or 1e9
        if len(bbox) != 4 or bbox[0] >= bbox[2] or bbox[1] >= bbox[3] or bbox[2] > pw + 1 or bbox[3] > ph + 1 or min(bbox) < -1:
            return dict(rec, ok=False, check="bbox_off_page", page_size=[pw, ph])
        if not quote:
            return dict(rec, ok=False, check="image_anchor_without_transcription")
        return dict(rec, ok=True, check="image_read_unverified", needs_review=True,
                    note="read from the page image; position is checked, reading is not")

    # -- evidence texts for number checks ----------------------------------
    def evidence_text(self, r):
        if r.get("kind") == "table" or r.get("table"):
            t = self.tables.get(str(r.get("table", "")).split()[-1])
            if t:
                if r.get("matched_rows"):  # numbers must come from the quoted row(s), not anywhere in the table
                    return " ".join(r["matched_rows"])
                return (t.get("caption") or "") + " " + " ".join(c.get("text") or "" for c in t.get("cells", []))
        if r.get("kind") == "figure" or r.get("figure"):
            return (r.get("caption") or "") + " " + (r.get("quote") or "")
        if r.get("kind") == "image":
            return r.get("transcription") or ""
        if r.get("kind") == "equation":
            return " ".join(str(x) for x in (r.get("expr_unicode"), r.get("raw")) if x)
        bid = r.get("block_id")
        if bid and bid in self.blocks:
            txt = self.blocks[bid].get("text") or ""
            pid = self.block_para.get(bid)
            if pid:
                txt = self.paras[pid].get("text") or txt
            return txt
        return r.get("quote") or ""

    # -- cue sentences ----------------------------------------------------
    def cue_sentences(self, per_kind=8):
        out = {k: [] for k in CUES}
        for bid in self.order:
            b = self.blocks[bid]
            if b.get("role") not in ("body", "abstract", "list"):
                continue
            s = self.sec_by_id.get(b.get("section_id"), {})
            if s.get("skip"):
                continue
            title = (s.get("path") or "") + " " + ("abstract" if b.get("role") == "abstract" else "")
            for sent in split_sentences(b.get("text") or ""):
                if len(sent) < 25:
                    continue
                for k, rx in CUE_RE.items():
                    if rx.search(sent):
                        score = 1.0 + (1.5 if re.search(SECTION_HINT[k], title, re.I) else 0.0)
                        if k == "main_findings":
                            score += 0.3 * len(NUM_RE.findall(sent))
                        out[k].append({"anchor": f"{bid}: {sent[:160]}", "section": s.get("path"), "score": round(score, 2)})
        for k in out:
            out[k] = sorted(out[k], key=lambda x: -x["score"])[:per_kind]
        return out
