"""macOS: Login Items, LaunchAgents/LaunchDaemons, system junk.

Imported only on macOS.
"""
from __future__ import annotations

import json
import os
import plistlib
import re
import shlex
from pathlib import Path

from .. import db
from ..junk_base import Category, register_source
from ..startup_base import Provider, _change, classify, register_provider
from .common import _run
from ..i18n import _

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


_SAFE_LABEL = re.compile(r"^[A-Za-z0-9._@+-]{1,200}$")
_SAFE_DOMAIN = re.compile(r"^gui/\d+$")


def _osascript_admin(shell: str) -> None:
    esc = shell.replace("\\", "\\\\").replace('"', '\\"')
    r = _run(["osascript", "-e", f'do shell script "{esc}" with administrator privileges'], timeout=300)
    if r.returncode != 0:
        if "-128" in r.stderr:
            raise PermissionError(_("Anh/chị đã hủy nhập mật khẩu quản trị, nên chưa thay đổi gì."))
        raise RuntimeError(r.stderr.strip()[:300])


def _mac_set(item: dict, enable: bool) -> None:
    kind = item["kind"]
    if kind == "login":
        name = item["id"].split("|", 1)[1]
        if enable:
            orig = _change(item["id"]) or {}
            path = orig.get("path") or item.get("command")
            if not path:
                raise RuntimeError(_("Không còn biết đường dẫn của mục này"))
            js = (f"Application('System Events').loginItems.push(Application('System Events').LoginItem("
                  f"{{path: {json.dumps(path)}, hidden: {json.dumps(bool(orig.get('hidden')))}}}))")
        else:
            js = (f"var se=Application('System Events'); var it=se.loginItems.byName({json.dumps(name)});"
                  "it.delete()")
        r = _run(["osascript", "-l", "JavaScript", "-e", js], timeout=30)
        if r.returncode != 0:
            raise RuntimeError(r.stderr.strip()[:300] or _("osascript lỗi"))
        return
    _k, domain, label, plist = item["id"].split("|", 3)
    if not _SAFE_LABEL.match(label) or not (domain == "system" or _SAFE_DOMAIN.match(domain)):
        raise ValueError(_("Tên mục khởi động có ký tự lạ, ứng dụng không thay đổi mục này"))
    target = f"{domain}/{label}"
    if domain == "system":
        # Runs as root: every value is quoted, never pasted into the command as-is.
        t, pl = shlex.quote(target), shlex.quote(plist)
        if enable:
            _osascript_admin(f"/bin/launchctl enable {t}; /bin/launchctl bootstrap system {pl} || true")
        else:
            _osascript_admin(f"/bin/launchctl disable {t}; /bin/launchctl bootout {t} || true")
        return
    r = _run(["launchctl", "enable" if enable else "disable", target])
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip()[:300] or _("launchctl lỗi"))
    if enable:
        _run(["launchctl", "bootstrap", domain, plist])  # may already be loaded; that's fine
    else:
        _run(["launchctl", "bootout", target])  # stop it now; fine if it wasn't running


register_provider(Provider("macos", {"login", "agent", "daemon"}, _mac_items, _mac_set))


# Caches that belong to macOS itself or to sync services. Moving them while the
# system or the sync client runs can cause errors or a full re-sync, so they are
# never offered, even though they are "only" caches.
_MAC_KEEP_PREFIXES = ("com.apple.", "cloudkit", "familycircle", "geoservices", "com.microsoft.onedrive",
                      "com.getdropbox.", "com.dropbox.", "com.google.drivefs", "com.box.")


def _mac_keep_cache(name: str) -> bool:
    low = name.lower()
    return low.startswith(_MAC_KEEP_PREFIXES) or "icloud" in low


@register_source
def junk_categories() -> list[Category]:
    home = str(Path.home())
    cats: list[Category] = []
    lib = os.path.join(home, "Library")
    cats += [
        Category("mac_caches", "Bộ nhớ đệm ứng dụng", "~/Library/Caches của các ứng dụng bên thứ ba: dữ liệu tạm ứng dụng tự tạo lại. Không đụng bộ nhớ đệm của macOS và của ứng dụng đồng bộ (iCloud, OneDrive, Dropbox…).", [os.path.join(lib, "Caches", "*")], skip_root=_mac_keep_cache),
        Category("mac_logs", "Nhật ký ứng dụng", "~/Library/Logs: file ghi hoạt động của ứng dụng.", [os.path.join(lib, "Logs")], min_age_hours=24),
        Category("mac_crash", "Báo cáo lỗi", "Báo cáo khi ứng dụng bị treo hoặc thoát đột ngột.", [os.path.join(lib, "Logs", "DiagnosticReports"), os.path.join(lib, "Application Support", "CrashReporter")], min_age_hours=0),
        Category("mac_xcode", "Dữ liệu tạm của Xcode", "DerivedData và bản lưu trữ thiết bị cũ của lập trình viên.", [os.path.join(lib, "Developer", "Xcode", "DerivedData"), os.path.join(lib, "Developer", "Xcode", "iOS DeviceSupport")], label="caution", min_age_hours=24),
    ]
    return cats
