"""Layout-preserving translation of PDF (and XPS / MOBI / FB2 / CBZ, converted to PDF first).

Text pages: paragraphs are extracted with coordinates, translated, the original glyphs are
removed (images and vector art kept) and the translation is written into the same box.
Scanned / image-only pages: rendered, OCR'd on-device (Apple Vision), lines are painted over
with the sampled background colour and the translation is written on top.
Outputs <stem>.<lang>.pdf (translation) and <stem>.<lang>-dual.pdf (original left, translation right).
"""
import os
import re
import tempfile
from collections import Counter

import fitz

from . import ocr
from .render import add_dual_page, font_setup, paragraphs_from_ocr, render_page
from .textutil import CJK, has_letters, out_path

LIGATURES = {"ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl"}
REF_HEADS = {"references", "reference", "bibliography", "referencesandnotes", "literaturecited", "参考文献"}
END_PUNCT = tuple('.:?!;)"”。：？！；）')
BULLET_RE = re.compile(r"^(•|–|-|\(\w{1,3}\)|\d{1,2}\)|[a-z]\))\s")
BOLD_RE = re.compile(r"bold|bd\b|-bd|bx\d|black|semibold|heavy|demi|-[6-9]00\b", re.I)


def clean(t):
    for k, v in LIGATURES.items():
        t = t.replace(k, v)
    return t


def area(r):
    return 0.0 if r.is_empty else r.width * r.height


def span_bold(s):
    return bool(s["flags"] & 16) or bool(BOLD_RE.search(s["font"]))


# ------------------------------------------------------------------ text layer
def build_lines(block):
    items = []
    for ln in block["lines"]:
        if abs(ln["dir"][0] - 1) > 1e-3:  # rotated text
            continue
        spans = [s for s in ln["spans"] if s["text"].strip()]
        if spans:
            items.append([fitz.Rect(ln["bbox"]), spans])
    items.sort(key=lambda it: (round(it[0].y0, 1), it[0].x0))
    merged = []
    for r, sp in items:
        size = max(s["size"] for s in sp)
        for m in reversed(merged[-3:]):
            a = m[0]
            ov = min(a.y1, r.y1) - max(a.y0, r.y0)
            near = r.x0 - a.x1 < 4 * size and a.x0 - r.x1 < 4 * size
            if ov > 0.5 * min(a.height, r.height) and near:
                m[0] = a | r
                m[1].extend(sp)
                break
        else:
            merged.append([fitz.Rect(r), list(sp)])
    lines = []
    for r, sp in merged:
        sp.sort(key=lambda s: s["bbox"][0])
        txt, prev = "", None
        for s in sp:
            t = clean(s["text"])
            if prev is not None:
                gap = s["bbox"][0] - prev["bbox"][2]
                if gap > 0.15 * s["size"] and not txt.endswith(" ") and not t.startswith(" "):
                    txt += " "
            txt += t
            prev = s
        sizes, colors, total, bold = Counter(), Counter(), 0, 0
        for s in sp:
            n = len(s["text"].strip())
            sizes[round(s["size"], 1)] += n
            colors[s["color"]] += n
            total += n
            if span_bold(s):
                bold += n
        lines.append(dict(bbox=r, text=re.sub(r"\s+", " ", txt).strip(), size=sizes.most_common(1)[0][0],
                          max_size=max(sizes), bold=bold > 0.6 * total, color=colors.most_common(1)[0][0]))
    lines.sort(key=lambda L: (L["bbox"].y0, L["bbox"].x0))
    return lines


def split_paragraphs(lines):
    if not lines:
        return []
    bx0 = min(L["bbox"].x0 for L in lines)
    bx1 = max(L["bbox"].x1 for L in lines)
    justified = sum(1 for L in lines if L["bbox"].x0 - bx0 < 2) / len(lines) >= 0.5
    paras, cur = [], [lines[0]]
    for prev, L in zip(lines, lines[1:]):
        size = max(prev["size"], L["size"])
        gap = L["bbox"].y0 - prev["bbox"].y1
        ends = prev["text"].endswith(END_PUNCT)
        short_prev = prev["bbox"].x1 < bx1 - 2.5 * size
        new = (gap > 0.5 * size or abs(L["size"] - prev["size"]) > 0.8 or L["bold"] != prev["bold"]
               or (justified and L["bbox"].x0 - bx0 > 0.6 * size and (ends or short_prev))
               or (justified and ends and short_prev)
               or (ends and BULLET_RE.match(L["text"]) is not None))
        if new:
            paras.append(cur)
            cur = [L]
        else:
            cur.append(L)
    paras.append(cur)
    return paras


