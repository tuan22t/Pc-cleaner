"""Local HTTP API + static UI. Binds to 127.0.0.1 only and requires a per-launch token."""
from __future__ import annotations

import json
import mimetypes
import os
import secrets
import subprocess
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import __version__, duplicates, paths, quarantine, scanner

WEB_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).parent.parent)) / "pccleaner" / "web"
if not WEB_DIR.is_dir():
    WEB_DIR = Path(__file__).parent / "web"


class JobManager:
    """Runs one long task (scan or duplicate search) at a time in a background thread."""

    def __init__(self):
        self.lock = threading.Lock()
        self.thread: threading.Thread | None = None
        self.cancel = threading.Event()
        self.state: dict = {"state": "idle"}

    def busy(self) -> bool:
        return self.thread is not None and self.thread.is_alive()

    def start(self, kind: str, fn, **meta) -> None:
        with self.lock:
            if self.busy():
                raise RuntimeError("Đang có một tác vụ khác chạy")
            self.cancel = threading.Event()
            self.state = {"state": "running", "kind": kind, "started": time.time(), **meta}

            def run():
                try:
                    result = fn(self.cancel, self._update)
                    self.state.update(state="done", result=result, finished=time.time())
                except (scanner.Cancelled, InterruptedError):
                    self.state.update(state="cancelled", finished=time.time())
                except Exception as e:  # noqa: BLE001
                    traceback.print_exc()
                    self.state.update(state="error", error=str(e), finished=time.time())

            self.thread = threading.Thread(target=run, daemon=True)
            self.thread.start()

    def _update(self, progress) -> None:
        self.state["progress"] = dict(progress.__dict__)


jobs = JobManager()


def _reveal(path: str) -> None:
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    if paths.IS_WINDOWS:
        subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
    elif paths.IS_MAC:
        subprocess.Popen(["open", "-R", path])
    else:
        subprocess.Popen(["xdg-open", os.path.dirname(path) if os.path.isfile(path) else path])


def make_handler(token: str):
    class Handler(BaseHTTPRequestHandler):
        server_version = "PCCleaner"

        def log_message(self, fmt, *args):  # keep the console quiet
            pass

        # ---- helpers ----
        def _send(self, code: int, body: bytes, ctype: str):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, data, code: int = 200):
            self._send(code, json.dumps(data, ensure_ascii=False).encode(), "application/json; charset=utf-8")

        def _body(self) -> dict:
            n = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(n) or b"{}") if n else {}

        def _authorized(self) -> bool:
            return secrets.compare_digest(self.headers.get("X-Token", ""), token)

        # ---- routing ----
        def do_GET(self):
            u = urlparse(self.path)
            if not u.path.startswith("/api/"):
                return self._static(u.path)
            self._api("GET", u.path, {k: v[0] for k, v in parse_qs(u.query).items()}, {})

        def do_POST(self):
            u = urlparse(self.path)
            try:
                body = self._body()
            except ValueError:
                return self._json({"error": "JSON không hợp lệ"}, 400)
            self._api("POST", u.path, {}, body)

        def _static(self, path: str):
            if path in ("", "/"):
                path = "/index.html"
            target = (WEB_DIR / path.lstrip("/")).resolve()
            if WEB_DIR.resolve() not in target.parents or not target.is_file():
                return self._send(404, b"not found", "text/plain")
            ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype.endswith("javascript"):
                ctype += "; charset=utf-8"
            self._send(200, target.read_bytes(), ctype)

        def _api(self, method: str, path: str, q: dict, body: dict):
            if not self._authorized():
                return self._json({"error": "unauthorized"}, 401)
            try:
                result = route(method, path, q, body)
            except KeyError as e:
                return self._json({"error": f"Không tìm thấy: {e}"}, 404)
            except (RuntimeError, ValueError, FileNotFoundError, PermissionError) as e:
                return self._json({"error": str(e)}, 400)
            except Exception as e:  # noqa: BLE001
                traceback.print_exc()
                return self._json({"error": str(e)}, 500)
            self._json(result)

    return Handler


def route(method: str, path: str, q: dict, body: dict):
    parts = [p for p in path.split("/") if p][1:]  # drop "api"
    key = (method, parts[0] if parts else "")

    if key == ("GET", "info"):
        return {
            "version": __version__,
            "platform": "windows" if paths.IS_WINDOWS else "mac" if paths.IS_MAC else "linux",
            "home": str(Path.home()),
            "locations": paths.list_locations(),
            "data_dir": str(paths.data_dir()),
        }
    if key == ("GET", "job"):
        return jobs.state
    if key == ("POST", "cancel"):
        jobs.cancel.set()
        return {"ok": True}
    if key == ("POST", "scan"):
        root = os.path.expanduser(body.get("path") or "")
        if not os.path.isdir(root):
            raise FileNotFoundError(f"Thư mục không tồn tại: {root}")
        progress = scanner.ScanProgress()
        jobs.start("scan", lambda c, u: scanner.scan(root, progress, c, u), root=root)
        return {"ok": True}
    if key == ("GET", "scans"):
        return scanner.latest_scans()
    if key == ("GET", "scan") and len(parts) >= 3:
        sid = int(parts[1])
        sub = parts[2]
        if scanner.get_scan(sid) is None:
            raise KeyError(sid)
        if sub == "summary":
            return {"scan": scanner.get_scan(sid), **scanner.type_breakdown(sid)}
        if sub == "children":
            return scanner.children(sid, int(q.get("dir", 0)))
        if sub == "large":
            return scanner.large_files(sid, int(q.get("limit", 200)), int(q.get("min", 0)))
        if sub == "old":
            return scanner.old_files(sid, int(q.get("days", 365)), int(q.get("min", 50 * 2**20)))
        if sub == "duplicates":
            return duplicates.get_groups(sid)
    if key == ("POST", "duplicates"):
        sid = int(body["scan_id"])
        min_size = int(body.get("min_size", 2**20))
        progress = duplicates.DupProgress()
        jobs.start("duplicates", lambda c, u: duplicates.find_duplicates(sid, min_size, progress, c, u), scan_id=sid)
        return {"ok": True}
    if key == ("POST", "quarantine"):
        files = body.get("paths") or []
        if not isinstance(files, list) or not files:
            raise ValueError("Chưa chọn file nào")
        return quarantine.quarantine([str(p) for p in files], str(body.get("reason", "")))
    if key == ("GET", "batches"):
        return quarantine.batches()
    if key == ("GET", "log"):
        return quarantine.log()
    if key == ("POST", "restore"):
        return quarantine.restore(str(body["batch_id"]))
    if key == ("POST", "purge"):
        return quarantine.purge_batch(str(body["batch_id"]))
    if key == ("POST", "reveal"):
        _reveal(str(body["path"]))
        return {"ok": True}
    raise KeyError(path)


def start_server(port: int = 0) -> tuple[ThreadingHTTPServer, str, str]:
    token = os.environ.get("PCCLEANER_TOKEN") or secrets.token_urlsafe(24)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(token))
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{httpd.server_address[1]}/#token={token}"
    return httpd, url, token
