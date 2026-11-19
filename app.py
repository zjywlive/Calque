#!/usr/bin/env python3
"""Calque (镜译) — local web UI (listens on 127.0.0.1 only).

    python3 -E app.py --open      start (or reuse) the server and open the browser
"""
import argparse
import json
import os
import queue
import subprocess
import sys
import threading
import time
import traceback
import urllib.parse
import urllib.request
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

APP_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, APP_DIR)
from localtr import config, core  # noqa: E402
from localtr.engine import Engine, EngineError  # noqa: E402

CFG = config.load()
STATE_FILE = os.path.join(config.SUPPORT, "server.json")
UPLOADS = os.path.join(config.SUPPORT, "uploads")
JOBS, ORDER, LOCK = {}, [], threading.Lock()
TASKS = queue.Queue()
ENGINE = {"obj": None}
STATUS_CACHE = {"t": 0, "v": None}


def log_file(msg):
    os.makedirs(os.path.dirname(config.LOG_FILE), exist_ok=True)
    with open(config.LOG_FILE, "a", encoding="utf-8") as f:
        f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n")


def engine():
    if ENGINE["obj"] is None:
        ENGINE["obj"] = Engine(CFG, log=log_file)
    return ENGINE["obj"]


def worker():
    while True:
        job = TASKS.get()
        job["status"] = "running"
        job["started"] = time.time()

        def report(stage, done, total):
            job.update(stage=stage, done=done, total=total)

        def log(msg):
            job["log"].append(msg)
            log_file(f"[{job['name']}] {msg}")
        eng = engine()
        eng.log = log
        try:
            job["outputs"] = core.translate_file(job["path"], job["out_dir"], eng, job["target"], job["mode"],
                                                 report, log, job["ocr"], CFG["ocr_languages"])
            job["status"] = "done"
        except EngineError as e:
            job.update(status="error", error=str(e))
        except Exception as e:  # keep the server alive, show the reason in the UI
            job.update(status="error", error=f"{type(e).__name__}: {e}")
            log_file(traceback.format_exc())
        finally:
            eng.log = log_file
            job["finished"] = time.time()


def engine_status():
    if time.time() - STATUS_CACHE["t"] > 4:
        try:
            STATUS_CACHE["v"] = engine().status()
        except Exception as e:
            STATUS_CACHE["v"] = {"server": False, "loaded": False, "model": CFG["model"], "error": str(e)}
        STATUS_CACHE["t"] = time.time()
    return STATUS_CACHE["v"]


