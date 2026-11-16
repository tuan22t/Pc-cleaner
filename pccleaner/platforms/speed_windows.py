"""Windows: memory, processor, running apps and reversible performance settings.

Imported only on Windows 10/11. Nothing here needs administrator rights.
"""
from __future__ import annotations

import ctypes
import json
import os
import re
import time
import winreg
from ctypes import wintypes

from ..speedup import Tweak
from .common import _ps, _run

k32 = ctypes.windll.kernel32
u32 = ctypes.windll.user32

PROTECTED_NAMES = {
    "system", "idle", "registry", "memory compression", "secure system", "smss", "csrss", "wininit", "winlogon",
    "services", "lsass", "lsaiso", "svchost", "fontdrvhost", "dwm", "explorer", "sihost", "ctfmon", "taskhostw",
    "runtimebroker", "searchhost", "searchapp", "searchindexer", "searchui", "startmenuexperiencehost",
    "shellexperiencehost", "textinputhost", "lockapp", "applicationframehost", "securityhealthservice",
    "securityhealthsystray", "msmpeng", "nissrv", "mpdefendercoreservice", "smartscreen", "spoolsv", "audiodg",
    "conhost", "dllhost", "wudfhost", "unsecapp", "wmiprvse", "dashost", "widgets", "widgetservice",
    "phoneexperiencehost", "crossdevicesvc", "useroobebroker", "systemsettingsbroker", "backgroundtaskhost",
}

HIGH_PERFORMANCE = "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c"
BALANCED = "381b4222-f694-41f0-9685-ff5bb260df2e"
GUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)


def system_roots() -> list[str]:
    root = os.environ.get("SystemRoot") or r"C:\Windows"
    return [root.rstrip("\\") + "\\"]


class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [("dwLength", wintypes.DWORD), ("dwMemoryLoad", wintypes.DWORD),
                ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]


def memory() -> dict:
    m = MEMORYSTATUSEX()
    m.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    if not k32.GlobalMemoryStatusEx(ctypes.byref(m)):
        raise OSError("GlobalMemoryStatusEx")
    return {"total": m.ullTotalPhys, "available": m.ullAvailPhys}


_prev_cpu: list = []


def _cpu_sample() -> tuple[int, int]:
    idle, kernel, user = wintypes.FILETIME(), wintypes.FILETIME(), wintypes.FILETIME()
    k32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user))
    v = lambda ft: (ft.dwHighDateTime << 32) | ft.dwLowDateTime  # noqa: E731
    total = v(kernel) + v(user)  # kernel time includes idle time
    return total - v(idle), total


def cpu_percent() -> float:
    if not _prev_cpu:
        _prev_cpu[:] = _cpu_sample()
        time.sleep(0.25)
    busy, total = _cpu_sample()
    b0, t0 = _prev_cpu
    _prev_cpu[:] = [busy, total]
    return round(100 * (busy - b0) / (total - t0), 1) if total > t0 else 0.0


def uptime() -> float:
    k32.GetTickCount64.restype = ctypes.c_ulonglong
    return k32.GetTickCount64() / 1000


def _session() -> int:
    sid = wintypes.DWORD()
    k32.ProcessIdToSessionId(os.getpid(), ctypes.byref(sid))
    return sid.value


def processes() -> list[dict]:
    raw = _ps(
        "Get-CimInstance Win32_Process | ForEach-Object { [pscustomobject]@{"
        "p=$_.ProcessId; pp=$_.ParentProcessId; n=$_.Name; x=$_.ExecutablePath; s=$_.SessionId;"
        "m=$_.WorkingSetSize; c=([double]$_.KernelModeTime + [double]$_.UserModeTime) / 1e7 } }"
        " | ConvertTo-Json -Compress", timeout=60)
    data = json.loads(raw or "[]")
    if isinstance(data, dict):
        data = [data]
    me = _session()
    procs = []
    for d in data:
        name = str(d.get("n") or "")
        if name.lower().endswith(".exe"):
            name = name[:-4]
        procs.append({"pid": int(d.get("p") or 0), "ppid": int(d.get("pp") or 0), "name": name,
                      "path": d.get("x") or "", "mem": int(d.get("m") or 0), "cpu_time": d.get("c"),
                      "cpu": None, "mine": d.get("s") == me and me != 0})
    return [p for p in procs if p["pid"] > 4]


def terminate(pids: list[int], force: bool) -> None:
    """Without force, Windows asks each window to close (the app may ask to save first)."""
    for i in range(0, len(pids), 50):
        cmd = ["taskkill"] + (["/F"] if force else [])
        for pid in pids[i:i + 50]:
            cmd += ["/PID", str(pid)]
        _run(cmd, 60)


def alive(pids: list[int]) -> list[int]:
    out = []
    for pid in pids:
        h = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            continue
        code = wintypes.DWORD()
        if k32.GetExitCodeProcess(h, ctypes.byref(code)) and code.value == 259:  # STILL_ACTIVE
            out.append(pid)
        k32.CloseHandle(h)
    return out


# ---------------------------------------------------------------- tweaks: power plan


def _active_scheme() -> str:
    m = GUID.search(_run(["powercfg", "/getactivescheme"], 30).stdout)
    if not m:
        raise RuntimeError("powercfg")
    return m.group(0).lower()


