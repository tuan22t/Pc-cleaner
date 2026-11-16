"""Speed up the computer: what slows it down right now, and safe fixes.

Rules agreed for this feature (the same as the rest of the app):
* looking is read-only: the health check and the list of heavy apps change nothing;
* nothing happens without a click and a confirmation;
* every settings change is recorded *before* it is made and can be undone with
  one click ("Hoàn tác");
* closing an app asks the app to close (it may offer to save first); forcing
  it closed is a separate, second choice;
* system processes, security software, input methods and this app itself can
  never be closed;
* no snake oil: no registry "cleaning", no "freeing RAM" by flushing other
  programs' memory. Those do not make a computer faster.

The operating-system parts live in ``pccleaner.platforms.speed_<os>``.
"""
from __future__ import annotations

import importlib
import json
import os
import shutil
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from . import db, paths, platforms
from .i18n import _
from .startup_base import KEEP_WORDS

_os = None


def _platform():
    global _os
    if _os is None:
        _os = importlib.import_module(f"{platforms.__name__}.speed_{platforms.name()}")
    return _os


@dataclass
class Tweak:
    """One reversible setting. ``read()`` returns the current value; ``write(v)``
    sets it (``None`` means "remove the setting", i.e. back to the system default)."""

    id: str
    name: str
    desc: str
    read: Callable[[], Any]
    write: Callable[[Any], None]
    target: Any
    default: Any = None
    available: Callable[[], str | None] = field(default=lambda: None)  # a reason when it cannot be used
    note: str = ""


# ---------------------------------------------------------------- health


def system_drive() -> str:
    if paths.IS_WINDOWS:
        return (os.environ.get("SystemDrive") or "C:") + "\\"
    return "/"


def status() -> dict:
    """Memory, processor, system drive and time since the last restart."""
    osm = _platform()
    out: dict = {}
    try:
        mem = osm.memory()
        out["mem_total"], out["mem_available"] = mem["total"], mem["available"]
        out["mem_used"] = mem["total"] - mem["available"]
        out["mem_pct"] = round(100 * out["mem_used"] / mem["total"], 1) if mem["total"] else None
    except Exception:  # noqa: BLE001 - a missing figure is shown as "—"
        out["mem_pct"] = None
    try:
        out["cpu_pct"] = osm.cpu_percent()
    except Exception:  # noqa: BLE001
        out["cpu_pct"] = None
    try:
        out["uptime"] = osm.uptime()
    except Exception:  # noqa: BLE001
        out["uptime"] = None
    drive = system_drive()
    try:
        du = shutil.disk_usage(drive)
        out.update(disk_path=drive, disk_total=du.total, disk_free=du.free,
                   disk_free_pct=round(100 * du.free / du.total, 1) if du.total else None)
    except OSError:
        out.update(disk_path=drive, disk_free_pct=None)
    out["cpu_count"] = os.cpu_count() or 1
    return out


# ---------------------------------------------------------------- heavy apps

_prev_lock = threading.Lock()
_prev: dict = {"ts": 0.0, "cpu": {}}  # pid -> (name, cpu seconds) from the last listing


def _family(procs: list[dict], pid: int) -> set[int]:
    """``pid`` with its parents and everything it started (this app's own window, browser engine…)."""
    by_pid = {p["pid"]: p for p in procs}
    fam = {pid}
    p = by_pid.get(pid)
    while p and p.get("ppid") and p["ppid"] not in fam:
        fam.add(p["ppid"])
        p = by_pid.get(p["ppid"])
    kids: dict[int, list[int]] = {}
    for q in procs:
        kids.setdefault(q.get("ppid") or 0, []).append(q["pid"])
    todo = [pid]
    while todo:
        for k in kids.get(todo.pop(), []):
            if k not in fam:
                fam.add(k)
                todo.append(k)
    return fam


def protection(proc: dict, own: set[int]) -> str | None:
    """Why a process may not be closed by the app, or None if it may."""
    osm = _platform()
    if proc["pid"] in own:
        return "Đây là chính ứng dụng này, không thể tự đóng"
    if not proc.get("mine", True):
        return "Chương trình của hệ thống hoặc của người dùng khác"
    name = (proc.get("name") or "").lower()
    path = os.path.normcase(proc.get("path") or "")
    if name in osm.PROTECTED_NAMES or any(path.startswith(os.path.normcase(r)) for r in osm.system_roots() if r):
        return "Thành phần của hệ điều hành"
    low = name + " " + path.lower()
    if any(w in low for w in KEEP_WORDS):
        return "Phần mềm bảo mật, phần cứng hoặc bộ gõ. Nên để chạy"
    return None