def within(path, roots):
    real = os.path.realpath(path)
    return any(real.startswith(os.path.realpath(r) + os.sep) for r in roots)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _body_json(self):
        n = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        if u.path in ("/", "/index.html"):
            with open(os.path.join(APP_DIR, "web", "index.html"), "rb") as f:
                data = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        elif u.path == "/api/state":
            with LOCK:
                jobs = [{k: v for k, v in JOBS[j].items() if k != "path"} for j in ORDER]
            self._json({"engine": engine_status(), "jobs": jobs,
                        "config": {k: CFG.get(k) for k in ("target", "mode", "ocr", "output_dir", "model")},
                        "langs": config.LANG_LABELS,
                        "formats": sorted({lbl for _, lbl in core.FORMATS.values()}),
                        "extensions": sorted(core.FORMATS)})
        elif u.path == "/api/models":
            self._json({"models": engine().list_models()})
        elif u.path == "/api/file":
            path = q.get("path", [""])[0]
            if not within(path, [CFG["output_dir"]]) or not os.path.isfile(path):
                return self._json({"error": "not allowed"}, 403)
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Disposition",
                             "attachment; filename*=UTF-8''" + urllib.parse.quote(os.path.basename(path)))
            self.send_header("Content-Length", str(os.path.getsize(path)))
            self.end_headers()
            with open(path, "rb") as f:
                while True:
                    chunk = f.read(1 << 20)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
        if u.path == "/api/upload":
            name = os.path.basename(q.get("name", "file"))
            if not core.supported(name):
                return self._json({"error": f"暂不支持该格式：{name}"}, 400)
            jid = uuid.uuid4().hex[:10]
            folder = os.path.join(UPLOADS, jid)
            os.makedirs(folder, exist_ok=True)
            path = os.path.join(folder, name)
            remaining = int(self.headers.get("Content-Length", 0))
            with open(path, "wb") as f:
                while remaining > 0:
                    chunk = self.rfile.read(min(remaining, 1 << 20))
                    if not chunk:
                        break
                    f.write(chunk)
                    remaining -= len(chunk)
            ext = os.path.splitext(name)[1].lower()
            job = {"id": jid, "name": name, "kind": core.FORMATS[ext][1], "path": path, "status": "queued",
                   "stage": "排队中", "done": 0, "total": 0, "outputs": [], "log": [], "error": "",
                   "target": q.get("target", CFG["target"]), "mode": q.get("mode", CFG["mode"]),
                   "ocr": q.get("ocr", "auto"), "out_dir": CFG["output_dir"], "created": time.time()}
            with LOCK:
                JOBS[jid] = job
                ORDER.insert(0, jid)
            TASKS.put(job)
            return self._json({"id": jid})
        body = self._body_json()
        if u.path == "/api/config":
            changed_model = "model" in body and body["model"] != CFG["model"]
            for k in ("target", "mode", "ocr", "output_dir", "model"):
                if k in body and body[k]:
                    CFG[k] = os.path.expanduser(body[k]) if k == "output_dir" else body[k]
            config.save(CFG)
            if changed_model:
                if ENGINE["obj"]:
                    try:
                        ENGINE["obj"].unload()
                    except Exception:
                        pass
                ENGINE["obj"] = None
                STATUS_CACHE["t"] = 0
            return self._json({"ok": True})
        if u.path in ("/api/reveal", "/api/open"):
            path = body.get("path", "")
            if not (within(path, [CFG["output_dir"]]) or os.path.realpath(path) == os.path.realpath(CFG["output_dir"])):
                return self._json({"error": "not allowed"}, 403)
            os.makedirs(CFG["output_dir"], exist_ok=True)
            subprocess.run(["open", "-R", path] if u.path == "/api/reveal" else ["open", path])
            return self._json({"ok": True})
        if u.path == "/api/open_output":
            os.makedirs(CFG["output_dir"], exist_ok=True)
            subprocess.run(["open", CFG["output_dir"]])
            return self._json({"ok": True})
        if u.path == "/api/choose_output":
            script = 'POSIX path of (choose folder with prompt "选择译文保存位置")'
            p = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
            path = p.stdout.strip()
            if path:
                CFG["output_dir"] = path.rstrip("/")
                config.save(CFG)
            return self._json({"output_dir": CFG["output_dir"]})
        if u.path == "/api/open_glossary":
            config.load()
            subprocess.run(["open", "-e", config.USER_GLOSSARY])
            return self._json({"ok": True})
        if u.path == "/api/clear":
            with LOCK:
                for j in list(ORDER):
                    if JOBS[j]["status"] in ("done", "error"):
                        ORDER.remove(j)
                        JOBS.pop(j)
            return self._json({"ok": True})
        if u.path == "/api/unload":
            try:
                engine().unload()
            except Exception as e:
                return self._json({"error": str(e)}, 500)
            STATUS_CACHE["t"] = 0
            return self._json({"ok": True})
        if u.path == "/api/load":
            try:
                engine().ensure_ready()
            except Exception as e:
                return self._json({"error": str(e)}, 500)
            STATUS_CACHE["t"] = 0
            return self._json({"ok": True})
        self._json({"error": "not found"}, 404)


def running_url():
    try:
        with open(STATE_FILE) as f:
            st = json.load(f)
        url = f"http://127.0.0.1:{st['port']}"
        urllib.request.urlopen(url + "/api/state", timeout=2).read()
        return url
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--open", action="store_true", help="open the browser")
    ap.add_argument("--port", type=int, default=CFG.get("port", 8765))
    a = ap.parse_args()
    url = running_url()
    if url:
        if a.open:
            webbrowser.open(url)
        print("already running at", url)
        return
    server = None
    for port in range(a.port, a.port + 20):
        try:
            server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
            break
        except OSError:
            continue
    if server is None:
        sys.exit("no free port")
    port = server.server_address[1]
    os.makedirs(config.SUPPORT, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump({"port": port, "pid": os.getpid()}, f)
    threading.Thread(target=worker, daemon=True).start()
    url = f"http://127.0.0.1:{port}"
    log_file(f"server started at {url}")
    print("Calque running at", url, flush=True)
    if a.open:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
