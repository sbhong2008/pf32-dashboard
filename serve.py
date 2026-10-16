#!/usr/bin/env python3
"""PF32 로컬 앱 서버 — http://127.0.0.1:8032  (정적 파일 + /api/*)"""
import json, subprocess, sys, threading, webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PORT = 8032
state = {"running": False}


def run_update():
    state["running"] = True
    try:
        with open(ROOT / "data" / "update.log", "w") as log:
            subprocess.run([sys.executable, "-I", str(ROOT / "update.py")], stdout=log, stderr=subprocess.STDOUT)
    finally:
        state["running"] = False


class H(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k): super().__init__(*a, directory=str(ROOT), **k)

    def _json(self, obj, code=200):
        b = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(b))); self.send_header("Cache-Control", "no-store"); self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path.startswith("/api/status"):
            p = ROOT / "data" / "update.log"
            return self._json({"running": state["running"], "log": p.read_text()[-1500:] if p.exists() else ""})
        if self.path.split("?")[0] in ("/config.json", "/config.local.json", "/data/data.json") and (ROOT / self.path.split("?")[0].lstrip("/")).exists():
            self.send_response(200)  # no-store 로 항상 최신
            b = (ROOT / self.path.split("?")[0].lstrip("/")).read_bytes()
            self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(b)))
            self.send_header("Cache-Control", "no-store"); self.end_headers(); return self.wfile.write(b)
        return super().do_GET()

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0)); body = self.rfile.read(n) if n else b""
        if self.path == "/api/update":
            if not state["running"]: threading.Thread(target=run_update, daemon=True).start()
            return self._json({"running": True})
        if self.path == "/api/config":
            try: cfg = json.loads(body)
            except ValueError: return self._json({"error": "bad json"}, 400)
            (ROOT / "config.local.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
            return self._json({"ok": True})
        self._json({"error": "not found"}, 404)

    def log_message(self, *a): pass


if __name__ == "__main__":
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), H)  # 로컬 전용
    if "--no-open" not in sys.argv: threading.Timer(0.8, lambda: webbrowser.open(f"http://127.0.0.1:{PORT}")).start()
    print(f"PF32 app: http://127.0.0.1:{PORT}  (Ctrl+C 종료)")
    srv.serve_forever()
