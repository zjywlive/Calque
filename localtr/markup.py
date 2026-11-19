"""EPUB and HTML translation: block elements are translated in place.

Bilingual mode adds the translation right after each paragraph/heading (inside the same cell or
list item for li/td/th), styled with .lt-tr; translation-only mode replaces the text.
EPUB stays a valid, reflowable EPUB (mimetype stored first).
"""
import html
import posixpath
import re
import urllib.parse
import zipfile

from .textutil import esc, needs_translation, out_path

BLOCK = "p|h[1-6]|li|blockquote|figcaption|dt|dd|td|th|caption|summary"
BLOCK_RE = re.compile(rf"<({BLOCK})(\s[^>]*)?>((?:(?!<(?:{BLOCK})[\s>/]).)*?)</\1\s*>", re.S | re.I)
INSIDE = {"li", "td", "th", "dt", "dd", "caption", "summary"}
TAG_RE = re.compile(r"<[^>]+>")
STYLE = "<style>.lt-tr{color:#3a5a8c}</style>"


def text_of(inner):
    if re.search(r"<(pre|code|script|style)\b", inner, re.I):
        return ""
    return re.sub(r"\s+", " ", html.unescape(TAG_RE.sub("", inner))).strip()


def collect(doc):
    return [(m, text_of(m.group(3))) for m in BLOCK_RE.finditer(doc)]


def rebuild(doc, found, trs, mode):
    out, pos = [], 0
    for (m, _), tr in zip(found, trs):
        out.append(doc[pos:m.start()])
        tag, attrs, inner = m.group(1), m.group(2) or "", m.group(3)
        if not tr:
            out.append(m.group(0))
        elif mode == "dual":
            if tag.lower() in INSIDE:
                out.append(f"<{tag}{attrs}>{inner}<br/><span class=\"lt-tr\">{esc(tr)}</span></{tag}>")
            else:
                copy_attrs = re.sub(r'\s(id|name)="[^"]*"', "", attrs)
                out.append(m.group(0) + f"\n<{tag}{copy_attrs}><span class=\"lt-tr\">{esc(tr)}</span></{tag}>")
        else:
            out.append(f"<{tag}{attrs}>{esc(tr)}</{tag}>")
        pos = m.end()
    out.append(doc[pos:])
    result = "".join(out)
    if mode == "dual" and "lt-tr{" not in result:
        result = re.sub(r"</head>", STYLE + "</head>", result, count=1, flags=re.I)
    return result


def _decode(raw):
    m = re.search(rb'charset=["\']?([\w-]+)', raw[:2000])
    for enc in ([m.group(1).decode()] if m else []) + ["utf-8", "gb18030", "latin-1"]:
        try:
            return raw.decode(enc), enc
        except (LookupError, UnicodeDecodeError):
            continue
    return raw.decode("utf-8", "replace"), "utf-8"


def _translate_docs(docs, engine, tgt, mode, report):
    """docs: {name: text}. Returns {name: new_text}."""
    found = {n: collect(d) for n, d in docs.items()}
    flat = [t for n in docs for _, t in found[n]]
    wanted = [t if needs_translation(t) else "" for t in flat]
    trs = engine.translate_many(wanted, tgt, progress=lambda d, n: report("翻译", d, n))
    out, i = {}, 0
    for n, d in docs.items():
        k = len(found[n])
        out[n] = rebuild(d, found[n], trs[i:i + k], mode)
        i += k
    return out


def translate_html(path, out_dir, engine, tgt="zh", mode="dual", report=None, log=print, **_):
    report = report or (lambda *a: None)
    with open(path, "rb") as f:
        text, enc = _decode(f.read())
    new = _translate_docs({"doc": text}, engine, tgt, mode, report)["doc"]
    out = out_path(path, out_dir, tgt, dual=mode == "dual")
    with open(out, "w", encoding=enc, errors="xmlcharrefreplace") as f:
        f.write(new)
    return [out]


def translate_epub(path, out_dir, engine, tgt="zh", mode="dual", report=None, log=print, **_):
    report = report or (lambda *a: None)
    with zipfile.ZipFile(path) as z:
        container = z.read("META-INF/container.xml").decode("utf-8", "replace")
        opf_path = re.search(r'full-path="([^"]+)"', container).group(1)
        opf = z.read(opf_path).decode("utf-8", "replace")
        base = posixpath.dirname(opf_path)
        names = []
        for item in re.findall(r"<item\b[^>]*>", opf):
            mt = re.search(r'media-type="([^"]+)"', item)
            href = re.search(r'href="([^"]+)"', item)
            if mt and href and mt.group(1) in ("application/xhtml+xml", "text/html"):
                names.append(posixpath.normpath(posixpath.join(base, urllib.parse.unquote(href.group(1)))))
        docs = {}
        for n in names:
            if n in z.namelist():
                docs[n] = _decode(z.read(n))[0]
        new = _translate_docs(docs, engine, tgt, mode, report)
        out = out_path(path, out_dir, tgt, ".epub", dual=mode == "dual")
        with zipfile.ZipFile(out, "w") as zo:
            if "mimetype" in z.namelist():
                zo.writestr(zipfile.ZipInfo("mimetype"), z.read("mimetype"), compress_type=zipfile.ZIP_STORED)
            for info in z.infolist():
                if info.filename == "mimetype":
                    continue
                data = new[info.filename].encode("utf-8") if info.filename in new else z.read(info.filename)
                zo.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED)
    return [out]
