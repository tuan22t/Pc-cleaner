"""Programs that start with the computer or keep running in the background.

Rules agreed for this feature:
* items are only ever *disabled*, never uninstalled or deleted;
* every change can be turned back on with one click;
* on Windows, a System Restore point is offered before changes that need
  administrator rights;
* each item gets a recommendation: "safe" (có thể tắt), "keep" (nên giữ) or
  "unknown" (chưa rõ).

Windows: Run keys and Startup folders (disabled the same way Task Manager does,
through the StartupApproved registry keys), non-Microsoft scheduled tasks, and
non-Microsoft services set to start automatically (switched to Manual).
macOS: Login Items, LaunchAgents and LaunchDaemons (via ``launchctl disable``).
"""
from __future__ import annotations

import base64
import json
import os
import plistlib
import subprocess
import tempfile
import time
from pathlib import Path

from . import db, paths

# ---------------------------------------------------------------- labels

KEEP_WORDS = [
    "defender", "securityhealth", "antivirus", "kaspersky", "bkav", "eset", "avast", "avg", "norton", "mcafee",
    "bitdefender", "malwarebytes", "realtek", "intel", "nvidia", "amd", "radeon", "synaptics", "elan", "touchpad",
    "audio", "bluetooth", "wifi", "wlan", "driver", "vpn", "unikey", "evkey", "ibus", "openkey", "1password",
    "bitwarden", "lastpass", "backup", "time machine", "littlesnitch", "little snitch", "battery", "dolby",
]
SAFE_WORDS = [
    "update", "updater", "helper", "spotify", "steam", "epic", "discord", "skype", "teams", "zoom", "zalo",
    "telegram", "messenger", "whatsapp", "viber", "adobe", "acrobat", "creative cloud", "ccleaner", "dropbox",
    "google drive", "onedrive", "itunes", "icloud", "garena", "riot", "battle.net", "ubisoft", "origin", "ea app",
    "utorrent", "bittorrent", "idm", "internet download manager", "cortana", "edge", "chrome", "opera", "coccoc",
    "brave", "firefox", "java", "office", "keystone", "googlesoftwareupdate", "notion", "slack", "figma",
]


def classify(*texts: str) -> tuple[str, str]:
    t = " ".join(x for x in texts if x).lower()
    for w in KEEP_WORDS:
        if w in t:
            return "keep", "Liên quan đến bảo mật, phần cứng hoặc bộ gõ. Nên giữ."
    for w in SAFE_WORDS:
        if w in t:
            return "safe", "Ứng dụng hoặc trình cập nhật. Tắt chỉ khiến nó không tự mở cùng máy, mở tay vẫn chạy bình thường."
    return "unknown", "Chưa rõ. Nếu không nhận ra chương trình này, hãy tìm hiểu trước khi tắt."


def _log_change(item: dict, original: dict) -> None:
    conn = db.connect()
    conn.execute("UPDATE startup_changes SET active=0 WHERE item_id=?", (item["id"],))
    conn.execute(
        "INSERT INTO startup_changes(ts, item_id, kind, name, original, active) VALUES (?,?,?,?,?,1)",
        (time.time(), item["id"], item["kind"], item["name"], json.dumps(original)),
    )
    conn.commit()


def _close_change(item_id: str) -> None:
    conn = db.connect()
    conn.execute("UPDATE startup_changes SET active=0 WHERE item_id=?", (item_id,))
    conn.commit()


def _change(item_id: str) -> dict | None:
    r = db.connect().execute(
        "SELECT original FROM startup_changes WHERE item_id=? AND active=1 ORDER BY id DESC LIMIT 1", (item_id,)
    ).fetchone()
    return json.loads(r["original"]) if r else None


def history() -> list[dict]:
    rows = db.connect().execute("SELECT * FROM startup_changes ORDER BY id DESC LIMIT 200").fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------- helpers

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

