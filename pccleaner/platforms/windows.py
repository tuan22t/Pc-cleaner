"""Windows: startup programs, scheduled tasks, services, restore points, system junk.

Imported only on Windows.
"""
from __future__ import annotations

import concurrent.futures
import json
import os
import time
import winreg

from .. import APP_NAME, db
from pathlib import Path

from ..junk_base import Category, env, register_source
from ..startup_base import Provider, _change, classify, register_provider
from .common import _ps, _ps_admin

RUN = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN32 = r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Run"
APPROVED = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved"
HIVES = {"HKCU": winreg.HKEY_CURRENT_USER, "HKLM": winreg.HKEY_LOCAL_MACHINE}


def _ps_list(script: str) -> list[dict]:
    """A PowerShell query that prints JSON; [] when it fails (the listing goes on without it)."""
    try:
        raw = _ps(script).strip()
        out = json.loads(raw) if raw else []
    except Exception:  # noqa: BLE001
        return []
    return [out] if isinstance(out, dict) else out

def _reg_values(hive, key) -> list[tuple[str, object]]:
    out = []
    try:
        with winreg.OpenKey(hive, key, 0, winreg.KEY_READ | getattr(winreg, "KEY_WOW64_64KEY", 0)) as k:
            i = 0
            while True:
                try:
                    name, val, _t = winreg.EnumValue(k, i)
                except OSError:
                    break
                out.append((name, val))
                i += 1
    except OSError:
        pass
    return out


def _approved_enabled(hive_name: str, sub: str, value: str) -> bool:
    for name, val in _reg_values(HIVES[hive_name], APPROVED + "\\" + sub):
        if name.lower() == value.lower() and isinstance(val, (bytes, bytearray)) and val:
            return not (val[0] & 1)  # 02/06 = enabled, 03/07 = disabled
    return True


def _approved_data(enable: bool) -> bytes:
    if enable:
        return bytes([2]) + bytes(11)
    # Same layout Task Manager writes: flag + FILETIME of the change.
    ft = int((time.time() + 11644473600) * 10_000_000)
    return bytes([3, 0, 0, 0]) + ft.to_bytes(8, "little")


def _set_approved(hive_name: str, sub: str, value: str, enable: bool) -> None:
    data = _approved_data(enable)
    key = APPROVED + "\\" + sub
    try:
        with winreg.CreateKeyEx(HIVES[hive_name], key, 0, winreg.KEY_SET_VALUE | getattr(winreg, "KEY_WOW64_64KEY", 0)) as k:
            winreg.SetValueEx(k, value, 0, winreg.REG_BINARY, data)
    except PermissionError:
        if hive_name != "HKLM":
            raise
        hexdata = ",".join(f"0x{b:02x}" for b in data)
        safe_value = value.replace("'", "''")
        _ps_admin(
            f"New-Item -Path 'HKLM:\\{key}' -Force | Out-Null;"
            f"Set-ItemProperty -Path 'HKLM:\\{key}' -Name '{safe_value}' -Type Binary -Value ([byte[]]({hexdata}))"
        )


