"""Shared parts of the startup-programs feature: labels, change records and the
provider registry. Platform code lives in ``pccleaner.platforms``.

A *provider* lists one family of startup items and turns them on or off.
Providers are registered with ``register_provider``; adding a new family
(another OS, another app's auto-start list) needs no change to the core.
"""
from __future__ import annotations

import json
import time
from typing import Callable

from . import db

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


def _discard_change(item_id: str) -> None:
    """Drop a change record written for a change that then failed."""
    conn = db.connect()
    conn.execute(
        "DELETE FROM startup_changes WHERE id=(SELECT MAX(id) FROM startup_changes WHERE item_id=? AND active=1)",
        (item_id,),
    )
    conn.commit()


class Provider:
    """One family of startup items. ``kinds`` are the item kinds it owns."""

    def __init__(self, name: str, kinds: set[str], list_items: Callable[[], list[dict]],
                 set_enabled: Callable[[dict, bool], None]):
        self.name, self.kinds, self.list_items, self.set_enabled = name, kinds, list_items, set_enabled


PROVIDERS: list[Provider] = []


def register_provider(p: Provider) -> None:
    PROVIDERS[:] = [x for x in PROVIDERS if x.name != p.name] + [p]