if paths.IS_WINDOWS:
    import winreg

    RUN = r"Software\Microsoft\Windows\CurrentVersion\Run"
    RUN32 = r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Run"
    APPROVED = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved"
    HIVES = {"HKCU": winreg.HKEY_CURRENT_USER, "HKLM": winreg.HKEY_LOCAL_MACHINE}


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
                "where": f"Khởi động cùng Windows ({'mọi người dùng' if hive_name == 'HKLM' else 'tài khoản này'})",
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
    try:
        raw = _ps(
            "Get-ScheduledTask | Where-Object { $_.TaskPath -notlike '\\Microsoft\\*' } | ForEach-Object {"
            " [pscustomobject]@{ name=$_.TaskName; path=$_.TaskPath; state=[string]$_.State; author=$_.Author;"
            " exec=(($_.Actions | ForEach-Object { $_.Execute + ' ' + $_.Arguments }) -join '; ') } } | ConvertTo-Json -Compress"
        ).strip()
        tasks = json.loads(raw) if raw else []
        if isinstance(tasks, dict):
            tasks = [tasks]
    except Exception:  # noqa: BLE001
        tasks = []
    for t in tasks:
        label, why = classify(t.get("name", ""), t.get("exec", ""), t.get("author", ""))
        items.append({
            "id": f"task|{t['path']}|{t['name']}", "kind": "task", "name": t["name"], "command": t.get("exec") or "",
            "where": "Tác vụ theo lịch (Task Scheduler)", "enabled": t.get("state") != "Disabled",
            "admin": True, "label": label, "why": why,
        })
    # Services: third-party, automatic start (plus those we switched to Manual)
    try:
        raw = _ps(
            "Get-CimInstance Win32_Service | ForEach-Object { [pscustomobject]@{ name=$_.Name; display=$_.DisplayName;"
            " mode=$_.StartMode; state=$_.State; path=$_.PathName } } | ConvertTo-Json -Compress"
        ).strip()
        services = json.loads(raw) if raw else []
        if isinstance(services, dict):
            services = [services]
    except Exception:  # noqa: BLE001
        services = []
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
            "where": f"Dịch vụ chạy nền ({'đang chạy' if s.get('state') == 'Running' else 'đang dừng'})",
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
    if not paths.IS_WINDOWS:
        return {"ok": False, "error": "Chỉ có trên Windows. Trên macOS hãy dùng Time Machine."}
    try:
        _ps_admin(
            "Enable-ComputerRestore -Drive \"$env:SystemDrive\\\" -ErrorAction SilentlyContinue;"
            "Checkpoint-Computer -Description 'PC Cleaner - truoc khi tat chuong trinh khoi dong' -RestorePointType MODIFY_SETTINGS"
        )
        db.set_setting("last_restore_point", time.time())
        return {"ok": True}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}


# ================================================================ macOS

def _uid() -> int:
    return os.getuid()


def _launchctl_disabled(domain: str) -> set[str]:
    r = _run(["launchctl", "print-disabled", domain])
    out = set()
    for line in r.stdout.splitlines():
        line = line.strip()
        if "=>" in line:
            label, state = [x.strip().strip('"') for x in line.split("=>", 1)]
            if state in ("disabled", "true"):
                out.add(label)
    return out


def _plist_info(path: str) -> dict | None:
    try:
        with open(path, "rb") as f:
            data = plistlib.load(f)
    except Exception:  # noqa: BLE001
        return None
    label = data.get("Label")
    if not label:
        return None
    prog = data.get("Program") or " ".join(data.get("ProgramArguments", []) or [])
    return {"label": label, "program": prog, "run_at_load": bool(data.get("RunAtLoad")), "keep_alive": bool(data.get("KeepAlive"))}


def _mac_login_items() -> list[dict]:
    js = ("JSON.stringify(Application('System Events').loginItems().map(i => "
          "({name: i.name(), path: i.path(), hidden: i.hidden()})))")
    r = _run(["osascript", "-l", "JavaScript", "-e", js], timeout=30)
    if r.returncode != 0:
        return []
    try:
        return json.loads(r.stdout or "[]")
    except ValueError:
        return []


def _mac_items() -> list[dict]:
    items: list[dict] = []
    uid = _uid()
    gui = f"gui/{uid}"
    disabled_gui = _launchctl_disabled(gui)
    disabled_sys = _launchctl_disabled("system")
    for li in _mac_login_items():
        label, why = classify(li.get("name", ""), li.get("path", ""))
        items.append({
            "id": f"login|{li.get('name')}", "kind": "login", "name": li.get("name") or "?", "command": li.get("path") or "",
            "where": "Mục đăng nhập (Login Items)", "enabled": True, "admin": False, "label": label, "why": why,
        })
    # Login items we removed are shown again so they can be turned back on.
    for r in db.connect().execute("SELECT item_id, name FROM startup_changes WHERE kind='login' AND active=1"):
        if not any(i["id"] == r["item_id"] for i in items):
            orig = _change(r["item_id"]) or {}
            label, why = classify(r["name"], orig.get("path", ""))
            items.append({"id": r["item_id"], "kind": "login", "name": r["name"], "command": orig.get("path", ""),
                          "where": "Mục đăng nhập (Login Items)", "enabled": False, "admin": False, "label": label, "why": why})
    for folder, kind, domain, disabled, admin in (
        (os.path.expanduser("~/Library/LaunchAgents"), "agent", gui, disabled_gui, False),
        ("/Library/LaunchAgents", "agent", gui, disabled_gui, False),
        ("/Library/LaunchDaemons", "daemon", "system", disabled_sys, True),
    ):
        if not os.path.isdir(folder):
            continue
        for fn in sorted(os.listdir(folder)):
            if not fn.endswith(".plist"):
                continue
            full = os.path.join(folder, fn)
            info = _plist_info(full)
            if not info or info["label"].startswith("com.apple."):
                continue
            label, why = classify(info["label"], info["program"])
            items.append({
                "id": f"{kind}|{domain}|{info['label']}|{full}", "kind": kind, "name": info["label"],
                "command": info["program"],
                "where": "Chạy nền cho tài khoản này (LaunchAgent)" if kind == "agent" else "Dịch vụ hệ thống (LaunchDaemon)",
                "enabled": info["label"] not in disabled, "admin": admin, "label": label, "why": why,
            })
    return items


