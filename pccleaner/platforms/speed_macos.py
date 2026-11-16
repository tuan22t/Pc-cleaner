"""macOS: memory, processor, running apps and reversible animation settings.

Imported only on macOS (Intel and Apple chips).
"""
from __future__ import annotations

import os
import re
import signal
import subprocess
import time

from ..speedup import Tweak
from .common import _run

PROTECTED_NAMES = {"kernel_task", "launchd", "windowserver", "loginwindow", "finder", "dock", "systemuiserver",
                   "controlcenter", "notificationcenter", "windowmanager", "spotlight", "coreaudiod", "cfprefsd",
                   "universalaccessd", "textinputmenuagent", "corelocationagent", "talagent", "usernoted",
                   "sharingd", "bird", "cloudd", "secd", "trustd", "pboard", "useractivityd"}


def system_roots() -> list[str]:
    return ["/System/", "/usr/", "/bin/", "/sbin/", "/Library/Apple/", "/Library/Input Methods/"]


def _sysctl(name: str) -> str:
    return _run(["sysctl", "-n", name], 15).stdout.strip()


def memory() -> dict:
    total = int(_sysctl("hw.memsize"))
    out = _run(["vm_stat"], 15).stdout
    m = re.search(r"page size of (\d+) bytes", out)
    page = int(m.group(1)) if m else 4096
    pages = {k.strip().lower(): int(v.strip().rstrip(".")) for k, v in re.findall(r"^([^:\n]+):\s+(\d+)\.?$", out, re.M)}
    # What Activity Monitor counts as not in use: free, inactive and speculative pages.
    avail = (pages.get("pages free", 0) + pages.get("pages inactive", 0) + pages.get("pages speculative", 0)) * page
    return {"total": total, "available": min(total, avail)}


def _ps() -> list[tuple]:
    out = _run(["ps", "-axo", "pid=,ppid=,uid=,pcpu=,rss=,comm="], 30).stdout
    rows = []
    for line in out.splitlines():
        parts = line.split(None, 5)
        if len(parts) == 6:
            rows.append((int(parts[0]), int(parts[1]), int(parts[2]), float(parts[3]), int(parts[4]), parts[5]))
    return rows


def cpu_percent() -> float:
    ncpu = os.cpu_count() or 1
    return round(min(100.0, sum(r[3] for r in _ps()) / ncpu), 1)


def uptime() -> float:
    m = re.search(r"sec = (\d+)", _sysctl("kern.boottime"))
    return time.time() - int(m.group(1)) if m else 0.0


def _app_name(path: str) -> str:
    """The app a process belongs to: helpers inside "Google Chrome.app" count as Google Chrome."""
    for part in path.split("/"):
        if part.endswith(".app"):
            return part[:-4]
    return os.path.basename(path)


def processes() -> list[dict]:
    me, ncpu = os.getuid(), os.cpu_count() or 1
    procs = []
    for pid, ppid, uid, pcpu, rss, comm in _ps():
        procs.append({"pid": pid, "ppid": ppid, "name": os.path.basename(comm), "app": _app_name(comm), "path": comm,
                      "mem": rss * 1024, "cpu": round(pcpu / ncpu, 1), "mine": uid == me})
    return procs


def terminate(pids: list[int], force: bool) -> None:
    for pid in pids:
        try:
            os.kill(pid, signal.SIGKILL if force else signal.SIGTERM)
        except OSError:
            pass


def alive(pids: list[int]) -> list[int]:
    out = []
    for pid in pids:
        try:
            os.kill(pid, 0)
            out.append(pid)
        except PermissionError:
            out.append(pid)
        except OSError:
            pass
    return out


# ---------------------------------------------------------------- tweaks


def _read_default(domain: str, key: str):
    r = _run(["defaults", "read", domain, key], 15)
    return r.stdout.strip() if r.returncode == 0 else None


def _writer(domain: str, key: str, kind: str, restart: str | None = None):
    def write(value) -> None:
        if value is None:
            r = _run(["defaults", "delete", domain, key], 15)
            ok = r.returncode == 0 or _read_default(domain, key) is None
        else:
            if kind == "-bool":
                value = "true" if str(value) in ("1", "true", "YES") else "false"
            r = _run(["defaults", "write", domain, key, kind, str(value)], 15)
            ok = r.returncode == 0
        if not ok:
            raise RuntimeError((r.stderr or r.stdout).strip()[:300] or "defaults")
        if restart:
            subprocess.run(["killall", restart], capture_output=True, timeout=15)

    return write


def tweaks() -> list[Tweak]:
    return [
        Tweak("mac_window_anim", "Tắt hiệu ứng mở cửa sổ",
              "Cửa sổ và hộp thoại hiện ra ngay, không phóng to dần. Giúp máy cũ phản hồi nhanh hơn.",
              lambda: _read_default("-g", "NSAutomaticWindowAnimationsEnabled"),
              _writer("-g", "NSAutomaticWindowAnimationsEnabled", "-bool"), "0", None,
              note="Áp dụng cho các ứng dụng mở sau khi bật."),
        Tweak("mac_dock_launch", "Tắt hiệu ứng nảy khi mở ứng dụng ở Dock",
              "Biểu tượng không nảy lên xuống khi ứng dụng đang mở.",
              lambda: _read_default("com.apple.dock", "launchanim"),
              _writer("com.apple.dock", "launchanim", "-bool", restart="Dock"), "0", None,
              note="Dock sẽ tự mở lại trong một giây."),
        Tweak("mac_dock_minimize", "Thu nhỏ cửa sổ bằng hiệu ứng đơn giản",
              "Dùng hiệu ứng “Thu nhỏ” nhẹ hơn thay cho hiệu ứng “Thần đèn”.",
              lambda: _read_default("com.apple.dock", "mineffect"),
              _writer("com.apple.dock", "mineffect", "-string", restart="Dock"), "scale", None,
              note="Dock sẽ tự mở lại trong một giây."),
    ]
