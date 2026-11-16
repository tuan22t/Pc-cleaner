"""Scheduled cleanup, registered with the operating system's own scheduler.

Windows: a Task Scheduler task for the current user (no administrator rights).
macOS: a LaunchAgent in ~/Library/LaunchAgents.

When it fires, the app runs with ``--auto-clean``: it moves the "safe" system
junk categories into quarantine and permanently empties quarantine batches
older than the chosen number of days. Nothing else is touched.
"""
from __future__ import annotations

import json
import os
import plistlib
import subprocess
import sys
import time
from pathlib import Path

from . import APP_NAME, db, junk, paths, quarantine
from .i18n import _

TASK_NAME = r"PCCleaner\AutoClean"
LAUNCH_LABEL = "com.pccleaner.autoclean"
DEFAULTS = {"enabled": False, "frequency": "weekly", "hour": 10, "junk": True, "purge_days": 30}
WEEKDAY = 0  # Sunday


def get() -> dict:
    raw = db.get_setting("schedule")
    cfg = dict(DEFAULTS)
    if raw:
        try:
            cfg.update(json.loads(raw))
        except ValueError:
            pass
    last = db.get_setting("schedule_last_run")
    cfg["last_run"] = json.loads(last) if last else None
    cfg["supported"] = paths.IS_WINDOWS or paths.IS_MAC
    cfg["health"] = health(cfg)
    return cfg


def _command() -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, "--auto-clean"]
    exe = sys.executable
    if paths.IS_WINDOWS:
        pyw = os.path.join(os.path.dirname(exe), "pythonw.exe")
        exe = pyw if os.path.exists(pyw) else exe
    run_py = str(Path(__file__).resolve().parent.parent / "run.py")
    return [exe, run_py, "--auto-clean"]


def _plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LAUNCH_LABEL}.plist"


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    kw = {"creationflags": 0x08000000} if paths.IS_WINDOWS else {}
    return subprocess.run(cmd, capture_output=True, text=True, errors="replace", **kw)


def _register(cfg: dict) -> None:
    hour = int(cfg["hour"])
    if paths.IS_WINDOWS:
        tr = subprocess.list2cmdline(_command())
        sc = {"daily": ["/SC", "DAILY"], "weekly": ["/SC", "WEEKLY", "/D", "SUN"], "monthly": ["/SC", "MONTHLY", "/D", "1"]}[cfg["frequency"]]
        r = _run(["schtasks", "/Create", "/F", "/TN", TASK_NAME, "/TR", tr, *sc, "/ST", f"{hour:02d}:00"])
        if r.returncode != 0:
            raise RuntimeError((r.stderr or r.stdout).strip()[:300])
    elif paths.IS_MAC:
        when: dict = {"Hour": hour, "Minute": 0}
        if cfg["frequency"] == "weekly":
            when["Weekday"] = WEEKDAY
        elif cfg["frequency"] == "monthly":
            when["Day"] = 1
        plist = {
            "Label": LAUNCH_LABEL, "ProgramArguments": _command(), "StartCalendarInterval": when,
            "RunAtLoad": False, "ProcessType": "Background", "LowPriorityIO": True,
        }
        p = _plist_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "wb") as f:
            plistlib.dump(plist, f)
        domain = f"gui/{os.getuid()}"
        _run(["launchctl", "bootout", f"{domain}/{LAUNCH_LABEL}"])
        r = _run(["launchctl", "bootstrap", domain, str(p)])
        if r.returncode != 0 and "already" not in r.stderr.lower():
            raise RuntimeError(r.stderr.strip()[:300])
    else:
        raise RuntimeError(_("Chỉ hỗ trợ Windows và macOS"))


def _unregister() -> None:
    if paths.IS_WINDOWS:
        _run(["schtasks", "/Delete", "/F", "/TN", TASK_NAME])
    elif paths.IS_MAC:
        _run(["launchctl", "bootout", f"gui/{os.getuid()}/{LAUNCH_LABEL}"])
        try:
            _plist_path().unlink()
        except FileNotFoundError:
            pass


def is_registered() -> bool:
    if paths.IS_WINDOWS:
        return _run(["schtasks", "/Query", "/TN", TASK_NAME]).returncode == 0
    if paths.IS_MAC:
        return _plist_path().exists()
    return False


def _registered_command() -> str | None:
    """The command line the operating system will run, or None if nothing is registered."""
    if paths.IS_WINDOWS:
        r = _run(["schtasks", "/Query", "/TN", TASK_NAME, "/XML"])
        if r.returncode != 0:
            return None
        import re

        cmd = re.search(r"<Command>(.*?)</Command>", r.stdout, re.S)
        args = re.search(r"<Arguments>(.*?)</Arguments>", r.stdout, re.S)
        if not cmd:
            return None
        import html

        return (html.unescape(cmd.group(1)) + " " + html.unescape(args.group(1) if args else "")).strip()
    if paths.IS_MAC:
        try:
            with open(_plist_path(), "rb") as f:
                return subprocess.list2cmdline(plistlib.load(f).get("ProgramArguments") or [])
        except (OSError, ValueError, plistlib.InvalidFileException):
            return None
    return None


