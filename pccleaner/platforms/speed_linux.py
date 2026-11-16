"""Linux: speed-up helpers, only used while developing (no settings tweaks)."""
from __future__ import annotations

import os
import signal
import subprocess
import time

PROTECTED_NAMES = {"systemd", "init", "xorg", "xwayland", "gnome-shell", "kwin_x11", "kwin_wayland", "plasmashell",
                   "dbus-daemon", "pulseaudio", "pipewire", "wireplumber", "sshd", "login", "bash", "sh"}

_prev_cpu: list = []


def system_roots() -> list[str]:
    return ["/usr/lib/systemd/", "/lib/systemd/", "/usr/libexec/", "/sbin/", "/usr/sbin/"]


def memory() -> dict:
    info = {}
    with open("/proc/meminfo") as f:
        for line in f:
            k, v = line.split(":", 1)
            info[k] = int(v.split()[0]) * 1024
    return {"total": info["MemTotal"], "available": info.get("MemAvailable", info.get("MemFree", 0))}


def _cpu_sample() -> tuple[int, int]:
    with open("/proc/stat") as f:
        vals = [int(x) for x in f.readline().split()[1:]]
    idle = vals[3] + (vals[4] if len(vals) > 4 else 0)
    return sum(vals) - idle, sum(vals)


def cpu_percent() -> float:
    if not _prev_cpu:
        _prev_cpu[:] = _cpu_sample()
        time.sleep(0.2)
    busy, total = _cpu_sample()
    b0, t0 = _prev_cpu
    _prev_cpu[:] = [busy, total]
    return round(100 * (busy - b0) / (total - t0), 1) if total > t0 else 0.0


def uptime() -> float:
    with open("/proc/uptime") as f:
        return float(f.read().split()[0])


def processes() -> list[dict]:
    out = subprocess.run(["ps", "-axo", "pid=,ppid=,uid=,pcpu=,rss=,comm="], capture_output=True, text=True,
                         timeout=30).stdout
    me, ncpu = os.getuid(), os.cpu_count() or 1
    procs = []
    for line in out.splitlines():
        parts = line.split(None, 5)
        if len(parts) < 6:
            continue
        pid, ppid, uid, pcpu, rss, comm = parts
        procs.append({"pid": int(pid), "ppid": int(ppid), "name": comm, "path": "", "mem": int(rss) * 1024,
                      "cpu": round(float(pcpu) / ncpu, 1), "mine": int(uid) == me})
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
        except OSError:
            continue
        try:  # a finished child stays a zombie until reaped: it is not running
            with open(f"/proc/{pid}/stat") as f:
                if f.read().rsplit(")", 1)[1].split()[0] == "Z":
                    continue
        except OSError:
            continue
        out.append(pid)
    return out


def tweaks() -> list:
    return []
