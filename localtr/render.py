"""Writing translations onto pages: fonts, painting over original text, side-by-side pages.

Shared by pdf.py (text and scanned pages) and image.py. Paragraph dicts carry kind ("text" or
"ocr"), page, lines (each with bbox, and bg for OCR lines), bbox, text, size, bold, centered, color.
"""
import html
import os

import fitz

from . import ocr

WORD_FONTS = "/Applications/Microsoft Word.app/Contents/Resources/DFonts"
SUPP_FONTS = "/System/Library/Fonts/Supplemental"


def bg_color(pix, box):
    x0, y0, x1, y1 = [int(v) for v in box]
    pts = []
    for x in range(max(0, x0 - 3), min(pix.width, x1 + 3), max(1, (x1 - x0) // 20 or 1)):
        for y in (y0 - 3, y1 + 2):
            if 0 <= y < pix.height:
                pts.append(pix.pixel(x, y))
    for y in range(max(0, y0), min(pix.height, y1), max(1, (y1 - y0) // 4 or 1)):
        for x in (x0 - 3, x1 + 2):
            if 0 <= x < pix.width:
                pts.append(pix.pixel(x, y))
    if not pts:
        return (1, 1, 1)
    chans = list(zip(*pts))[:3]
    return tuple(sorted(c)[len(c) // 2] / 255 for c in chans)


def paragraphs_from_ocr(data, pix, scale, pno=0):
    """OCR result (pixel boxes) -> paragraph dicts in page coordinates (pixels * scale)."""
    groups = ocr.group_lines(data["lines"])
    hs = sorted(g["line_h"] for g in groups) or [12]
    median_h = hs[len(hs) // 2]
    paras = []
    for g in groups:
        line_h = g["line_h"]
        if not (len(g["lines"]) == 1 and line_h > 1.6 * median_h and len(g["text"]) < 80):
            line_h = min(line_h, 1.25 * median_h)  # cap odd tall boxes; keep real headings large
        lines = []
        for ln in g["lines"]:
            lines.append({"bbox": fitz.Rect([v * scale for v in ln["box"]]), "bg": bg_color(pix, ln["box"])})
        bg = lines[0]["bg"]
        lum = 0.299 * bg[0] + 0.587 * bg[1] + 0.114 * bg[2]
        size = max(5.0, line_h * scale * 0.78)
        paras.append(dict(kind="ocr", page=pno, lines=lines, bbox=fitz.Rect([v * scale for v in g["box"]]),
                          text=g["text"], size=size, bold=False, centered=False,
                          color=0x111111 if lum > 0.55 else 0xFFFFFF))
    return paras


def font_setup(tgt):
    if tgt.startswith("zh") and os.path.exists(os.path.join(WORD_FONTS, "Deng.ttf")):
        css = ("@font-face {font-family: tr; src: url(Deng.ttf);} "
               "@font-face {font-family: tr; font-weight: bold; src: url(Dengb.ttf);} ")
        return fitz.Archive(WORD_FONTS), css
    if os.path.exists(os.path.join(SUPP_FONTS, "Arial Unicode.ttf")):
        return fitz.Archive(SUPP_FONTS), '@font-face {font-family: tr; src: url("Arial Unicode.ttf");} '
    return None, ""


def hex_color(c):
    return f"{(c >> 16) & 255:02x}{(c >> 8) & 255:02x}{c & 255:02x}"


def render_page(page, items, archive, font_css, tgt):
    text_items = [(p, t) for p, t in items if p["kind"] == "text"]
    for p, _ in text_items:
        for L in p["lines"]:
            r = L["bbox"]
            inset = r.height * 0.2
            page.add_redact_annot(fitz.Rect(r.x0 - 0.3, r.y0 + inset, r.x1 + 0.3, r.y1 - inset))
    if text_items:
        page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE, graphics=fitz.PDF_REDACT_LINE_ART_NONE)
    for p, _ in items:
        if p["kind"] == "ocr":
            for L in p["lines"]:
                r = L["bbox"]
                page.draw_rect(fitz.Rect(r.x0 - 1, r.y0 - 1, r.x1 + 1, r.y1 + 1), color=None, fill=L["bg"], overlay=True)
    scales = []
    cjk_target = tgt.startswith(("zh", "ja", "ko"))
    for p, tr in items:
        b = p["bbox"]
        rect = fitz.Rect(b.x0, b.y0, b.x1 + 1, max(b.y1 + 1, b.y0 + 1.45 * p["size"]))
        align = "center" if p["centered"] else ("justify" if len(p["lines"]) > 1 else "left")
        size = p["size"] * (0.92 if cjk_target else 0.95)
        css = font_css + "* {font-family: tr, sans-serif; margin: 0; padding: 0;} " + (
            f"p {{margin: 0; padding: 0; font-size: {size:.2f}px; line-height: {1.28 if cjk_target else 1.15}; "
            f"color: #{hex_color(p['color'])}; text-align: {align}; font-weight: {'bold' if p['bold'] else 'normal'};}}")
        _, scale = page.insert_htmlbox(rect, f"<p>{html.escape(tr)}</p>", css=css, archive=archive, scale_low=0)
        scales.append(scale)
    return scales


def add_dual_page(out, orig, trans, pno):
    r = orig[pno].rect
    w, h = r.width, r.height
    page = out.new_page(width=2 * w, height=h)
    page.show_pdf_page(fitz.Rect(0, 0, w, h), orig, pno)
    page.show_pdf_page(fitz.Rect(w, 0, 2 * w, h), trans, pno)
    page.draw_line((w, 0), (w, h), color=(0.7, 0.7, 0.7), width=0.5)