def processes() -> list[dict]:
    """Running processes with memory, processor use (percent of the whole processor,
    as Task Manager / Activity Monitor show it) and whether the app may close them."""
    osm = _platform()
    procs = osm.processes()
    now = time.time()
    ncpu = os.cpu_count() or 1
    with _prev_lock:
        dt = now - _prev["ts"]
        prev = _prev["cpu"] if dt < 120 else {}
        for p in procs:
            if p.get("cpu") is None and p.get("cpu_time") is not None:
                old = prev.get(p["pid"])
                if old and old[0] == p["name"] and dt > 0:
                    p["cpu"] = max(0.0, round(100 * (p["cpu_time"] - old[1]) / (dt * ncpu), 1))
        _prev["ts"] = now
        _prev["cpu"] = {p["pid"]: (p["name"], p["cpu_time"]) for p in procs if p.get("cpu_time") is not None}
    own = _family(procs, os.getpid())
    for p in procs:
        p["protected"] = protection(p, own)
    return procs


def heavy_apps(limit: int = 12, procs: list[dict] | None = None) -> list[dict]:
    """The apps using the most memory and processor, one row per app (a browser's
    many processes add up to one row)."""
    procs = processes() if procs is None else procs
    groups: dict[str, dict] = {}
    for p in procs:
        name = p.get("app") or p.get("name") or "?"
        g = groups.setdefault(name.lower(), {"name": name, "mem": 0, "cpu": None, "pids": [], "locked": [],
                                             "count": 0, "path": p.get("path") or "", "why": None})
        g["mem"] += p.get("mem") or 0
        if p.get("cpu") is not None:
            g["cpu"] = round((g["cpu"] or 0) + p["cpu"], 1)
        g["count"] += 1
        if p["protected"]:
            g["locked"].append(p["pid"])
            g["why"] = g["why"] or p["protected"]
        else:
            g["pids"].append(p["pid"])
    out = sorted(groups.values(), key=lambda g: (g["mem"] + (g["cpu"] or 0) * 20 * 2**20), reverse=True)[:limit]
    for g in out:
        g["closable"] = bool(g["pids"])
        if g["closable"]:
            g["why"] = None
    return out


def close_app(name: str, pids: list[int], force: bool = False, wait: float = 4.0) -> dict:
    """Close the processes of one app row. Only processes that are still running
    under the same app name, and that the app may close, are touched: a process
    number reused by another program in the meantime is left alone."""
    osm = _platform()
    procs = processes()
    key = name.lower()
    wanted = set(int(p) for p in pids)
    targets = [p["pid"] for p in procs
               if p["pid"] in wanted and not p["protected"] and (p.get("app") or p.get("name") or "").lower() == key]
    if not targets:
        return {"ok": True, "closed": 0, "running": 0, "refused": len(wanted)}
    osm.terminate(targets, force)
    deadline = time.time() + wait
    while True:
        alive = set(osm.alive(targets))
        if not alive or time.time() >= deadline:
            break
        time.sleep(0.25)
    return {"ok": True, "closed": len(targets) - len(alive), "running": len(alive),
            "refused": len(wanted) - len(targets), "forced": force}


# ---------------------------------------------------------------- settings tweaks


def _key(tid: str) -> str:
    return "tweak:" + tid


def _record(tid: str) -> dict | None:
    raw = db.get_setting(_key(tid))
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


def _forget(tid: str) -> None:
    conn = db.connect()
    conn.execute("DELETE FROM settings WHERE key=?", (_key(tid),))
    conn.commit()


def tweaks() -> list[Tweak]:
    return list(_platform().tweaks())


def tweak_list() -> list[dict]:
    out = []
    for tw in tweaks():
        item = {"id": tw.id, "name": tw.name, "desc": tw.desc, "note": tw.note, "by_app": _record(tw.id) is not None}
        try:
            item["unavailable"] = tw.available()
        except Exception as e:  # noqa: BLE001
            item["unavailable"] = str(e)
        if not item["unavailable"]:
            try:
                item["on"] = tw.read() == tw.target
            except Exception as e:  # noqa: BLE001
                item["unavailable"] = str(e)
        if item["unavailable"]:
            item["on"] = False
        out.append(item)
    return out


def set_tweak(tid: str, on: bool) -> dict:
    """Turn one tweak on, or put the setting back the way it was.

    The value before the change is saved first, so a crash in between never
    leaves a setting changed with no way back from the app.
    """
    tw = next((t for t in tweaks() if t.id == tid), None)
    if tw is None:
        raise KeyError(tid)
    reason = tw.available()
    if reason:
        raise RuntimeError(_(reason))
    current = tw.read()
    rec = _record(tid)
    if on:
        if current == tw.target:
            return {"ok": True, "unchanged": True}
        if rec is None:
            db.set_setting(_key(tid), json.dumps({"original": current, "ts": time.time()}))
        try:
            tw.write(tw.target)
        except Exception:
            if rec is None:
                _forget(tid)
            raise
        return {"ok": True}
    back = rec["original"] if rec else tw.default
    if current != tw.target and rec is None:
        return {"ok": True, "unchanged": True}
    tw.write(back)
    _forget(tid)
    return {"ok": True}


