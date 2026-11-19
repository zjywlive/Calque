"""Translation engine: a local Hy-MT2 model served by LM Studio.

- Starts the LM Studio server and loads the model on demand under its own identifier
  (with a TTL), so the user's own loaded models are never touched.
- Uses Hy-MT2's official prompt templates (Chinese template for zh pairs, English template otherwise),
  with a terminology block built from glossaries, personal names and quoted titles.
- Caches results on disk, translates in parallel, validates output (right script, no LaTeX).
"""
import hashlib
import json
import os
import re
import subprocess
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

from . import config
from .names import find_names, find_titles
from .textutil import needs_translation

LMS = os.path.expanduser("~/.lmstudio/bin/lms")
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|[⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏]")
CJK = re.compile(r"[一-鿿]")
SCRIPT = {
    "zh": r"[一-鿿]", "zh-Hant": r"[一-鿿]",
    "ja": r"[぀-ヿ一-鿿]", "ko": r"[가-힯]",
    "ru": r"[Ѐ-ӿ]", "ar": r"[؀-ۿ]", "th": r"[฀-๿]",
}


class EngineError(Exception):
    pass


def is_chinese(text):
    cjk = len(CJK.findall(text))
    return cjk > 0 and cjk >= 0.3 * sum(1 for c in text if c.isalpha())


def load_glossaries(cfg):
    """Return list of (source, target, target_lang)."""
    files = [os.path.join(config.APP_DIR, "glossary", g) for g in cfg.get("glossaries", [])]
    files.append(config.USER_GLOSSARY)
    out = []
    for path in files:
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            for line in f:
                if not line.strip() or line.lstrip().startswith("#"):
                    continue
                parts = [p.strip() for p in line.rstrip("\n").split("\t")]
                if len(parts) >= 2 and parts[0] and parts[1]:
                    out.append((parts[0], parts[1], parts[2] if len(parts) > 2 and parts[2] else "zh"))
    # longest first so "tactile sensing" wins over "tactile sensor" in display order
    out.sort(key=lambda x: -len(x[0]))
    return out


def split_long(text, limit=1500):
    if len(text) <= limit:
        return [text]
    parts = re.split(r"(?<=[.!?。！？；;])\s+", text)
    chunks, cur = [], ""
    for p in parts:
        if cur and len(cur) + len(p) + 1 > limit:
            chunks.append(cur)
            cur = p
        else:
            cur = (cur + " " + p).strip() if cur else p
    if cur:
        chunks.append(cur)
    out = []
    for c in chunks:  # still too long (no punctuation): hard split
        while len(c) > limit * 1.5:
            out.append(c[:limit])
            c = c[limit:]
        out.append(c)
    return out


def clean_output(out):
    out = re.sub(r"<think>.*?</think>", "", out, flags=re.S)
    out = re.sub(r"\*\*(.+?)\*\*", r"\1", out)
    out = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"\1", out)
    return out.replace("`", "").strip()


def postfix(src, out):
    if out and len(src) < 40 and "/" in out and "/" not in src:
        out = out.split("/")[0].strip()  # short labels sometimes come back as "A/B" alternatives
    return out


