"""On-device OCR (Apple Vision via a small Swift helper) and grouping of OCR lines into paragraphs."""
import json
import os
import re
import subprocess

from . import config

SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ocr_vision.swift")
BIN = os.path.join(config.SUPPORT, "bin", "ocr")


class OCRError(Exception):
    pass


def ensure_binary():
    if os.path.exists(BIN) and os.path.getmtime(BIN) >= os.path.getmtime(SRC):
        return BIN
    os.makedirs(os.path.dirname(BIN), exist_ok=True)
    p = subprocess.run(["swiftc", "-O", SRC, "-o", BIN], capture_output=True, text=True)
    if p.returncode != 0:
        raise OCRError("OCR 组件编译失败（需要 Xcode 命令行工具）：" + p.stderr[-400:])
    return BIN


def recognize(image_path, png_out, languages):
    """Return dict(width, height, lines=[{text, conf, box}]) and write the orientation-normalized PNG."""
    p = subprocess.run([ensure_binary(), image_path, png_out, ",".join(languages)],
                       capture_output=True, text=True, timeout=600)
    try:
        data = json.loads(p.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        raise OCRError("OCR 失败：" + (p.stderr or p.stdout)[-300:])
    if "error" in data:
        raise OCRError("OCR 失败：" + data["error"])
    return data


def _join(a, b):
    if not a:
        return b
    if re.search(r"[　-鿿가-힯]$", a) or re.match(r"[　-鿿가-힯]", b):
        return a + b
    if a.endswith("-") and len(a) > 1 and a[-2].isalpha() and b[:1].islower():
        return a[:-1] + b
    return a + " " + b


def group_lines(lines, min_conf=0.3):
    """Group OCR text lines (pixel boxes) into paragraphs. Handles multiple columns."""
    items = []
    for ln in lines:
        x0, y0, x1, y1 = ln["box"]
        if ln.get("conf", 1) < min_conf or not ln["text"].strip():
            continue
        items.append({"text": ln["text"].strip(), "box": [x0, y0, x1, y1], "h": max(1.0, y1 - y0)})
    # Vision sometimes splits one visual line into several observations: merge pieces on the same line
    items.sort(key=lambda it: (it["box"][0]))
    merged = []
    for it in sorted(items, key=lambda it: (round(it["box"][1] / 4), it["box"][0])):
        for m in merged:
            a, b = m["box"], it["box"]
            ov = min(a[3], b[3]) - max(a[1], b[1])
            gap = b[0] - a[2]
            if ov > 0.5 * min(m["h"], it["h"]) and -0.5 * it["h"] <= gap <= 3 * max(m["h"], it["h"]):
                m["text"] = _join(m["text"], it["text"])
                m["box"] = [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]
                m["h"] = m["box"][3] - m["box"][1]
                break
        else:
            merged.append(dict(it))
    items = merged
    items.sort(key=lambda it: (it["box"][1], it["box"][0]))
    paras = []
    for it in items:
        x0, y0, x1, y1 = it["box"]
        best = None
        for p in paras:
            last = p["lines"][-1]
            lx0, ly0, lx1, ly1 = last["box"]
            h = max(last["h"], it["h"])
            gap = y0 - ly1
            overlap = min(x1, lx1) - max(x0, lx0)
            similar_h = abs(it["h"] - last["h"]) <= 0.35 * h
            aligned = abs(x0 - lx0) <= 2.5 * h or overlap > 0.4 * min(x1 - x0, lx1 - lx0)
            if -0.3 * h <= gap <= 0.9 * h and similar_h and aligned and overlap > -0.5 * h:
                best = p
                break
        if best is None:
            paras.append({"lines": [it]})
        else:
            best["lines"].append(it)
    # second pass: split at short last lines (paragraph ends, headings) and first-line indents
    split = []
    for p in paras:
        lines = p["lines"]
        right = max(l["box"][2] for l in lines)
        left = min(l["box"][0] for l in lines)
        cur = [lines[0]]
        for prev, ln in zip(lines, lines[1:]):
            h = max(prev["h"], ln["h"])
            ends = re.search(r"[.:!?。：！？;；]$", prev["text"]) is not None
            short = prev["box"][2] < right - 2.5 * h
            indent = ln["box"][0] > left + 0.8 * h
            if (short and (ends or len(prev["text"]) < 70)) or (indent and ends):
                split.append({"lines": cur})
                cur = [ln]
            else:
                cur.append(ln)
        split.append({"lines": cur})
    paras = split

    out = []
    for p in paras:
        xs0 = min(l["box"][0] for l in p["lines"])
        ys0 = min(l["box"][1] for l in p["lines"])
        xs1 = max(l["box"][2] for l in p["lines"])
        ys1 = max(l["box"][3] for l in p["lines"])
        text = ""
        for l in p["lines"]:
            text = _join(text, l["text"])
        hs = sorted(l["h"] for l in p["lines"])
        out.append({"box": [xs0, ys0, xs1, ys1], "lines": p["lines"], "text": text, "line_h": hs[len(hs) // 2]})
    return out