def join_lines(texts):
    out = ""
    for t in texts:
        t = t.strip()
        if not out:
            out = t
        elif out.endswith("-") and len(out) > 1 and out[-2].isalpha() and t[:1].islower():
            out = out[:-1] + t
        elif CJK.search(out[-1:]) or CJK.match(t[:1]):
            out += t
        else:
            out += " " + t
    return out


def make_para(lines, pno, page_w):
    bbox = fitz.Rect(lines[0]["bbox"])
    for L in lines[1:]:
        bbox |= L["bbox"]
    sizes, colors = Counter(), Counter()
    for L in lines:
        sizes[L["size"]] += len(L["text"])
        colors[L["color"]] += len(L["text"])
    mid = (bbox.x0 + bbox.x1) / 2
    if len(lines) > 1:
        centered = all(abs((L["bbox"].x0 + L["bbox"].x1) / 2 - mid) < 2.5 for L in lines) and \
            any(L["bbox"].x0 - bbox.x0 > 3 for L in lines)
    else:
        centered = abs(mid - page_w / 2) < 4 and bbox.width < 0.75 * page_w
    text = join_lines([L["text"] for L in lines])
    bold = all(L["bold"] for L in lines)
    size = sizes.most_common(1)[0][0]
    if len(lines) <= 2 and (bold or text.upper() == text):
        size = max(L["max_size"] for L in lines)
    return dict(kind="text", page=pno, lines=lines, bbox=bbox, text=text, size=size, bold=bold,
                color=colors.most_common(1)[0][0], centered=centered)


def drop_line_numbers(blocks):
    """Manuscripts with margin line numbers (1, 2, 3 ... in a vertical strip): remove those spans,
    otherwise they get merged into the text lines and end up inside the translation."""
    cols = {}
    for b in blocks:
        if b["type"] != 0:
            continue
        for ln in b["lines"]:
            for s in ln["spans"]:
                if re.fullmatch(r"\s*\d{1,3}\s*", s["text"]):
                    cols.setdefault(round(s["bbox"][0] / 6), []).append(s)
    marked = set()
    for spans in cols.values():
        if len(spans) >= 8:
            nums = [int(s["text"]) for s in sorted(spans, key=lambda s: s["bbox"][1])]
            rising = sum(1 for a, b in zip(nums, nums[1:]) if b > a)
            if rising >= 0.7 * (len(nums) - 1):
                marked.update(id(s) for s in spans)
    if marked:
        for b in blocks:
            if b["type"] == 0:
                for ln in b["lines"]:
                    ln["spans"] = [s for s in ln["spans"] if id(s) not in marked]
    return blocks


def merge_fragment_blocks(groups):
    """Some PDFs (e.g. manuscripts with line numbers) put every text line in its own block.
    Re-join a small block to the previous one when it continues the same column."""
    merged = []
    for lines in groups:
        if not lines:
            continue
        if merged and len(lines) <= 2:
            a, b = merged[-1][-1], lines[0]
            size = max(a["size"], b["size"])
            gap = b["bbox"].y0 - a["bbox"].y1
            ov = min(a["bbox"].x1, b["bbox"].x1) - max(a["bbox"].x0, b["bbox"].x0)
            if (-0.3 * size <= gap <= 0.6 * size and ov > 0.5 * min(a["bbox"].width, b["bbox"].width)
                    and abs(a["size"] - b["size"]) <= 0.5 and abs(a["bbox"].x0 - b["bbox"].x0) < 3 * size):
                merged[-1].extend(lines)
                continue
        merged.append(list(lines))
    return merged