class Engine:
    def __init__(self, cfg=None, log=print):
        self.cfg = cfg or config.load()
        self.log = log
        self.base = self.cfg["server"].rstrip("/")
        self.glossary = load_glossaries(self.cfg)
        self._caches = {}
        self._lock = threading.Lock()
        self._ready = False

    # ------------------------------------------------------------ LM Studio
    def _lms(self, *args, timeout=900):
        if not os.path.exists(LMS):
            raise EngineError("找不到 LM Studio 命令行工具（~/.lmstudio/bin/lms），请先安装并打开一次 LM Studio。")
        p = subprocess.run([LMS, *args], capture_output=True, text=True, timeout=timeout)
        return p.returncode, ANSI.sub("", p.stdout + p.stderr)

    def server_up(self):
        try:
            urllib.request.urlopen(self.base + "/v1/models", timeout=3).read()
            return True
        except Exception:
            return False

    def _ps(self):
        try:
            code, out = self._lms("ps", "--json", timeout=30)
            return json.loads(out)
        except Exception:
            return []

    def loaded(self):
        return [m.get("identifier") for m in self._ps()]

    def list_models(self):
        """modelKeys of the LLMs downloaded in LM Studio (for the model picker); [] if unavailable."""
        try:
            code, out = self._lms("ls", "--json", timeout=30)
            return [m["modelKey"] for m in json.loads(out[out.index("["):]) if m.get("type") == "llm"]
        except Exception:
            return []

    def status(self):
        up = self.server_up()
        mine = [m for m in (self._ps() if up else []) if m.get("identifier") == self.cfg["identifier"]]
        return {"server": up, "loaded": bool(mine), "size_bytes": mine[0].get("sizeBytes") if mine else None,
                "model": self.cfg["model"], "lms": os.path.exists(LMS)}

    def ensure_ready(self):
        if self._ready and self.cfg["identifier"] in self.loaded():
            return
        if not self.server_up():
            self.log("正在启动 LM Studio 本地服务 …")
            self._lms("server", "start", timeout=120)
            for _ in range(60):
                if self.server_up():
                    break
                time.sleep(1)
            else:
                raise EngineError("LM Studio 本地服务启动失败。")
        if self.cfg["identifier"] not in self.loaded():
            self.log(f"正在加载翻译模型 {self.cfg['model']} …")
            code, out = self._lms("load", self.cfg["model"], "--identifier", self.cfg["identifier"],
                                  "-c", str(self.cfg["context"]), "--parallel", str(self.cfg["workers"]),
                                  "--ttl", str(self.cfg["ttl"]), "-y")
            if self.cfg["identifier"] not in self.loaded():
                raise EngineError("翻译模型加载失败：" + out.strip()[-400:])
        self._ready = True

    def unload(self):
        if self.cfg["identifier"] in self.loaded():
            self._lms("unload", self.cfg["identifier"], timeout=120)
        self._ready = False

    # ------------------------------------------------------------ prompts
    def terms_for(self, text, tgt):
        low = text.lower()
        terms, used = [], []
        for src, dst, lang in self.glossary:
            if lang.split("-")[0] != tgt.split("-")[0]:
                continue
            if re.search(r"(?<![\w-])" + re.escape(src.lower()) + r"s?(?![\w-])", low):
                if not any(src.lower() in u for u in used):
                    terms.append((src, dst))
                used.append(src.lower())
        if self.cfg.get("keep_names", True) and not is_chinese(text):
            gl = " ".join(used)
            titles = find_titles(text)
            for t in titles:
                terms.append((t, t))
            for n in find_names(text):
                if n.lower() not in gl and not any(n in t for t in titles):
                    terms.append((n, n))
        return terms[:40]

    def build_messages(self, text, tgt):
        zh_name, en_name = config.LANGS.get(tgt, config.LANGS["zh"])
        terms = self.terms_for(text, tgt)
        if tgt.startswith("zh") or is_chinese(text):
            head = ("参考下面的翻译：\n" + "\n".join(f"{a} 翻译成 {b}" for a, b in terms) + "\n\n") if terms else ""
            prompt = head + f"将以下文本翻译为{zh_name}，注意只需要输出翻译后的结果，不要额外解释：\n\n{text}"
        else:
            head = ("Refer to the following translations:\n" + "\n".join(f"{a} translates to {b}" for a, b in terms)
                    + "\n\n") if terms else ""
            prompt = head + f"Translate the following segment into {en_name}, without additional explanation.\n\n{text}"
        return [{"role": "user", "content": prompt}]

    # ------------------------------------------------------------ validation / cache
    @staticmethod
    def valid(out, src, tgt):
        if not out or not out.strip():
            return False
        if out.strip() == src.strip():
            return True  # names, codes, placeholder text (lorem ipsum) legitimately stay as they are
        if "\\" in out and "\\" not in src:
            return False
        pat = SCRIPT.get(tgt)
        if pat:
            return re.search(pat, out) is not None
        latin = sum(1 for c in out if c.isascii() and c.isalpha())
        return latin >= 0.3 * max(1, sum(1 for c in out if c.isalpha()))

    def _cache(self, tgt):
        key = f"{self.cfg['model']}__{tgt}"
        if key not in self._caches:
            path = os.path.join(config.CACHE_DIR, key.replace("/", "_") + ".json")
            data = {}
            if os.path.exists(path):
                try:
                    with open(path, encoding="utf-8") as f:
                        data = json.load(f)
                except (OSError, ValueError):
                    data = {}
            self._caches[key] = (path, data)
        return self._caches[key]

    def _save_cache(self, tgt):
        path, data = self._cache(tgt)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with self._lock:
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            os.replace(tmp, path)

    @staticmethod
    def _key(text):
        return hashlib.sha1(text.encode("utf-8")).hexdigest()

    # ------------------------------------------------------------ translation
    def _call(self, text, tgt):
        body = {"model": self.cfg["identifier"], "messages": self.build_messages(text, tgt),
                "temperature": self.cfg["temperature"], "top_p": 0.9,
                "max_tokens": max(512, int(len(text) * 1.6)), "reasoning_effort": "none"}
        last = None
        for attempt in range(3):
            try:
                req = urllib.request.Request(self.base + "/v1/chat/completions", data=json.dumps(body).encode("utf-8"),
                                             headers={"Content-Type": "application/json"})
                r = json.load(urllib.request.urlopen(req, timeout=900))
                out = postfix(text, clean_output(r["choices"][0]["message"].get("content") or ""))
                if self.valid(out, text, tgt):
                    return out
                last = "invalid output"
            except Exception as e:  # server busy / model reloading
                last = str(e)
                time.sleep(3)
                try:
                    self.ensure_ready()
                except EngineError:
                    pass
        self.log(f"  ! 一段文字翻译失败（{last}），保留原文")
        return None

    def _translate_one(self, text, tgt):
        chunks = split_long(text)
        outs = [self._call(c, tgt) for c in chunks]
        if any(o is None for o in outs):
            return None
        sep = "" if tgt.startswith(("zh", "ja")) else " "
        return sep.join(outs)

    def translate_many(self, texts, tgt, progress=None):
        """texts -> list of translations (None where translation failed or was not needed)."""
        path, cache = self._cache(tgt)
        uniq = list(dict.fromkeys(t for t in texts if needs_translation(t)))
        todo = [t for t in uniq if not self.valid(cache.get(self._key(t), ""), t, tgt)]
        if progress:
            progress(len(uniq) - len(todo), len(uniq))
        if todo:
            self.ensure_ready()
            done = len(uniq) - len(todo)
            with ThreadPoolExecutor(self.cfg["workers"]) as ex:
                futs = {ex.submit(self._translate_one, t, tgt): t for t in todo}
                for i, fut in enumerate(as_completed(futs), 1):
                    res = fut.result()
                    if res:
                        with self._lock:
                            cache[self._key(futs[fut])] = res
                    done += 1
                    if progress:
                        progress(done, len(uniq))
                    if i % 25 == 0:
                        self._save_cache(tgt)
            self._save_cache(tgt)
        out = []
        for t in texts:
            c = postfix(t, cache.get(self._key(t))) if needs_translation(t) else None
            out.append(c if c and self.valid(c, t, tgt) else None)
        return out
