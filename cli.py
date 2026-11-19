#!/usr/bin/env python3
"""LocalTranslator command line.

    python3 -E cli.py FILE [FILE ...] [--to zh] [--mode dual|mono] [--out DIR] [--ocr auto|force|off]
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from localtr import config, core  # noqa: E402
from localtr.engine import Engine, EngineError  # noqa: E402


def main():
    cfg = config.load()
    ap = argparse.ArgumentParser(description="本地文档翻译（LM Studio + Hy-MT2，纯本地）")
    ap.add_argument("files", nargs="+")
    ap.add_argument("--to", default=cfg["target"], choices=sorted(config.LANGS))
    ap.add_argument("--mode", default=cfg["mode"], choices=["dual", "mono"])
    ap.add_argument("--out", default=None, help="输出文件夹（默认与原文件同目录）")
    ap.add_argument("--ocr", default="auto", choices=["auto", "force", "off"])
    ap.add_argument("--unload", action="store_true", help="完成后卸载模型")
    a = ap.parse_args()
    eng = Engine(cfg, log=print)
    ok = True
    for f in a.files:
        if not core.supported(f):
            print(f"跳过（不支持的格式）：{f}")
            continue
        out_dir = a.out or os.path.dirname(os.path.abspath(f))
        t0 = time.time()
        last = {"s": ""}

        def report(stage, done, total):
            msg = f"\r  {stage} {done}/{total}" if total else f"\r  {stage}"
            if msg != last["s"]:
                print(msg.ljust(40), end="", flush=True)
                last["s"] = msg
        print(f"{os.path.basename(f)}")
        try:
            outs = core.translate_file(f, out_dir, eng, a.to, a.mode, report, lambda m: print("\n" + m),
                                       a.ocr, cfg["ocr_languages"])
            print(f"\r  完成，用时 {time.time() - t0:.0f} 秒".ljust(40))
            for o in outs:
                print("   →", o)
        except (EngineError, RuntimeError) as e:
            ok = False
            print(f"\n  失败：{e}")
    if a.unload:
        eng.unload()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