def _win_items() -> list[dict]:
    items: list[dict] = []
    # Run keys
    for hive_name, key, sub in (("HKCU", RUN, "Run"), ("HKLM", RUN, "Run"), ("HKLM", RUN32, "Run32")):
        for name, cmd in _reg_values(HIVES[hive_name], key):
            if not name:
                continue
            label, why = classify(name, str(cmd))
            items.append({
                "id": f"run|{hive_name}|{sub}|{name}", "kind": "run", "name": name, "command": str(cmd),
                "where": "Khởi động cùng Windows (mọi người dùng)" if hive_name == "HKLM" else "Khởi động cùng Windows (tài khoản này)",
                "enabled": _approved_enabled(hive_name, sub, name), "admin": hive_name == "HKLM",
                "label": label, "why": why,
            })
    # Startup folders
    appdata = os.environ.get("APPDATA", "")
    progdata = os.environ.get("ProgramData", r"C:\ProgramData")
    for hive_name, folder in (
        ("HKCU", os.path.join(appdata, r"Microsoft\Windows\Start Menu\Programs\Startup")),
        ("HKLM", os.path.join(progdata, r"Microsoft\Windows\Start Menu\Programs\StartUp")),
    ):
        if not os.path.isdir(folder):
            continue
        for fn in sorted(os.listdir(folder)):
            if fn.lower() == "desktop.ini":
                continue
            label, why = classify(fn)
            items.append({
                "id": f"folder|{hive_name}|{fn}", "kind": "folder", "name": os.path.splitext(fn)[0],
                "command": os.path.join(folder, fn), "where": "Thư mục Startup",
                "enabled": _approved_enabled(hive_name, "StartupFolder", fn), "admin": hive_name == "HKLM",
                "label": label, "why": why,
            })
    # Scheduled tasks (non-Microsoft)
    # The two PowerShell queries are slow to start (seconds each on a cold machine): run them side by side.
    with concurrent.futures.ThreadPoolExecutor(2) as pool:
        tasks_job = pool.submit(_ps_list,
            "Get-ScheduledTask | Where-Object { $_.TaskPath -notlike '\\Microsoft\\*' } | ForEach-Object {"
            " [pscustomobject]@{ name=$_.TaskName; path=$_.TaskPath; state=[string]$_.State; author=$_.Author;"
            " exec=(($_.Actions | ForEach-Object { $_.Execute + ' ' + $_.Arguments }) -join '; ') } } | ConvertTo-Json -Compress")
        services_job = pool.submit(_ps_list,
            "Get-CimInstance Win32_Service | ForEach-Object { [pscustomobject]@{ name=$_.Name; display=$_.DisplayName;"
            " mode=$_.StartMode; state=$_.State; path=$_.PathName } } | ConvertTo-Json -Compress")
        tasks, services = tasks_job.result(), services_job.result()
    for t in tasks:
        label, why = classify(t.get("name", ""), t.get("exec", ""), t.get("author", ""))
        items.append({
            "id": f"task|{t['path']}|{t['name']}", "kind": "task", "name": t["name"], "command": t.get("exec") or "",
            "where": "Tác vụ theo lịch (Task Scheduler)", "enabled": t.get("state") != "Disabled",
            "admin": True, "label": label, "why": why,
        })
    # Services: third-party, automatic start (plus those we switched to Manual)
    windir = os.path.normcase(os.environ.get("SystemRoot", r"C:\Windows"))
    for s in services:
        p = os.path.normcase((s.get("path") or "").strip('"'))
        if not p or windir in p or "\\windows defender\\" in p or "\\microsoft\\" in p:
            continue  # Windows' own services are never listed
        sid = f"service|{s['name']}"
        ours = _change(sid)
        if s.get("mode") != "Auto" and not ours:
            continue
        label, why = classify(s.get("display", ""), s.get("name", ""), p)
        items.append({
            "id": sid, "kind": "service", "name": s.get("display") or s["name"], "command": s.get("path") or "",
            "where": "Dịch vụ chạy nền (đang chạy)" if s.get("state") == "Running" else "Dịch vụ chạy nền (đang dừng)",
            "enabled": s.get("mode") == "Auto", "admin": True, "label": label, "why": why,
        })
    return items


def _win_set(item: dict, enable: bool) -> None:
    kind = item["kind"]
    if kind == "run":
        _, hive_name, sub, name = item["id"].split("|", 3)
        _set_approved(hive_name, sub, name, enable)
    elif kind == "folder":
        _, hive_name, fn = item["id"].split("|", 2)
        _set_approved(hive_name, "StartupFolder", fn, enable)
    elif kind == "task":
        _, tpath, tname = item["id"].split("|", 2)
        verb = "Enable-ScheduledTask" if enable else "Disable-ScheduledTask"
        cmd = f"{verb} -TaskPath '{tpath.replace(chr(39), chr(39) * 2)}' -TaskName '{tname.replace(chr(39), chr(39) * 2)}' | Out-Null"
        try:
            _ps(cmd)
        except RuntimeError:
            _ps_admin(cmd)
    elif kind == "service":
        name = item["id"].split("|", 1)[1].replace("'", "''")
        mode = "Automatic" if enable else "Manual"
        _ps_admin(f"Set-Service -Name '{name}' -StartupType {mode}")
    else:
        raise ValueError(kind)