def analyze(doc, pages):
    flags = fitz.TEXTFLAGS_DICT & ~fitz.TEXT_PRESERVE_IMAGES
    out, size_counter = {}, Counter()
    for pno in pages:
        page = doc[pno]
        paras = []
        blocks = drop_line_numbers(page.get_text("dict", flags=flags)["blocks"])
        groups = merge_fragment_blocks([build_lines(b) for b in blocks if b["type"] == 0])
        for lines in groups:
            for grp in split_paragraphs(lines):
                paras.append(make_para(grp, pno, page.rect.width))
        for p in paras:
            for L in p["lines"]:
                size_counter[L["size"]] += len(L["text"])
        out[pno] = paras
    body = size_counter.most_common(1)[0][0] if size_counter else 10
    return out, body


def reading_key(p, page_w):
    return (p["page"], 1 if p["bbox"].x0 >= page_w * 0.45 else 0, p["bbox"].y0)


def find_refs_start(doc, analysis):
    for pno in sorted(analysis):
        w = doc[pno].rect.width
        for p in sorted(analysis[pno], key=lambda q: reading_key(q, w)):
            norm = re.sub(r"[\s\d.IVX]+", "", p["text"]).lower()
            if len(p["text"]) < 40 and norm in REF_HEADS:
                return reading_key(p, w)
    return None


def classify(p, page, body, tables, figures, refs_key):
    t, b = p["text"], p["bbox"]
    W, H = page.rect.width, page.rect.height
    if not t:
        return "empty"
    if refs_key is not None and reading_key(p, W) > refs_key:
        return "references"
    nonspace = [c for c in t if not c.isspace()]
    if any(ord(c) < 32 or 0xE000 <= ord(c) <= 0xF8FF or c in "�\\" for c in t):
        return "math/garbled"
    if sum(1 for c in nonspace if c.isalpha()) < 0.55 * len(nonspace):
        return "math/symbols"
    words = re.findall(r"[A-Za-z]+", t)
    singles = [w for w in words if len(w) == 1 and w not in ("a", "A", "I")]
    if len(singles) >= 4 and len(singles) > 0.12 * len(words):
        return "math/inline"
    if re.search(r"[\^=_|]", t) and len(re.findall(r"[A-Za-z]{3,}", t)) < 6 and not CJK.search(t):
        return "math/fragment"
    if b.y1 < 0.06 * H or b.y0 > 0.945 * H:
        return "header/footer"
    barea = max(area(b), 1e-3)
    if any(area(b & tb) > 0.5 * barea for tb in tables):
        return "table"
    if any(area(b & fg) > 0.5 * barea for fg in figures):
        return "figure"
    n_words = len(re.findall(r"[A-Za-z]{2,}", t)) + len(CJK.findall(t)) // 2
    heading = p["bold"] or p["size"] > body + 0.8 or (t.isupper() and len(t) < 100)
    if p["size"] < 0.8 * body and n_words < 5:
        return "label"
    if n_words >= 3 or (heading and n_words >= 1):
        return "ok"
    return "label"


def figure_rects(page):
    rects = []
    for info in page.get_image_info():
        r = fitz.Rect(info["bbox"])
        if area(r) > 2000:
            rects.append(r)
    return rects


def table_rects(page):
    try:
        return [fitz.Rect(t.bbox) for t in page.find_tables().tables]
    except Exception:
        return []


def is_scanned(page):
    text = page.get_text("text").strip()
    if len(text) >= 40:
        return False
    cover = sum(area(r & page.rect) for r in figure_rects(page))
    return cover > 0.4 * area(page.rect)


def group_continuations(doc, paras, body):
    order = sorted(paras, key=lambda q: reading_key(q, doc[q["page"]].rect.width))
    units, last_body = [], None
    for p in order:
        is_body = p["size"] >= 0.9 * body
        if is_body and last_body is not None:
            prev = last_body[-1]
            if (not prev["text"].endswith(END_PUNCT) and p["text"][:1].islower()
                    and not prev["bold"] and not p["bold"]):
                last_body.append(p)
                continue
        unit = [p]
        units.append(unit)
        if is_body:
            last_body = unit
    return units


