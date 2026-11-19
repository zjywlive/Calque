"""Images (PNG/JPG/HEIC/TIFF/BMP/GIF/WebP): on-device OCR, paint over the text, write the translation."""
import os
import tempfile

import fitz

from . import ocr
from .render import add_dual_page, font_setup, paragraphs_from_ocr, render_page
from .textutil import has_letters, out_path


def translate(path, out_dir, engine, tgt="zh", mode="dual", report=None, log=print, ocr_languages=None, **_):
    report = report or (lambda *a: None)
    with tempfile.TemporaryDirectory() as tmp:
        norm = os.path.join(tmp, "norm.png")
        report("文字识别", 0, 1)
        data = ocr.recognize(path, norm, ocr_languages or ["en-US", "zh-Hans"])
        report("文字识别", 1, 1)
        pix = fitz.Pixmap(norm)
        if pix.alpha:
            pix = fitz.Pixmap(pix, 0)
        paras = [p for p in paragraphs_from_ocr(data, pix, 1.0) if has_letters(p["text"])]
        trs = engine.translate_many([p["text"] for p in paras], tgt, progress=lambda d, n: report("翻译", d, n))
        W, H = data["width"], data["height"]
        src = fitz.open()
        src.new_page(width=W, height=H).insert_image(fitz.Rect(0, 0, W, H), filename=norm)
        trans = fitz.open("pdf", src.tobytes())
        archive, css = font_setup(tgt)
        render_page(trans[0], [(p, t) for p, t in zip(paras, trs) if t], archive, css, tgt)
        outs = []
        mono = out_path(path, out_dir, tgt, ".png")
        trans[0].get_pixmap(dpi=72).save(mono)
        outs.append(mono)
        if mode == "dual":
            dual = fitz.open()
            add_dual_page(dual, src, trans, 0)
            path_dual = out_path(path, out_dir, tgt, ".png", dual=True)
            dual[0].get_pixmap(dpi=72).save(path_dual)
            outs.insert(0, path_dual)
    if not paras:
        log("  图片中没有识别到可翻译的文字")
    return outs