def create_restore_point() -> dict:
    """Windows only: create a System Restore point (asks for administrator rights)."""
    try:
        _ps_admin(
            "Enable-ComputerRestore -Drive \"$env:SystemDrive\\\" -ErrorAction SilentlyContinue;"
            f"Checkpoint-Computer -Description '{APP_NAME} - before turning off startup programs' -RestorePointType MODIFY_SETTINGS"
        )
        db.set_setting("last_restore_point", time.time())
        return {"ok": True}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}


register_provider(Provider("windows", {"run", "folder", "task", "service"}, _win_items, _win_set))


@register_source
def junk_categories() -> list[Category]:
    home = str(Path.home())
    cats: list[Category] = []
    local = env("LOCALAPPDATA", os.path.join(home, "AppData", "Local"))
    windir = env("SystemRoot", r"C:\Windows")
    progdata = env("ProgramData", r"C:\ProgramData")
    temp = env("TEMP", os.path.join(local, "Temp"))
    cats += [
        Category("win_user_temp", "File tạm của người dùng", "Thư mục Temp: chương trình tạo ra khi cài đặt, giải nén, xem trước file… rồi bỏ lại.", [temp]),
        Category("win_temp", "File tạm của Windows", "Thư mục Windows\\Temp.", [os.path.join(windir, "Temp")], admin=True),
        Category("win_update", "Bản cập nhật Windows đã tải về", "Bộ cài cập nhật đã cài xong; Windows sẽ tải lại nếu cần.", [os.path.join(windir, "SoftwareDistribution", "Download")], min_age_hours=72, admin=True),
        Category("win_dumps", "File báo lỗi (crash dump)", "Bản ghi bộ nhớ khi chương trình hoặc Windows bị lỗi. Chỉ cần khi gửi cho kỹ thuật viên.", [os.path.join(local, "CrashDumps"), os.path.join(windir, "Minidump"), os.path.join(windir, "LiveKernelReports")], min_age_hours=0),
        Category("win_wer", "Báo cáo lỗi Windows", "Báo cáo lỗi đã gửi hoặc chờ gửi cho Microsoft.", [os.path.join(local, "Microsoft", "Windows", "WER"), os.path.join(progdata, "Microsoft", "Windows", "WER")], min_age_hours=0),
        Category("win_thumbs", "Bộ nhớ đệm ảnh thu nhỏ", "Ảnh thu nhỏ trong File Explorer; Windows tự tạo lại khi mở thư mục.", [os.path.join(local, "Microsoft", "Windows", "Explorer")], file_glob="thumbcache_*.db", min_age_hours=0),
        Category("browser_cache", "Bộ nhớ đệm trình duyệt", "Chrome, Edge, Firefox, Cốc Cốc. Không mất mật khẩu, lịch sử hay dấu trang. Nên đóng trình duyệt trước.", [
            os.path.join(local, "Google", "Chrome", "User Data", "*", d) for d in ("Cache", "Code Cache", "GPUCache")
        ] + [
            os.path.join(local, "Microsoft", "Edge", "User Data", "*", d) for d in ("Cache", "Code Cache", "GPUCache")
        ] + [
            os.path.join(local, "CocCoc", "Browser", "User Data", "*", d) for d in ("Cache", "Code Cache", "GPUCache")
        ] + [os.path.join(local, "Mozilla", "Firefox", "Profiles", "*", "cache2")], min_age_hours=1),
        Category("win_prefetch", "Prefetch", "Dữ liệu giúp Windows mở chương trình nhanh hơn. Xóa thì lần mở đầu tiên sẽ chậm hơn một chút.", [os.path.join(windir, "Prefetch")], label="caution", min_age_hours=0, admin=True),
    ]
    return cats