def split_translation(tr, parts):
    if len(parts) == 1:
        return [tr]
    total = sum(len(t) for t in parts)
    out, start, acc = [], 0, 0
    for t in parts[:-1]:
        acc += len(t)
        target = round(len(tr) * acc / total)
        win = max(6, len(tr) // 10)
        best = None
        for i in range(max(start + 1, target - win), min(len(tr) - 1, target + win) + 1):
            if tr[i - 1] in "，。；：、）”,.;: " and (best is None or abs(i - target) < abs(best - target)):
                best = i
        if best is None:
            best = min(max(target, start + 1), len(tr) - 1)
            while best < len(tr) - 1 and tr[best - 1].isalnum() and tr[best].isalnum() and tr[best].isascii():
                best += 1
        out.append(tr[start:best].strip())
        start = best
    out.append(tr[start:].strip())
    return out


# ------------------------------------------------------------------ OCR pages
def ocr_paragraphs(page, pno, languages, tmpdir):
    dpi = 200
    pix = page.get_pixmap(dpi=dpi)
    png = os.path.join(tmpdir, f"p{pno}.png")
    pix.save(png)
    data = ocr.recognize(png, os.path.join(tmpdir, f"p{pno}_n.png"), languages)
    return paragraphs_from_ocr(data, pix, page.rect.width / data["width"], pno)


def save(doc, path):
    try:
        doc.subset_fonts()
    except Exception:
        pass
    doc.save(path, garbage=4, deflate=True)


def open_as_pdf(path):
    src = fitz.open(path)
    if src.is_pdf:
        return src
    return fitz.open("pdf", src.convert_to_pdf())


# ------------------------------------------------------------------ main entry
def translate(path, out_dir, engine, tgt="zh", mode="dual", report=None, log=print,
              ocr_mode="auto", ocr_languages=None, pages=None, **_):
    report = report or (lambda *a: None)
    orig = open_as_pdf(path)
    trans = fitz.open("pdf", orig.tobytes())
    pages = list(range(len(orig))) if pages is None else pages
    report("分析版面", 0, len(pages))
    analysis, body = analyze(orig, range(len(orig)))
    refs_key = find_refs_start(orig, analysis)
    plan, reasons = {}, Counter()
    with tempfile.TemporaryDirectory() as tmp:
        for i, pno in enumerate(pages):
            page = orig[pno]
            if ocr_mode == "force" or (ocr_mode == "auto" and is_scanned(page)):
                paras = [p for p in ocr_paragraphs(page, pno, ocr_languages or ["en-US", "zh-Hans"], tmp)
                         if has_letters(p["text"])]
                reasons["ocr"] += len(paras)
                plan[pno] = paras
            else:
                tables, figures = table_rects(page), figure_rects(page)
                keep = []
                for p in analysis[pno]:
                    why = classify(p, page, body, tables, figures, refs_key)
                    reasons[why] += 1
                    if why == "ok":
                        keep.append(p)
                plan[pno] = keep
            report("分析版面", i + 1, len(pages))
    text_paras = [p for ps in plan.values() for p in ps if p["kind"] == "text"]
    units = group_continuations(orig, text_paras, body) + \
        [[p] for ps in plan.values() for p in ps if p["kind"] == "ocr"]
    unit_texts = [join_lines([p["text"] for p in u]) for u in units]
    log(f"  段落：{dict(reasons)}；跨栏合并 {sum(len(u) - 1 for u in units)} 处")
    results = engine.translate_many(unit_texts, tgt, progress=lambda d, n: report("翻译", d, n))
    tr_of = {}
    for u, res in zip(units, results):
        if res:
            for p, part in zip(u, split_translation(res, [p["text"] for p in u])):
                tr_of[id(p)] = part
    report("排版", 0, len(pages))
    archive, font_css = font_setup(tgt)
    failed = 0
    for i, pno in enumerate(pages):
        items = []
        for p in plan[pno]:
            if tr_of.get(id(p)):
                items.append((p, tr_of[id(p)]))
            else:
                failed += 1
        render_page(trans[pno], items, archive, font_css, tgt)
        report("排版", i + 1, len(pages))
    outputs = []
    mono = fitz.open()
    for pno in pages:
        mono.insert_pdf(trans, from_page=pno, to_page=pno)
    mono_path = out_path(path, out_dir, tgt, ".pdf")
    save(mono, mono_path)
    outputs.append(mono_path)
    if mode in ("dual", "both"):
        dual = fitz.open()
        for pno in pages:
            add_dual_page(dual, orig, trans, pno)
        dual_path = out_path(path, out_dir, tgt, ".pdf", dual=True)
        save(dual, dual_path)
        outputs.insert(0, dual_path)
    if failed:
        log(f"  有 {failed} 段未能翻译，已保留原文")
    return outputs