def undo_all() -> dict:
    """Put back every setting this app changed."""
    done, failed = 0, []
    for tw in tweaks():
        if _record(tw.id) is None:
            continue
        try:
            set_tweak(tw.id, False)
            done += 1
        except Exception as e:  # noqa: BLE001
            failed.append({"id": tw.id, "error": str(e)})
    return {"ok": not failed, "restored": done, "failed": failed}


# ---------------------------------------------------------------- one-click clean


def clean_safe_junk(cancel=None, progress=None, on_progress=None) -> dict:
    """Move the junk marked "safe" (temporary files, caches) into quarantine.

    The same choice the scheduled clean makes: categories that need
    administrator rights are left for the System junk screen.
    """
    from . import junk

    found = junk.scan(cancel)
    ids = [c["id"] for c in found if c["label"] == "safe" and not c["admin"] and c["count"] > 0]
    if not ids:
        return {"moved": 0, "bytes": 0, "skipped": 0, "batch_ids": [], "categories": [], "cancelled": False}
    return junk.clean(ids, cancel, progress, on_progress)


# ---------------------------------------------------------------- advice

MEM_HIGH, CPU_HIGH, DISK_LOW_PCT, DISK_LOW_BYTES, UPTIME_LONG = 85, 80, 10, 10 * 2**30, 7 * 86400


def advice(st: dict, tweak_items: list[dict] | None = None, startup: dict | None = None) -> list[dict]:
    """What to do first, most useful first. Each tip names the screen that fixes it."""
    tips: list[dict] = []
    if (st.get("mem_pct") or 0) >= MEM_HIGH:
        tips.append({"level": "warn", "id": "mem", "view": "apps",
                     "text": _("Bộ nhớ RAM đang dùng {0}%. Hãy đóng bớt ứng dụng nặng không dùng đến ở danh sách bên dưới.",
                               round(st["mem_pct"]))})
    if (st.get("cpu_pct") or 0) >= CPU_HIGH:
        tips.append({"level": "warn", "id": "cpu", "view": "apps",
                     "text": _("Bộ xử lý đang bận {0}%. Xem ứng dụng nào đang dùng nhiều ở danh sách bên dưới.",
                               round(st["cpu_pct"]))})
    free_pct, free = st.get("disk_free_pct"), st.get("disk_free")
    if free_pct is not None and (free_pct < DISK_LOW_PCT or (free or 0) < DISK_LOW_BYTES):
        tips.append({"level": "warn", "id": "disk", "view": "clean",
                     "text": _("Ổ hệ thống chỉ còn trống {0}%. Ổ gần đầy làm máy chậm hẳn: hãy dọn rác và file lớn.",
                               round(free_pct))})
    if (st.get("uptime") or 0) >= UPTIME_LONG:
        tips.append({"level": "info", "id": "uptime", "view": "",
                     "text": _("Máy đã chạy liên tục {0} ngày. Khởi động lại máy giúp giải phóng bộ nhớ và hoàn tất các bản cập nhật.",
                               int(st["uptime"] // 86400))})
    if startup is None:
        tips.append({"level": "info", "id": "startup", "view": "startup",
                     "text": _("Chưa kiểm tra các chương trình khởi động cùng máy. Tắt bớt chúng giúp máy mở nhanh hơn.")})
    elif startup.get("can_disable"):
        tips.append({"level": "info", "id": "startup", "view": "startup",
                     "text": _("Có {0} chương trình khởi động cùng máy có thể tắt để máy mở nhanh hơn.", startup["can_disable"])})
    off = [t for t in (tweak_items or []) if not t["on"] and not t.get("unavailable")]
    if off:
        tips.append({"level": "info", "id": "tweaks", "view": "tweaks",
                     "text": _("Có {0} tinh chỉnh an toàn chưa bật. Mỗi tinh chỉnh đều hoàn tác được.", len(off))})
    if not tips:
        tips.append({"level": "ok", "id": "ok", "view": "", "text": _("Máy đang chạy tốt. Không có gì cần làm ngay.")})
    return tips


def overview(with_apps: bool = True) -> dict:
    from . import dashboard

    st = status()
    tw = tweak_list()
    out = {"status": st, "tweaks": tw, "advice": advice(st, tw, dashboard._recall("last_startup")),
           "platform": platforms.name()}
    if with_apps:
        try:
            out["apps"] = heavy_apps()
        except Exception as e:  # noqa: BLE001
            out["apps"], out["apps_error"] = [], str(e)
    return out