def _same_command(a: str, b: str) -> bool:
    norm = (lambda x: x.replace('"', "").lower().split()) if paths.IS_WINDOWS else (lambda x: x.replace('"', "").split())
    return norm(a) == norm(b)


def _translocated() -> bool:
    """macOS runs apps opened straight from a download at a random read-only
    path that changes on every launch; a schedule pointing there would break."""
    return paths.IS_MAC and "/AppTranslocation/" in sys.executable


def health(cfg: dict | None = None) -> dict:
    """Is the scheduled cleanup still pointing at this copy of the app?"""
    cfg = cfg or {}
    if not cfg.get("enabled") or not (paths.IS_WINDOWS or paths.IS_MAC):
        return {"ok": True, "problem": None}
    if _translocated():
        return {"ok": False, "problem": "translocated",
                "message": _("Hãy kéo {0} vào thư mục Applications rồi mở lại, lịch dọn tự động mới chạy được.", APP_NAME)}
    reg = _registered_command()
    if reg is None:
        return {"ok": False, "problem": "missing",
                "message": _("Lịch dọn tự động đã bị xóa khỏi hệ thống. Bấm Lưu để đăng ký lại.")}
    if not _same_command(reg, subprocess.list2cmdline(_command())):
        return {"ok": False, "problem": "moved",
                "message": _("Ứng dụng đã được chuyển sang chỗ khác. Bấm Lưu để cập nhật lịch dọn tự động.")}
    return {"ok": True, "problem": None}


def self_check() -> dict:
    """At start-up: if the app was moved or reinstalled elsewhere, point the schedule at it again."""
    raw = db.get_setting("schedule")
    cfg = dict(DEFAULTS)
    if raw:
        try:
            cfg.update(json.loads(raw))
        except ValueError:
            return {"ok": True, "problem": None}
    h = health(cfg)
    if h["problem"] in ("moved", "missing"):
        try:
            _register(cfg)
            return {"ok": True, "problem": None, "fixed": h["problem"]}
        except Exception as e:  # noqa: BLE001 - shown in the schedule screen instead
            h["error"] = str(e)[:200]
    return h


def save(cfg_in: dict) -> dict:
    cfg = dict(DEFAULTS)
    cfg.update({k: cfg_in[k] for k in DEFAULTS if k in cfg_in})
    if cfg["frequency"] not in ("daily", "weekly", "monthly"):
        raise ValueError(_("Tần suất không hợp lệ"))
    cfg["hour"] = max(0, min(23, int(cfg["hour"])))
    cfg["purge_days"] = max(0, min(365, int(cfg["purge_days"])))
    cfg["enabled"] = bool(cfg["enabled"])
    cfg["junk"] = bool(cfg["junk"])
    if cfg["enabled"]:
        _register(cfg)
    else:
        _unregister()
    db.set_setting("schedule", json.dumps(cfg))
    return get()


def remove_for_uninstall() -> None:
    """Before the app is removed: take the scheduled task (or LaunchAgent) off the
    system, so nothing tries to start a program that is gone. Data is kept."""
    _unregister()
    raw = db.get_setting("schedule")
    if raw:
        try:
            cfg = json.loads(raw)
            cfg["enabled"] = False
            db.set_setting("schedule", json.dumps(cfg))
        except ValueError:
            pass


def record_skipped(why: str) -> None:
    db.set_setting("schedule_last_run", json.dumps({"ts": time.time(), "skipped": why}))


def run_auto_clean(cancel=None, progress=None, on_progress=None) -> dict:
    """What the scheduled task does. Safe junk only; old quarantine is emptied."""
    cfg = get()
    result: dict = {"ts": time.time(), "junk_moved": 0, "junk_bytes": 0, "purged_bytes": 0}
    if cfg.get("junk", True):
        ids = [c["id"] for c in junk.scan() if c["label"] == "safe" and not c["admin"] and c["count"] > 0]
        if ids:
            r = junk.clean(ids, cancel, progress, on_progress)
            result["junk_moved"], result["junk_bytes"] = r["moved"], r["bytes"]
    days = int(cfg.get("purge_days") or 0)
    if days > 0:
        result["purged_bytes"] = quarantine.purge_older_than(days)["freed"]
    db.set_setting("schedule_last_run", json.dumps(result))
    try:
        from . import dashboard

        dashboard.record_disks()
    except Exception:  # noqa: BLE001 - history only
        pass
    return result
