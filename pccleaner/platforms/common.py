"""Helpers shared by the platform modules: running commands, PowerShell, admin checks."""
from __future__ import annotations

import base64
import json
import os
import subprocess
import tempfile
from pathlib import Path

from .. import paths


def _run(cmd: list[str], timeout: int = 60) -> subprocess.CompletedProcess:
    kw = {}
    if paths.IS_WINDOWS:
        kw["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace", **kw)


def _ps(script: str, timeout: int = 90) -> str:
    """Run PowerShell and return stdout (UTF-8)."""
    full = "[Console]::OutputEncoding=[Text.Encoding]::UTF8;$ErrorActionPreference='Stop';" + script
    enc = base64.b64encode(full.encode("utf-16-le")).decode()
    r = _run(["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", enc], timeout)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout).strip()[:400])
    return r.stdout


def _ps_admin(script: str, timeout: int = 300) -> dict:
    """Run PowerShell elevated (shows the Windows UAC prompt). Returns the JSON the script writes."""
    out = Path(tempfile.mkdtemp()) / "result.json"
    inner = (
        "$ErrorActionPreference='Stop';"
        f"$out='{out}';"
        "try {" + script + "; if (-not (Test-Path $out)) { '{\"ok\":true}' | Set-Content -Encoding UTF8 $out } }"
        " catch { @{ok=$false; error=$_.Exception.Message} | ConvertTo-Json | Set-Content -Encoding UTF8 $out }"
    )
    enc = base64.b64encode(inner.encode("utf-16-le")).decode()
    outer = (
        "Start-Process powershell -Verb RunAs -Wait -WindowStyle Hidden "
        f"-ArgumentList '-NoProfile','-NonInteractive','-EncodedCommand','{enc}'"
    )
    try:
        _ps(outer, timeout)
    except RuntimeError as e:
        if "canceled" in str(e).lower() or "hủy" in str(e).lower() or "1223" in str(e):
            raise PermissionError("Anh/chị đã từ chối cấp quyền quản trị, nên chưa thay đổi gì.")
        raise
    if not out.exists():
        raise PermissionError("Không nhận được kết quả từ tác vụ cần quyền quản trị.")
    data = json.loads(out.read_text(encoding="utf-8-sig") or "{}")
    if not data.get("ok", False):
        raise RuntimeError(data.get("error") or "Không thực hiện được")
    return data


def is_admin() -> bool:
    if paths.IS_WINDOWS:
        try:
            import ctypes

            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:  # noqa: BLE001
            return False
    return os.geteuid() == 0


# ================================================================ Windows


def background_thread() -> None:
    """Lower the CPU and disk priority of the calling thread (scans, searches, cleanups).

    The computer stays responsive while a long job runs. Best effort: if the
    system refuses, the job simply runs at normal priority.
    """
    try:
        if paths.IS_WINDOWS:
            import ctypes

            k32 = ctypes.windll.kernel32
            k32.SetThreadPriority(k32.GetCurrentThread(), 0x00010000)  # THREAD_MODE_BACKGROUND_BEGIN (CPU + I/O)
        elif paths.IS_MAC:
            import ctypes
            import ctypes.util

            libc = ctypes.CDLL(ctypes.util.find_library("c"))
            libc.setiopolicy_np(0, 1, 3)  # disk I/O, this thread, IOPOL_THROTTLE
            libc.pthread_set_qos_class_self_np(0x11, 0)  # QOS_CLASS_UTILITY
        else:
            import threading

            os.setpriority(os.PRIO_PROCESS, threading.get_native_id(), 10)
    except Exception:  # noqa: BLE001
        pass
