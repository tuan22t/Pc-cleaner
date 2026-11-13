"""Checking for, downloading and starting an update.

Safety rules:
- An update announcement (a small JSON file on the release server) counts only
  if it carries a valid Ed25519 signature from the publisher's key, whose public
  half is built into the app (UPDATE_PUBLIC_KEY). A changed server or a
  man-in-the-middle cannot offer a different file.
- The announcement names the installer's size and SHA-256; the downloaded file
  must match both before it can be started.
- Nothing is downloaded or installed without the user clicking for it.
- Installing replaces only the program. Data and quarantine live in the data
  folder, which installers never touch.

Asking the server sends nothing about the user or the computer: it is a plain
download of a public file.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from . import APP_ID, __version__, db, ed25519, paths
from .i18n import _

# Set when the release key is made (see docs/phat-hanh.md). Empty: updates are off.
UPDATE_PUBLIC_KEY = ""
# Folder on the release server holding stable.json and beta.json.
UPDATE_BASE_URL = ""
CHANNELS = ("stable", "beta")
MAX_SIZE = 400 * 2**20
CHECK_EVERY = 24 * 3600

VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:-beta\.(\d+))?$")


def parse_version(v: str) -> tuple:
    m = VERSION_RE.match(v or "")
    if not m:
        raise ValueError(_("Số phiên bản không hợp lệ: {0}", v))
    major, minor, patch, beta = m.groups()
    # A beta comes before the stable release of the same number.
    return (int(major), int(minor), int(patch), 0 if beta else 1, int(beta or 0))


def _key() -> bytes:
    k = os.environ.get("PCCLEANER_UPDATE_KEY") or UPDATE_PUBLIC_KEY
    return bytes.fromhex(k) if k else b""


def _base_url() -> str:
    return (os.environ.get("PCCLEANER_UPDATE_URL") or UPDATE_BASE_URL).rstrip("/")


def configured() -> bool:
    return bool(_key() and _base_url())


def platform_key() -> str:
    return "windows" if paths.IS_WINDOWS else "mac" if paths.IS_MAC else "linux"


def settings() -> dict:
    raw = db.get_setting("update")
    cfg = {"channel": "stable", "auto_check": True}
    if raw:
        try:
            cfg.update(json.loads(raw))
        except ValueError:
            pass
    return cfg


def save_settings(body: dict) -> dict:
    cfg = settings()
    if "channel" in body:
        if body["channel"] not in CHANNELS:
            raise ValueError(_("Kênh cập nhật không hợp lệ"))
        cfg["channel"] = body["channel"]
    if "auto_check" in body:
        cfg["auto_check"] = bool(body["auto_check"])
    db.set_setting("update", json.dumps(cfg))
    return status()


def verify_announcement(raw: bytes, channel: str) -> dict:
    """Return the announcement if it is signed by the publisher, else raise ValueError."""
    key = _key()
    if not key:
        raise ValueError(_("Chưa cấu hình khóa kiểm tra bản cập nhật"))
    try:
        outer = json.loads(raw)
        payload = base64.b64decode(outer["payload"], validate=True)
        signature = base64.b64decode(outer["signature"], validate=True)
    except (ValueError, KeyError, TypeError):
        raise ValueError(_("Thông báo cập nhật bị hỏng")) from None
    if not ed25519.verify(key, payload, signature):
        raise ValueError(_("Chữ ký của bản cập nhật không hợp lệ, đã bỏ qua"))
    info = json.loads(payload)
    if info.get("app") != APP_ID or info.get("channel") != channel:
        raise ValueError(_("Thông báo cập nhật không dành cho ứng dụng này"))
    parse_version(info.get("version", ""))
    return info


def _fetch(url: str, limit: int) -> bytes:
    if not url.startswith("https://") and not os.environ.get("PCCLEANER_UPDATE_URL"):
        raise ValueError(_("Chỉ tải bản cập nhật qua HTTPS"))
    req = urllib.request.Request(url, headers={"User-Agent": f"{APP_ID}/{__version__}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = r.read(limit + 1)
    if len(data) > limit:
        raise ValueError(_("Tệp tải về quá lớn"))
    return data


def check(force: bool = False) -> dict:
    """Ask the release server whether a newer version exists on the chosen channel."""
    if not configured():
        return status()
    cfg = settings()
    raw = _fetch(f"{_base_url()}/{cfg['channel']}.json", 256 * 1024)
    info = verify_announcement(raw, cfg["channel"])
    newer = parse_version(info["version"]) > parse_version(__version__)
    db.set_setting("update_last", json.dumps({"ts": time.time(), "info": info if newer else None}))
    return status()


def check_if_due() -> None:
    """Called once at startup, in the background: one check a day at most, if allowed."""
    if not configured() or not settings()["auto_check"]:
        return
    last = _last()
    if last and time.time() - last.get("ts", 0) < CHECK_EVERY:
        return
    try:
        check()
    except Exception:  # noqa: BLE001  - no network is normal
        pass


def _last() -> dict | None:
    raw = db.get_setting("update_last")
    try:
        return json.loads(raw) if raw else None
    except ValueError:
        return None


def status() -> dict:
    last = _last() or {}
    info = last.get("info")
    if info and parse_version(info["version"]) <= parse_version(__version__):
        info = None  # already installed
    dl = (info or {}).get("downloads", {}).get(platform_key()) if info else None
    return {
        "configured": configured(),
        "current": __version__,
        **settings(),
        "last_check": last.get("ts"),
        "available": {"version": info["version"], "notes": info.get("notes", {}), "size": dl["size"]}
        if info and dl else None,
    }


def _updates_dir() -> Path:
    d = paths.data_dir() / "updates"
    d.mkdir(parents=True, exist_ok=True)
    return d


def download(cancel=None, on_progress=None) -> dict:
    """Download the installer of the announced version and check its size and SHA-256."""
    last = _last() or {}
    info = last.get("info")
    if not info:
        raise ValueError(_("Không có bản cập nhật nào"))
    dl = info.get("downloads", {}).get(platform_key())
    if not dl:
        raise ValueError(_("Bản cập nhật chưa có cho hệ điều hành này"))
    url, size, digest = dl["url"], int(dl["size"]), dl["sha256"].lower()
    if size > MAX_SIZE:
        raise ValueError(_("Tệp tải về quá lớn"))
    ext = ".exe" if paths.IS_WINDOWS else ".dmg"
    target = _updates_dir() / f"{APP_ID}-{info['version']}{ext}"
    for old in _updates_dir().iterdir():  # keep only the one being downloaded
        if old != target:
            old.unlink(missing_ok=True)
    if target.exists() and target.stat().st_size == size and _sha256(target) == digest:
        return {"path": str(target), "version": info["version"]}
    if not url.startswith("https://") and not os.environ.get("PCCLEANER_UPDATE_URL"):
        raise ValueError(_("Chỉ tải bản cập nhật qua HTTPS"))
    part = target.with_suffix(ext + ".part")
    h = hashlib.sha256()
    got = 0
    req = urllib.request.Request(url, headers={"User-Agent": f"{APP_ID}/{__version__}"})
    with urllib.request.urlopen(req, timeout=60) as r, open(part, "wb") as f:
        while True:
            if cancel is not None and cancel.is_set():
                f.close()
                part.unlink(missing_ok=True)
                raise InterruptedError
            chunk = r.read(1 << 16)
            if not chunk:
                break
            got += len(chunk)
            if got > size:
                break
            h.update(chunk)
            f.write(chunk)
            if on_progress is not None:
                on_progress(_Progress(got, size))
    if got != size or h.hexdigest() != digest:
        part.unlink(missing_ok=True)
        raise ValueError(_("Tệp cập nhật tải về không khớp, đã xóa. Hãy thử lại sau"))
    os.replace(part, target)
    return {"path": str(target), "version": info["version"]}


class _Progress:
    def __init__(self, done: int, total: int):
        self.done = done
        self.total = total


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def install(path: str) -> dict:
    """Start the installer the user asked for. The caller then closes the app."""
    p = Path(path).resolve()
    if p.parent != _updates_dir().resolve() or not p.is_file():
        raise ValueError(_("Chỉ cài được bản cập nhật đã tải và kiểm tra"))
    st = status()
    last = (_last() or {}).get("info") or {}
    dl = last.get("downloads", {}).get(platform_key()) or {}
    if not dl or _sha256(p) != dl.get("sha256", "").lower():
        raise ValueError(_("Tệp cập nhật tải về không khớp, đã xóa. Hãy thử lại sau"))
    if paths.IS_WINDOWS:
        # /SILENT: a progress window only; the user already confirmed in the app.
        subprocess.Popen([str(p), "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/relaunch=1"],
                         close_fds=True)
        return {"started": True, "quit": True, "version": st["available"]["version"] if st["available"] else None}
    if paths.IS_MAC:
        subprocess.Popen(["open", str(p)])
        return {"started": True, "quit": False, "drag": True}
    raise RuntimeError(_("Hệ điều hành này chưa hỗ trợ tự cập nhật"))


def make_announcement(secret_hex: str, info: dict) -> bytes:
    """Used by tools/sign_update.py on the release machine."""
    payload = json.dumps(info, ensure_ascii=False, sort_keys=True).encode()
    sig = ed25519.sign(bytes.fromhex(secret_hex), payload)
    return json.dumps({"payload": base64.b64encode(payload).decode(), "signature": base64.b64encode(sig).decode()},
                      indent=1).encode()


if __name__ == "__main__":  # pragma: no cover
    print(json.dumps(status(), indent=1, ensure_ascii=False), file=sys.stdout)
