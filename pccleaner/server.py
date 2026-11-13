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

from .platforms.common import background_thread
from . import __version__, duplicates, junk, organizer, paths, quarantine, scanner, scheduler, similar, startup

WEB_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).parent.parent)) / "pccleaner" / "web"
if not WEB_DIR.is_dir():
    WEB_DIR = Path(__file__).parent / "web"


def _log_exc() -> None:
    """Write the current exception to app.log (packaged apps have no console)."""
    try:
        with open(paths.data_dir() / "app.log", "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + traceback.format_exc() + "\n")
    except OSError:
        pass


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
                background_thread()
                try:
                    result = fn(self.cancel, self._update)
                    self.state.update(state="done", result=result, finished=time.time())
                except (scanner.Cancelled, InterruptedError):
                    self.state.update(state="cancelled", finished=time.time())
                except Exception as e:  # noqa: BLE001
                    _log_exc()
                    self.state.update(state="error", error=str(e), finished=time.time())

            self.thread = threading.Thread(target=run, daemon=True)
            self.thread.start()

    def _update(self, progress) -> None:
        self.state["progress"] = dict(progress.__dict__)

    def action(self, label: str, fn) -> dict:
        """Run a file-changing action in the background, with progress and a Stop button.

        ``fn(cancel, progress, on_progress)``; the UI waits for kind "action".
        """
        progress = quarantine.Progress(label)
        self.start("action", lambda c, u: fn(c, progress, u), label=label)
        return {"ok": True, "job": True}


jobs = JobManager()

# Set by app.py when the UI runs inside a pywebview window; enables the native folder picker.
window = None


def _pick_folder() -> str | None:
    if window is None:
        raise RuntimeError("Chỉ chọn thư mục được khi chạy trong cửa sổ ứng dụng")
    import webview  # type: ignore

    kind = getattr(getattr(webview, "FileDialog", None), "FOLDER", None) or webview.FOLDER_DIALOG
    result = window.create_file_dialog(kind)
    if not result:
        return None
    return result[0] if isinstance(result, (list, tuple)) else str(result)


def _reveal(path: str) -> None:
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    if paths.IS_WINDOWS:
        subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
    elif paths.IS_MAC:
        subprocess.Popen(["open", "-R", path])
    else:
        subprocess.Popen(["xdg-open", os.path.dirname(path) if os.path.isfile(path) else path])


CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
    "connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)


def make_handler(token: str):
    class Handler(BaseHTTPRequestHandler):
        server_version = "PCCleaner"

        def log_message(self, fmt, *args):  # keep the console quiet
            pass

        # ---- helpers ----
        def _send(self, code: int, body: bytes, ctype: str):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            # Only the app's own files may run or load; nothing can be sent elsewhere.
            self.send_header("Content-Security-Policy", CSP)
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
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

        def _host_ok(self) -> bool:
            # Blocks DNS-rebinding: a web page cannot reach this server under another name.
            host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
            return host in ("127.0.0.1", "localhost")

        # ---- routing ----
        def do_GET(self):
            if not self._host_ok():
                return self._send(403, b"forbidden", "text/plain")
            u = urlparse(self.path)
            if u.path == "/api/thumb":
                return self._thumb(parse_qs(u.query))
            if not u.path.startswith("/api/"):
                return self._static(u.path)
            self._api("GET", u.path, {k: v[0] for k, v in parse_qs(u.query).items()}, {})

        def do_POST(self):
            if not self._host_ok():
                return self._send(403, b"forbidden", "text/plain")
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

        def _thumb(self, q: dict):
            # <img> tags cannot send headers, so the token comes in the query string.
            if not secrets.compare_digest((q.get("t") or [""])[0], token):
                return self._send(401, b"unauthorized", "text/plain")
            try:
                data = similar.thumbnail((q.get("path") or [""])[0])
            except Exception:  # noqa: BLE001
                return self._send(404, b"not found", "text/plain")
            self._send(200, data, "image/jpeg")

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
                _log_exc()
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
            "can_pick_folder": window is not None,
        }
    if key == ("POST", "pick-folder"):
        return {"path": _pick_folder()}
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
        full = bool(body.get("full"))
        jobs.start("scan", lambda c, u: scanner.scan(root, progress, c, u, incremental=not full), root=root)
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
        if sub == "similar":
            return similar.get_groups(sid)
    if key == ("POST", "duplicates"):
        sid = int(body["scan_id"])
        min_size = int(body.get("min_size", 2**20))
        progress = duplicates.DupProgress()
        jobs.start("duplicates", lambda c, u: duplicates.find_duplicates(sid, min_size, progress, c, u), scan_id=sid)
        return {"ok": True}
    if key == ("POST", "similar"):
        sid = int(body["scan_id"])
        thr = int(body.get("threshold", similar.DEFAULT_THRESHOLD))
        progress = similar.SimProgress()
        jobs.start("similar", lambda c, u: similar.find_similar(sid, thr, progress=progress, cancel=c, on_progress=u), scan_id=sid)
        return {"ok": True}
    if key == ("POST", "junk-scan"):
        jobs.start("junk", lambda c, u: junk.scan(c, u))
        return {"ok": True}
    if key == ("POST", "junk-clean"):
        ids = [str(i) for i in body.get("ids") or []]
        if not ids:
            raise ValueError("Chưa chọn mục nào")
        return jobs.action("Đang dọn rác hệ thống", lambda c, p, u: junk.clean(ids, c, p, u))
    if key == ("GET", "startup"):
        return {"items": startup.list_items(), "admin": startup.is_admin(),
                "last_restore_point": scheduler.db.get_setting("last_restore_point")}
    if key == ("POST", "startup-set"):
        return startup.set_enabled(str(body["id"]), bool(body["enable"]))
    if key == ("POST", "restore-point"):
        return startup.create_restore_point()
    if key == ("GET", "startup-history"):
        return startup.history()
    if key == ("POST", "organize-preview"):
        return organizer.preview(str(body.get("folder") or ""), bool(body.get("by_year", True)))
    if key == ("POST", "organize-apply"):
        folder, chosen = str(body.get("folder") or ""), [str(p) for p in body.get("chosen") or []]
        by_year = bool(body.get("by_year", True))
        organizer.preview(folder, by_year)  # refuse a bad folder right away, before the job starts
        return jobs.action("Đang sắp xếp thư mục", lambda c, p, u: organizer.apply(folder, chosen, by_year, c, p, u))
    if key == ("GET", "schedule"):
        cfg = scheduler.get()
        cfg["registered"] = scheduler.is_registered()
        cfg["pending_bytes"] = quarantine.pending_bytes()
        return cfg
    if key == ("POST", "schedule"):
        return scheduler.save(body)
    if key == ("POST", "schedule-run"):
        return jobs.action("Đang chạy dọn dẹp tự động", lambda c, p, u: scheduler.run_auto_clean(c, p, u))
    if key == ("POST", "quarantine"):
        files = body.get("paths") or []
        if not isinstance(files, list) or not files:
            raise ValueError("Chưa chọn file nào")
        files = [str(p) for p in files]
        reason, allow_cloud = str(body.get("reason", "")), bool(body.get("allow_cloud"))
        dup_sid, sim_sid = body.get("dup_scan_id"), body.get("similar_scan_id")

        def clean(c, p, u):
            chosen, refused = files, []
            if dup_sid is not None:
                # Duplicates are re-verified on disk right before anything moves.
                p.stage = "Đang kiểm tra lại nội dung file trùng"
                u(p)
                chosen, refused = duplicates.check_removal(int(dup_sid), files)
            elif sim_sid is not None:
                chosen, refused = similar.check_removal(int(sim_sid), files)
            p.stage = "Đang dọn"
            return quarantine.quarantine(chosen, reason, refused, allow_cloud=allow_cloud,
                                         cancel=c, progress=p, on_progress=u)

        return jobs.action("Đang dọn", clean)
    if key == ("GET", "batches"):
        return quarantine.batches()
    if key == ("GET", "log"):
        return quarantine.log()
    if key == ("POST", "restore"):
        bids = [str(b) for b in (body.get("batch_ids") or [body["batch_id"]])]

        def undo_all(c, p, u):
            out = {"restored": 0, "failed": [], "renamed": [], "cancelled": False}
            for b in bids:
                r = quarantine.restore(b, c, p, u)
                out["restored"] += r["restored"]
                out["failed"] += r["failed"]
                out["renamed"] += r.get("renamed", [])
                out["cancelled"] = out["cancelled"] or r["cancelled"]
            return out

        return jobs.action("Đang trả file về chỗ cũ", undo_all)
    if key == ("POST", "purge"):
        bid = str(body["batch_id"])
        return jobs.action("Đang xóa vĩnh viễn", lambda c, p, u: quarantine.purge_batch(bid, c, p, u))
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
