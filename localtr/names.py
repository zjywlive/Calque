"""Find personal names and quoted titles in English text, so they can be kept untranslated.

Hy-MT2 ignores free-form instructions such as "keep names in English" but follows its
terminology block strictly, so names are passed as "X 翻译成 X" entries.
"""
import re

_DICT = "/usr/share/dict/words"
try:
    with open(_DICT, encoding="utf-8", errors="ignore") as _f:
        COMMON = {w.strip().lower() for w in _f if w.strip() and w.strip()[0].islower()}
except OSError:
    COMMON = set()

SKIP = {"Fig", "Figure", "Table", "Section", "Eq", "Abstract", "Index", "Terms", "Appendix", "Chapter"}
_SUFFIXES = (("s", ""), ("es", ""), ("ies", "y"), ("ing", ""), ("ing", "e"), ("ed", ""), ("ed", "e"),
             ("ions", "ion"), ("ments", "ment"), ("ers", "er"), ("ly", ""), ("al", ""), ("ic", ""))


def _is_common(word, text):
    low = word.lower()
    forms = {low}
    for suf, rep in _SUFFIXES:
        if low.endswith(suf) and len(low) - len(suf) >= 3:
            forms.add(low[: len(low) - len(suf)] + rep)
    if any(f in COMMON for f in forms):
        return True
    return re.search(r"\b" + re.escape(low), text) is not None  # also appears in lower case


MONTHS_DAYS = {"January", "February", "March", "April", "May", "June", "July", "August", "September",
               "October", "November", "December", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
               "Saturday", "Sunday"}
_UK_US = ((r"tre$", "ter"), (r"our$", "or"), (r"ise$", "ize"), (r"yse$", "yze"), (r"ogue$", "og"))
_COMMON_SUFFIX = re.compile(r"(ics|tion|sion|ment|ness|ity|ology|ance|ence|ship|able|ible|ive|ous)$", re.I)


def _plain_word(word, text):
    if word in SKIP or word in MONTHS_DAYS or _COMMON_SUFFIX.search(word):
        return True
    if _is_common(word, text):
        return True
    low = word.lower()
    return any(re.search(a, low) and re.sub(a, b, low) in COMMON for a, b in _UK_US)


def find_names(text):
    """Personal names in English text. To avoid false positives a candidate is kept only when it looks
    like a name in context: two or more name words ("Yuval Noah Harrari"), "X et al.", "X [12]",
    "X (2019)", or "X and Y" where Y is also a candidate."""
    if not COMMON:
        return []
    toks = re.findall(r"[A-Za-z][A-Za-z'’\-]*\.?|\[|\(|\d+|[^\sA-Za-z\d]", text)
    spans, cur = [], []
    for i, tok in enumerate(toks):
        word = tok.rstrip(".")
        initial = re.fullmatch(r"[A-Z]\.", tok) is not None
        is_name = (re.fullmatch(r"[A-Z][a-z]+(?:[-’'][A-Z]?[a-z]+)?", word) is not None
                   and not _plain_word(word, text))
        if is_name or initial:
            cur.append((i, tok, is_name))
            continue
        if cur:
            spans.append(cur)
            cur = []
    if cur:
        spans.append(cur)
    cands = []
    for sp in spans:
        while sp and not sp[-1][2]:   # drop trailing initials
            sp = sp[:-1]
        while sp and not sp[0][2] and len(sp) > 1 and not sp[1][2] and False:
            sp = sp[1:]
        words = [t for _, t, nm in sp if nm]
        if not words:
            continue
        start, end = sp[0][0], sp[-1][0]
        name = " ".join(t for _, t, _ in sp).rstrip(".")
        after = " ".join(toks[end + 1:end + 3])
        before = toks[start - 1] if start > 0 else ""
        strong = (len(words) >= 2 or len(sp) >= 2 or after.startswith("et al") or after.startswith("[")
                  or re.match(r"\(\s*\d{4}", after) is not None)
        cands.append({"name": name, "start": start, "end": end, "strong": strong, "before": before})
    for a, b in zip(cands, cands[1:]):  # "Lepora and Lloyd"
        if b["start"] - a["end"] == 2 and toks[a["end"] + 1] in ("and", "&"):
            a["strong"] = b["strong"] = True
    out = []
    for c in cands:
        if c["strong"] and len(c["name"]) > 2 and c["name"] not in out:
            out.append(c["name"])
    return out


def find_titles(text):
    """Quoted Title-Case strings, e.g. book or paper titles."""
    found = re.findall(r"[“\"]([A-Z][^”\"]{3,100})[”\"]", text)
    return [t for t in found if len(re.findall(r"\b[A-Z][a-z]+", t)) >= 2]
