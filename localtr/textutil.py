"""Small text and file-naming helpers shared by the format handlers and the engine."""
import os
import re

CJK = re.compile(r"[぀-ヿ一-鿿가-힯]")  # kana, CJK ideographs, hangul
LETTER = re.compile(r"[^\W\d_]")


def needs_translation(text):
    t = text.strip()
    if len(t) < 2:
        return False
    letters = sum(1 for c in t if c.isalpha())
    if letters < 2:
        return False
    if re.fullmatch(r"(https?://|www\.)\S+|[\w.+-]+@[\w-]+\.[\w.]+", t):
        return False
    if re.fullmatch(r"[A-Z0-9][A-Z0-9\-_.]{1,9}", t):  # acronyms / codes: CONV, LSTM, UFMFRR-15-M
        return False
    return True


def has_letters(text, n=2):
    """At least n letters (any script) -- filters OCR noise such as stray digits or symbols."""
    return len(LETTER.findall(text)) >= n


def esc(s):
    """Escape text for XML/HTML element content."""
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def out_path(path, out_dir, tgt, ext=None, dual=False, stem=None):
    """<out_dir>/<stem>.<tgt>[-dual]<ext>; ext defaults to the input's extension. Creates out_dir."""
    s, e = os.path.splitext(os.path.basename(path))
    os.makedirs(out_dir, exist_ok=True)
    return os.path.join(out_dir, f"{stem or s}.{tgt}{'-dual' if dual else ''}{ext or e}")
