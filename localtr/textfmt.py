"""Plain text, Markdown and subtitles (SRT / VTT)."""
import re

from .textutil import CJK, out_path


def _read(path):
    raw = open(path, "rb").read()
    for enc in ("utf-8-sig", "gb18030", "utf-16", "latin-1"):
        try:
            return raw.decode(enc), ("utf-8" if enc == "utf-8-sig" else enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace"), "utf-8"


def _join(lines):
    out = ""
    for l in (x.strip() for x in lines):
        if not out:
            out = l
        elif CJK.search(out[-1:]) or CJK.match(l[:1]):
            out += l
        elif out.endswith("-") and l[:1].islower():
            out = out[:-1] + l
        else:
            out += " " + l
    return out


def translate_txt(path, out_dir, engine, tgt="zh", mode="dual", report=None, log=print, **_):
    report = report or (lambda *a: None)
    text, enc = _read(path)
    blocks = re.split(r"\n\s*\n", text.replace("\r\n", "\n"))
    srcs = [_join(b.split("\n")) for b in blocks]
    trs = engine.translate_many(srcs, tgt, progress=lambda d, n: report("翻译", d, n))
    parts = []
    for b, tr in zip(blocks, trs):
        if not tr:
            parts.append(b)
        elif mode == "dual":
            parts.append(b.rstrip() + "\n" + tr)
        else:
            parts.append(tr)
    out = out_path(path, out_dir, tgt, dual=mode == "dual")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n\n".join(parts))
    return [out]


MD_PREFIX = re.compile(r"^(\s*(?:#{1,6}\s+|[-*+]\s+(?:\[[ xX]\]\s+)?|\d+[.)]\s+|>\s*)+)(.*)$")


def translate_md(path, out_dir, engine, tgt="zh", mode="dual", report=None, log=print, **_):
    report = report or (lambda *a: None)
    lines = _read(path)[0].replace("\r\n", "\n").split("\n")
    units = []  # (kind, payload)
    i, fence = 0, False
    para = []

    def flush():
        if para:
            units.append(("para", list(para)))
            para.clear()
    while i < len(lines):
        ln = lines[i]
        if ln.strip().startswith(("```", "~~~")):
            flush()
            fence = not fence
            units.append(("raw", ln))
        elif fence or not ln.strip() or re.match(r"^\s*([-*_]\s*){3,}$", ln) or ln.lstrip().startswith(("<", "![")):
            flush()
            units.append(("raw", ln))
        elif ln.lstrip().startswith("|"):
            flush()
            units.append(("table", ln))
        elif MD_PREFIX.match(ln) and MD_PREFIX.match(ln).group(1).strip():
            flush()
            units.append(("prefixed", ln))
        else:
            para.append(ln)
        i += 1
    flush()
    srcs = []
    for kind, p in units:
        if kind == "para":
            srcs.append(_join(p))
        elif kind == "prefixed":
            srcs.append(MD_PREFIX.match(p).group(2))
        elif kind == "table":
            cells = [c.strip() for c in p.strip().strip("|").split("|")]
            srcs.extend(c for c in cells if not re.fullmatch(r":?-{2,}:?", c))
    trs = iter(engine.translate_many(srcs, tgt, progress=lambda d, n: report("翻译", d, n)))
    out = []
    for kind, p in units:
        if kind == "raw":
            out.append(p)
        elif kind == "para":
            tr = next(trs)
            if not tr:
                out.extend(p)
            elif mode == "dual":
                out.extend(p + [""] + [tr])
            else:
                out.append(tr)
        elif kind == "prefixed":
            m = MD_PREFIX.match(p)
            tr = next(trs)
            if not tr:
                out.append(p)
            elif mode == "dual":
                if m.group(1).lstrip().startswith("#"):
                    out.extend([p, "", m.group(1) + tr])
                else:
                    out.extend([p + "  ", " " * len(m.group(1)) + tr])
            else:
                out.append(m.group(1) + tr)
        else:  # table row
            cells = [c.strip() for c in p.strip().strip("|").split("|")]
            new = []
            for c in cells:
                if re.fullmatch(r":?-{2,}:?", c):
                    new.append(c)
                    continue
                tr = next(trs)
                new.append(c if not tr else (f"{c}<br>{tr}" if mode == "dual" else tr))
            out.append("| " + " | ".join(new) + " |")
    dst = out_path(path, out_dir, tgt, dual=mode == "dual")
    with open(dst, "w", encoding="utf-8") as f:
        f.write("\n".join(out))
    return [dst]


def translate_subtitles(path, out_dir, engine, tgt="zh", mode="dual", report=None, log=print, **_):
    report = report or (lambda *a: None)
    text = _read(path)[0].replace("\r\n", "\n")
    blocks = re.split(r"\n\s*\n", text.strip("\n"))
    parsed = []
    for b in blocks:
        ls = b.split("\n")
        t = next((k for k, l in enumerate(ls) if "-->" in l), None)
        if t is None:
            parsed.append((ls, None, ""))
        else:
            parsed.append((ls[:t + 1], ls[t + 1:], _join([re.sub(r"<[^>]+>", "", l) for l in ls[t + 1:]])))
    trs = engine.translate_many([p[2] for p in parsed], tgt, progress=lambda d, n: report("翻译", d, n))
    out = []
    for (head, body, src), tr in zip(parsed, trs):
        if body is None or not tr:
            out.append("\n".join(head + (body or [])))
        elif mode == "dual":
            out.append("\n".join(head + body + [tr]))
        else:
            out.append("\n".join(head + [tr]))
    dst = out_path(path, out_dir, tgt, dual=mode == "dual")
    with open(dst, "w", encoding="utf-8") as f:
        f.write("\n\n".join(out) + "\n")
    return [dst]