def _set_scheme(guid) -> None:
    guid = str(guid or BALANCED)
    if not GUID.fullmatch(guid):
        raise ValueError(guid)
    r = _run(["powercfg", "/setactive", guid], 30)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout).strip()[:300] or "powercfg")


def _power_available() -> str | None:
    if HIGH_PERFORMANCE not in _run(["powercfg", "/list"], 30).stdout.lower():
        return ("Máy này không có chế độ nguồn Hiệu suất cao (thường gặp ở laptop đời mới). "
                "Hãy chọn “Hiệu suất tốt nhất” trong Cài đặt > Hệ thống > Nguồn.")
    return None


class SYSTEM_POWER_STATUS(ctypes.Structure):
    _fields_ = [("ACLineStatus", ctypes.c_ubyte), ("BatteryFlag", ctypes.c_ubyte),
                ("BatteryLifePercent", ctypes.c_ubyte), ("SystemStatusFlag", ctypes.c_ubyte),
                ("BatteryLifeTime", wintypes.DWORD), ("BatteryFullLifeTime", wintypes.DWORD)]


def _has_battery() -> bool:
    s = SYSTEM_POWER_STATUS()
    return bool(k32.GetSystemPowerStatus(ctypes.byref(s))) and s.BatteryFlag not in (128, 255)


# ---------------------------------------------------------------- tweaks: transparency

PERSONALIZE = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"


def _get_transparency():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, PERSONALIZE) as k:
            return int(winreg.QueryValueEx(k, "EnableTransparency")[0])
    except OSError:
        return None


def _set_transparency(value) -> None:
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, PERSONALIZE, 0, winreg.KEY_SET_VALUE) as k:
        if value is None:
            try:
                winreg.DeleteValue(k, "EnableTransparency")
            except FileNotFoundError:
                pass
        else:
            winreg.SetValueEx(k, "EnableTransparency", 0, winreg.REG_DWORD, int(value))
    _broadcast("ImmersiveColorSet")


def _broadcast(area: str) -> None:
    """Tell open windows that a setting changed, so it applies without signing out."""
    res = wintypes.DWORD()
    u32.SendMessageTimeoutW(0xFFFF, 0x001A, 0, ctypes.c_wchar_p(area), 0x0002, 1000, ctypes.byref(res))


# ---------------------------------------------------------------- tweaks: animations

SPI_GETANIMATION, SPI_SETANIMATION = 0x0048, 0x0049
SPI_GETCLIENTAREAANIMATION, SPI_SETCLIENTAREAANIMATION = 0x1042, 0x1043
SPI_GETMENUANIMATION, SPI_SETMENUANIMATION = 0x1002, 0x1003
SPIF_UPDATE = 0x01 | 0x02  # save to the user profile and tell open windows


class ANIMATIONINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("iMinAnimate", ctypes.c_int)]


def _get_bool(action: int) -> int:
    v = wintypes.BOOL()
    u32.SystemParametersInfoW(action, 0, ctypes.byref(v), 0)
    return int(bool(v.value))


def _get_animations() -> list[int]:
    ai = ANIMATIONINFO(ctypes.sizeof(ANIMATIONINFO), 0)
    u32.SystemParametersInfoW(SPI_GETANIMATION, ai.cbSize, ctypes.byref(ai), 0)
    return [int(bool(ai.iMinAnimate)), _get_bool(SPI_GETCLIENTAREAANIMATION), _get_bool(SPI_GETMENUANIMATION)]


def _set_animations(value) -> None:
    minimize, client, menu = [int(bool(x)) for x in (value or [1, 1, 1])]
    ai = ANIMATIONINFO(ctypes.sizeof(ANIMATIONINFO), minimize)
    ok = u32.SystemParametersInfoW(SPI_SETANIMATION, ai.cbSize, ctypes.byref(ai), SPIF_UPDATE)
    ok = u32.SystemParametersInfoW(SPI_SETCLIENTAREAANIMATION, 0, ctypes.c_void_p(client), SPIF_UPDATE) and ok
    ok = u32.SystemParametersInfoW(SPI_SETMENUANIMATION, 0, ctypes.c_void_p(menu), SPIF_UPDATE) and ok
    if not ok:
        raise ctypes.WinError()


def tweaks() -> list[Tweak]:
    return [
        Tweak("win_power", "Chế độ nguồn Hiệu suất cao",
              "Bộ xử lý giữ tốc độ cao thay vì tiết kiệm điện, máy phản hồi nhanh hơn khi làm việc nặng.",
              _active_scheme, _set_scheme, HIGH_PERFORMANCE, BALANCED, _power_available,
              note="Máy có pin sẽ hết pin nhanh hơn khi bật." if _has_battery() else ""),
        Tweak("win_animations", "Tắt hiệu ứng chuyển động",
              "Cửa sổ, menu mở ra và thu nhỏ ngay lập tức, không chạy hiệu ứng. Giúp máy yếu mượt hơn.",
              _get_animations, _set_animations, [0, 0, 0], [1, 1, 1]),
        Tweak("win_transparency", "Tắt hiệu ứng trong suốt",
              "Thanh tác vụ, menu Start và cửa sổ hệ thống dùng nền đặc thay vì nền mờ trong suốt, đỡ tốn card đồ họa.",
              _get_transparency, _set_transparency, 0, None),
    ]
