"""Word / PowerPoint / Excel translation by rewriting OOXML text runs in place.

Only the text inside <w:t> / <a:t> / <t> elements changes; styles, images, tables, numbering
and everything else stays byte-identical. Paragraph formatting is kept; formatting that differs
inside one paragraph (e.g. a single bold word) collapses to the paragraph's first run.
Bilingual mode inserts the translated paragraph right after the original one
(Excel: "original\\ntranslation" in the same cell).
Legacy .doc/.rtf/.odt are converted to .docx with macOS textutil first.
"""
import html
import os
import re
import subprocess
import tempfile
import zipfile

from .textutil import esc, needs_translation, out_path

W_P = re.compile(r"<w:p\b(?:(?!<w:p\b).)*?</w:p>", re.S)
W_T = re.compile(r"(<w:t(?:\s[^>]*)?>)([^<]*)(</w:t>)")
A_P = re.compile(r"<a:p\b(?:(?!<a:p\b).)*?</a:p>", re.S)
A_T = re.compile(r"(<a:t(?:\s[^>]*)?>)([^<]*)(</a:t>)")
X_SI = re.compile(r"<si>(.*?)</si>|<is>(.*?)</is>", re.S)
X_T = re.compile(r"(<t(?:\s[^>]*)?>)([^<]*)(</t>)")

PARTS = {
    "docx": [(re.compile(r"word/(document|header\d*|footer\d*|footnotes|endnotes|comments)\.xml$"), W_P, W_T)],
    "pptx": [(re.compile(r"ppt/(slides/slide|notesSlides/notesSlide|diagrams/data)\d+\.xml$"), A_P, A_T)],
    "xlsx": [(re.compile(r"xl/sharedStrings\.xml$|xl/worksheets/sheet\d+\.xml$"), X_SI, X_T),
             (re.compile(r"xl/drawings/drawing\d+\.xml$"), A_P, A_T)],
}
LEGACY_WORD = {".doc", ".rtf", ".rtfd", ".odt", ".wordml", ".webarchive"}


def _unesc(s):
    return html.unescape(s)


def _preserve(open_tag):
    if "xml:space" in open_tag:
        return open_tag
    return open_tag[:-1] + ' xml:space="preserve">'


def _fill(block, t_re, new_text):
    """Put new_text into the first text element of block, empty the others."""
    state = {"first": True}

    def repl(m):
        if state["first"]:
            state["first"] = False
            return _preserve(m.group(1)) + esc(new_text) + m.group(3)
        return m.group(1) + m.group(3)
    return t_re.sub(repl, block)


def _dual_copy(block):
    block = re.sub(r"<w:bookmark(Start|End)\b[^>]*/>", "", block)
    block = re.sub(r"<w:numPr>.*?</w:numPr>", "", block, flags=re.S)
    block = re.sub(r'\sw14:(paraId|textId)="[^"]*"', "", block)
    return block


AUTOFIT = '<a:normAutofit fontScale="70000" lnSpcReduction="10000"/>'


def _autofit(xml):
    """Bilingual slides hold twice the text: ask PowerPoint to shrink text to fit its box."""
    xml = re.sub(r"<a:(normAutofit|spAutoFit|noAutofit)\b[^>]*/>", AUTOFIT, xml)
    xml = re.sub(r"<a:normAutofit\b[^>]*>.*?</a:normAutofit>", AUTOFIT, xml, flags=re.S)
    xml = re.sub(r"<a:bodyPr\b([^>]*)/>", r"<a:bodyPr\1>" + AUTOFIT + "</a:bodyPr>", xml)

    def fix(m):
        attrs, inner = m.group(1), m.group(2)
        if "Autofit" in inner or "AutoFit" in inner:
            return m.group(0)
        warp = re.search(r"<a:prstTxWarp\b.*?(?:/>|</a:prstTxWarp>)", inner, flags=re.S)
        if warp:
            inner = inner[:warp.end()] + AUTOFIT + inner[warp.end():]
        else:
            inner = AUTOFIT + inner
        return f"<a:bodyPr{attrs}>{inner}</a:bodyPr>"
    return re.sub(r"<a:bodyPr\b([^>]*)>(.*?)</a:bodyPr>", fix, xml, flags=re.S)


