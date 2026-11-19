"""Dispatch a file to the right translator by extension."""
import os

from . import image, markup, office, pdf, textfmt

FORMATS = {
    # extension: (handler, label)
    ".pdf": (pdf.translate, "PDF"), ".xps": (pdf.translate, "XPS"), ".oxps": (pdf.translate, "XPS"),
    ".mobi": (pdf.translate, "MOBI"), ".fb2": (pdf.translate, "FB2"), ".cbz": (pdf.translate, "漫画 CBZ"),
    ".docx": (office.translate, "Word"), ".docm": (office.translate, "Word"), ".dotx": (office.translate, "Word"),
    ".doc": (office.translate, "Word 97"), ".rtf": (office.translate, "RTF"), ".rtfd": (office.translate, "RTFD"),
    ".odt": (office.translate, "OpenDocument"), ".wordml": (office.translate, "WordML"),
    ".pptx": (office.translate, "PowerPoint"), ".pptm": (office.translate, "PowerPoint"),
    ".xlsx": (office.translate, "Excel"), ".xlsm": (office.translate, "Excel"),
    ".epub": (markup.translate_epub, "EPUB"),
    ".html": (markup.translate_html, "HTML"), ".htm": (markup.translate_html, "HTML"),
    ".xhtml": (markup.translate_html, "XHTML"),
    ".txt": (textfmt.translate_txt, "文本"), ".md": (textfmt.translate_md, "Markdown"),
    ".markdown": (textfmt.translate_md, "Markdown"),
    ".srt": (textfmt.translate_subtitles, "SRT 字幕"), ".vtt": (textfmt.translate_subtitles, "VTT 字幕"),
}
for _ext in (".png", ".jpg", ".jpeg", ".heic", ".heif", ".tif", ".tiff", ".bmp", ".gif", ".webp"):
    FORMATS[_ext] = (image.translate, "图片（OCR）")


def supported(path):
    return os.path.splitext(path)[1].lower() in FORMATS


def translate_file(path, out_dir, engine, tgt="zh", mode="dual", report=None, log=print, ocr_mode="auto",
                   ocr_languages=None):
    ext = os.path.splitext(path)[1].lower()
    if ext not in FORMATS:
        raise RuntimeError(f"暂不支持 {ext} 格式")
    handler = FORMATS[ext][0]
    # Every handler takes (path, out_dir, engine, tgt, mode, report, log, **_) and ignores options it doesn't use.
    return handler(path, out_dir, engine, tgt, mode, report=report, log=log,
                   ocr_mode=ocr_mode, ocr_languages=ocr_languages)