def _osascript_admin(shell: str) -> None:
    esc = shell.replace("\\", "\\\\").replace('"', '\\"')
    r = _run(["osascript", "-e", f'do shell script "{esc}" with administrator privileges'], timeout=300)
    if r.returncode != 0:
        if "-128" in r.stderr:
            raise PermissionError("Anh/chị đã hủy nhập mật khẩu quản trị, nên chưa thay đổi gì.")
        raise RuntimeError(r.stderr.strip()[:300])


def _mac_set(item: dict, enable: bool) -> None:
    kind = item["kind"]
    if kind == "login":
        name = item["id"].split("|", 1)[1]
        if enable:
            orig = _change(item["id"]) or {}
            path = orig.get("path") or item.get("command")
            if not path:
                raise RuntimeError("Không còn biết đường dẫn của mục này")
            js = (f"Application('System Events').loginItems.push(Application('System Events').LoginItem("
                  f"{{path: {json.dumps(path)}, hidden: {json.dumps(bool(orig.get('hidden')))}}}))")
        else:
            js = (f"var se=Application('System Events'); var it=se.loginItems.byName({json.dumps(name)});"
                  "it.delete()")
        r = _run(["osascript", "-l", "JavaScript", "-e", js], timeout=30)
        if r.returncode != 0:
            raise RuntimeError(r.stderr.strip()[:300] or "osascript lỗi")
        return
    _k, domain, label, plist = item["id"].split("|", 3)
    target = f"{domain}/{label}"
    if domain == "system":
        if enable:
            _osascript_admin(f"launchctl enable {target}; launchctl bootstrap system '{plist}' || true")
        else:
            _osascript_admin(f"launchctl disable {target}; launchctl bootout {target} || true")
        return
    r = _run(["launchctl", "enable" if enable else "disable", target])
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip()[:300] or "launchctl lỗi")
    if enable:
        _run(["launchctl", "bootstrap", domain, plist])  # may already be loaded; that's fine
    else:
        _run(["launchctl", "bootout", target])  # stop it now; fine if it wasn't running


# ================================================================ public API

def list_items() -> list[dict]:
    if paths.IS_WINDOWS:
        items = _win_items()
    elif paths.IS_MAC:
        items = _mac_items()
    else:
        items = []
    disabled_by_us = {r["item_id"] for r in db.connect().execute("SELECT item_id FROM startup_changes WHERE active=1")}
    for it in items:
        it["changed_by_app"] = it["id"] in disabled_by_us
    order = {"safe": 0, "unknown": 1, "keep": 2}
    items.sort(key=lambda i: (not i["enabled"], order.get(i["label"], 3), i["name"].lower()))
    return items


def set_enabled(item_id: str, enable: bool) -> dict:
    """Turn one item off or back on. Only items found in the current listing are accepted."""
    item = next((i for i in list_items() if i["id"] == item_id), None)
    if item is None:
        raise KeyError(item_id)
    if item["enabled"] == enable:
        return {"ok": True, "unchanged": True}
    original = {"enabled": item["enabled"], "command": item.get("command")}
    if item["kind"] == "login" and not enable:
        li = next((x for x in _mac_login_items() if x.get("name") == item["name"]), {})
        original.update(path=li.get("path"), hidden=li.get("hidden"))
    if paths.IS_WINDOWS:
        _win_set(item, enable)
    elif paths.IS_MAC:
        _mac_set(item, enable)
    else:
        raise RuntimeError("Chỉ hỗ trợ Windows và macOS")
    if enable:
        _close_change(item_id)
    else:
        _log_change(item, original)
    return {"ok": True}
