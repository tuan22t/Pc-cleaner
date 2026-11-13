"""Figures for the Dashboard: disks, what can be cleaned, startup items, last cleanup.

Everything here is read-only and cheap. Results of slow checks (system junk,
startup items) come from the last time the user ran them, with their date, so
opening the Dashboard never starts a scan by itself.
"""
from __future__ import annotations

import json
import time

from . import db, paths, quarantine

HISTORY_DAYS = 400


def record_disks(locations: list[dict] | None = None) -> None:
    """Remember today's used space of each drive (one reading per drive per day)."""
    locations = paths.list_locations() if locations is None else locations
    now = time.time()
    day = time.strftime("%Y-%m-%d", time.localtime(now))
    conn = db.connect()
    conn.executemany(
        "INSERT INTO disk_history(path, day, ts, total, used) VALUES (?,?,?,?,?) "
        "ON CONFLICT(path, day) DO UPDATE SET ts=excluded.ts, total=excluded.total, used=excluded.used",
        [(l["path"], day, now, l["total"], l["used"]) for l in locations if l.get("total")],
    )
    cutoff = time.strftime("%Y-%m-%d", time.localtime(now - HISTORY_DAYS * 86400))
    conn.execute("DELETE FROM disk_history WHERE day < ?", (cutoff,))
    conn.commit()


def history(days: int = 90) -> dict[str, list]:
    cutoff = time.strftime("%Y-%m-%d", time.localtime(time.time() - days * 86400))
    out: dict[str, list] = {}
    for r in db.connect().execute(
        "SELECT path, day, total, used FROM disk_history WHERE day >= ? ORDER BY day", (cutoff,)
    ):
        out.setdefault(r["path"], []).append({"day": r["day"], "total": r["total"], "used": r["used"]})
    return out


def remember(key: str, value: dict) -> None:
    db.set_setting(key, json.dumps({"ts": time.time(), **value}))


def _recall(key: str) -> dict | None:
    raw = db.get_setting(key)
    try:
        return json.loads(raw) if raw else None
    except ValueError:
        return None


def duplicate_waste() -> dict | None:
    """Space taken by the extra copies found by the last duplicate search."""
    conn = db.connect()
    r = conn.execute(
        "SELECT g.scan_id AS sid, s.root AS root, s.finished AS ts FROM dup_groups g JOIN scans s ON s.id=g.scan_id "
        "ORDER BY g.scan_id DESC LIMIT 1"
    ).fetchone()
    if r is None:
        return None
    w = conn.execute(
        "SELECT COALESCE(SUM(size * (n - 1)), 0) AS bytes, COALESCE(SUM(n - 1), 0) AS files FROM "
        "(SELECT MAX(size) AS size, COUNT(*) AS n FROM dup_groups WHERE scan_id=? GROUP BY group_id)",
        (r["sid"],),
    ).fetchone()
    return {"bytes": w["bytes"], "files": w["files"], "scan_id": r["sid"], "root": r["root"], "ts": r["ts"]}


def last_cleanup() -> dict | None:
    r = db.connect().execute(
        """SELECT batch_id, MIN(ts) AS ts, MAX(reason) AS reason, COUNT(*) AS files, SUM(size) AS bytes
           FROM actions WHERE batch_id IN (SELECT batch_id FROM actions WHERE kind='quarantine' ORDER BY id DESC LIMIT 1)
             AND kind='quarantine' GROUP BY batch_id"""
    ).fetchone()
    return dict(r) if r else None


def summary() -> dict:
    locations = paths.list_locations()
    try:
        record_disks(locations)
    except Exception:  # noqa: BLE001 - the history is a nice-to-have, never block the Dashboard
        pass
    junk = _recall("last_junk")
    cleanable = []
    if junk:
        cleanable.append({"group": "junk", "bytes": junk.get("bytes", 0), "files": junk.get("files", 0), "ts": junk["ts"]})
    dup = duplicate_waste()
    if dup:
        cleanable.append({"group": "dups", "bytes": dup["bytes"], "files": dup["files"], "ts": dup["ts"], "root": dup["root"]})
    pending = quarantine.pending_bytes()
    cleanable.append({"group": "quarantine", "bytes": pending})
    sched = _recall("schedule_last_run")
    return {
        "locations": locations,
        "cleanable": cleanable,
        "startup": _recall("last_startup"),
        "last_cleanup": last_cleanup(),
        "last_auto": sched,
        "history": history(),
    }