def _texts(block, t_re):
    block = re.sub(r"<rPh\b.*?</rPh>", "", block, flags=re.S)  # Excel phonetic runs
    return "".join(_unesc(m.group(2)) for m in t_re.finditer(block))


def translate_ooxml(path, out_dir, engine, kind, tgt="zh", mode="dual", report=None, log=print, stem=None):
    report = report or (lambda *a: None)
    specs = PARTS[kind]
    with zipfile.ZipFile(path) as zin:
        names = zin.namelist()
        xml = {}
        items = []  # (part, start, end, text, t_re, excel)
        for name in names:
            for part_re, p_re, t_re in specs:
                if not part_re.search(name):
                    continue
                data = zin.read(name).decode("utf-8")
                xml[name] = data
                for m in p_re.finditer(data):
                    text = _texts(m.group(0), t_re).strip()
                    if needs_translation(text):
                        items.append((name, m.start(), m.end(), text, t_re, p_re is X_SI))
                break
        report("翻译", 0, len(items))
        trs = engine.translate_many([it[3] for it in items], tgt, progress=lambda d, n: report("翻译", d, n))
        by_part = {}
        for it, tr in zip(items, trs):
            if tr:
                by_part.setdefault(it[0], []).append((it, tr))
        new = {}
        for name, lst in by_part.items():
            data = xml[name]
            for (part, s, e, text, t_re, excel), tr in sorted(lst, key=lambda x: -x[0][1]):
                block = re.sub(r"<rPh\b.*?</rPh>", "", data[s:e], flags=re.S)
                if excel:
                    rep = _fill(block, t_re, (text + "\n" + tr) if mode == "dual" else tr)
                elif mode == "dual":
                    rep = block + _dual_copy(_fill(block, t_re, tr))
                else:
                    rep = _fill(block, t_re, tr)
                data = data[:s] + rep + data[e:]
            if kind == "pptx" and mode == "dual" and "/slides/slide" in name:
                data = _autofit(data)
            new[name] = data.encode("utf-8")
        dst = out_path(path, out_dir, tgt, "." + kind, dual=mode == "dual", stem=stem)
        with zipfile.ZipFile(dst, "w") as zout:
            for info in zin.infolist():
                zout.writestr(info, new.get(info.filename, zin.read(info.filename)))
    missing = sum(1 for t in trs if not t)
    if missing:
        log(f"  有 {missing} 段未能翻译，已保留原文")
    return [dst]


def translate(path, out_dir, engine, tgt="zh", mode="dual", report=None, log=print, **_):
    ext = os.path.splitext(path)[1].lower()
    if ext in (".docx", ".docm", ".dotx"):
        return translate_ooxml(path, out_dir, engine, "docx", tgt, mode, report, log)
    if ext in (".pptx", ".pptm", ".potx"):
        return translate_ooxml(path, out_dir, engine, "pptx", tgt, mode, report, log)
    if ext in (".xlsx", ".xlsm", ".xltx"):
        return translate_ooxml(path, out_dir, engine, "xlsx", tgt, mode, report, log)
    if ext in LEGACY_WORD:
        with tempfile.TemporaryDirectory() as tmp:
            conv = os.path.join(tmp, "converted.docx")
            p = subprocess.run(["textutil", "-convert", "docx", "-output", conv, path], capture_output=True, text=True)
            if p.returncode != 0 or not os.path.exists(conv):
                raise RuntimeError("无法转换为 docx：" + (p.stderr or "")[-200:])
            stem = os.path.splitext(os.path.basename(path))[0]
            return translate_ooxml(conv, out_dir, engine, "docx", tgt, mode, report, log, stem=stem)
    if ext in (".ppt", ".xls"):
        raise RuntimeError("旧版 .ppt/.xls 请先在 PowerPoint/Excel 中另存为 .pptx/.xlsx 再翻译。")
    raise RuntimeError(f"不支持的格式：{ext}")
