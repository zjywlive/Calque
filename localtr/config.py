"""Settings, paths and language table for Calque (镜译).

The support/cache/log folders keep the original "LocalTranslator" name so existing settings carry over."""
import json
import os

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SUPPORT = os.path.expanduser("~/Library/Application Support/LocalTranslator")
CACHE_DIR = os.path.expanduser("~/Library/Caches/LocalTranslator")
LOG_FILE = os.path.expanduser("~/Library/Logs/LocalTranslator.log")
CONFIG_FILE = os.path.join(SUPPORT, "config.json")
USER_GLOSSARY = os.path.join(SUPPORT, "glossary.tsv")

DEFAULTS = {
    "model": "hy-mt2-30b-a3b",          # LM Studio model key (Hy-MT2-30B-A3B, a dedicated MT model)
    "identifier": "localtr",            # identifier used when we load it, so we never touch the user's own models
    "server": "http://127.0.0.1:1234",  # LM Studio local server
    "workers": 4,                       # parallel requests
    "temperature": 0.2,                 # low = stable wording across runs
    "context": 8192,
    "ttl": 900,                         # LM Studio unloads our model after 15 min idle
    "target": "zh",
    "mode": "dual",                     # dual = bilingual, mono = translation only
    "ocr": "auto",                      # PDF OCR: auto (scanned pages only) / force / off
    "output_dir": os.path.expanduser("~/Documents/镜译"),
    "ocr_languages": ["en-US", "zh-Hans", "zh-Hant", "ja-JP", "ko-KR", "fr-FR", "de-DE", "es-ES"],
    "glossaries": ["robotics.tsv"],     # files in <app>/glossary, plus the user glossary
    "keep_names": True,                 # keep personal names / quoted titles in the source language
    "port": 8765,
}

# code: (Chinese name used in Hy-MT2's Chinese template, English name for the English template)
LANGS = {
    "zh": ("中文", "Chinese"),
    "zh-Hant": ("繁体中文", "Traditional Chinese"),
    "en": ("英语", "English"),
    "ja": ("日语", "Japanese"),
    "ko": ("韩语", "Korean"),
    "fr": ("法语", "French"),
    "de": ("德语", "German"),
    "es": ("西班牙语", "Spanish"),
    "pt": ("葡萄牙语", "Portuguese"),
    "it": ("意大利语", "Italian"),
    "ru": ("俄语", "Russian"),
    "ar": ("阿拉伯语", "Arabic"),
    "vi": ("越南语", "Vietnamese"),
    "th": ("泰语", "Thai"),
}
LANG_LABELS = {
    "zh": "简体中文", "zh-Hant": "繁體中文", "en": "English", "ja": "日本語", "ko": "한국어",
    "fr": "Français", "de": "Deutsch", "es": "Español", "pt": "Português", "it": "Italiano",
    "ru": "Русский", "ar": "العربية", "vi": "Tiếng Việt", "th": "ไทย",
}


def load():
    os.makedirs(SUPPORT, exist_ok=True)
    cfg = dict(DEFAULTS)
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, encoding="utf-8") as f:
                cfg.update(json.load(f))
        except (OSError, ValueError):
            pass
    else:
        save(cfg)
    if not os.path.exists(USER_GLOSSARY):
        with open(USER_GLOSSARY, "w", encoding="utf-8") as f:
            f.write("# 自定义术语表：每行  原文<Tab>译文  （可选第三列：目标语言代码，默认 zh）\n"
                    "# 例如：\n# in-hand manipulation\t手内操作\n")
    return cfg


def save(cfg):
    os.makedirs(SUPPORT, exist_ok=True)
    tmp = CONFIG_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CONFIG_FILE)
