"""Safe removal: files are moved into a quarantine folder, logged, and can be restored.

Nothing is ever deleted outright. ``purge_older_than`` empties quarantine batches
after a grace period, and only when the user asks for it.
"""
from __future__ import annotations

import os
import shutil
import time
import uuid

from . import db, paths


class ProtectedPathError(PermissionError):
    pass


def _log(conn, batch_id, kind, path, stored_at=None, size=0, reason=None):
    conn.execute(
        "INSERT INTO actions(batch_id, ts, kind, path, stored_at, size, reason) VALUES (?,?,?,?,?,?,?)",
        (batch_id, time.time(), kind, path, stored_at, size, reason),
    )


def quarantine(file_paths: list[str], reason: str = "") -> dict:
    """Move files into quarantine. Returns a summary with the batch id for undo."""
    conn = db.connect()
    batch_id = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
    dest_root = paths.quarantine_dir() / batch_id
    moved, failed, total = [], [], 0
    for i, src in enumerate(file_paths):
        src = os.path.abspath(src)
        try:
            if paths.is_protected(src):
                raise ProtectedPathError("Thư mục hệ thống/chương trình được bảo vệ")
            if not os.path.isfile(src) or os.path.islink(src):
                raise FileNotFoundError("Không phải file thường hoặc không còn tồn tại")
            size = os.path.getsize(src)
            dest_dir = dest_root / str(i)
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / os.path.basename(src)
            shutil.move(src, dest)
            _log(conn, batch_id, "quarantine", src, str(dest), size, reason)
            moved.append(src)
            total += size
        except Exception as e:  # noqa: BLE001 - every failure is reported to the user
            _log(conn, batch_id, "error", src, None, 0, f"{reason}: {e}")
            failed.append({"path": src, "error": str(e)})
    conn.commit()
    return {"batch_id": batch_id, "moved": len(moved), "bytes": total, "failed": failed}


def restore(batch_id: str) -> dict:
    """Undo a quarantine batch: put every file back where it was."""
    conn = db.connect()
    rows = conn.execute(
        "SELECT * FROM actions WHERE batch_id=? AND kind='quarantine' AND restored=0", (batch_id,)
    ).fetchall()
    ok, failed = 0, []
    for r in rows:
        try:
            if os.path.exists(r["path"]):
                raise FileExistsError("Đã có file khác ở vị trí cũ")
            os.makedirs(os.path.dirname(r["path"]), exist_ok=True)
            shutil.move(r["stored_at"], r["path"])
            conn.execute("UPDATE actions SET restored=1 WHERE id=?", (r["id"],))
            _log(conn, batch_id, "restore", r["path"], r["stored_at"], r["size"])
            ok += 1
        except Exception as e:  # noqa: BLE001
            failed.append({"path": r["path"], "error": str(e)})
    conn.commit()
    _cleanup_empty(paths.quarantine_dir() / batch_id)
    return {"restored": ok, "failed": failed}


def batches() -> list[dict]:
    rows = db.connect().execute(
        """SELECT batch_id, MIN(ts) AS ts, MAX(reason) AS reason,
                  SUM(CASE WHEN kind='quarantine' THEN 1 ELSE 0 END) AS files,
                  SUM(CASE WHEN kind='quarantine' THEN size ELSE 0 END) AS bytes,
                  SUM(CASE WHEN kind='quarantine' AND restored=0 THEN 1 ELSE 0 END) AS pending,
                  SUM(CASE WHEN kind='purge' THEN 1 ELSE 0 END) AS purged
           FROM actions GROUP BY batch_id ORDER BY ts DESC LIMIT 200"""
    ).fetchall()
    return [dict(r) for r in rows]


def log(limit: int = 500) -> list[dict]:
    rows = db.connect().execute("SELECT * FROM actions ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def purge_batch(batch_id: str) -> dict:
    """Permanently delete the quarantined copies of one batch (explicit user action)."""
    conn = db.connect()
    rows = conn.execute(
        "SELECT * FROM actions WHERE batch_id=? AND kind='quarantine' AND restored=0", (batch_id,)
    ).fetchall()
    freed = 0
    for r in rows:
        try:
            if r["stored_at"] and os.path.exists(r["stored_at"]):
                os.remove(r["stored_at"])
            freed += r["size"]
            conn.execute("UPDATE actions SET restored=2 WHERE id=?", (r["id"],))
            _log(conn, batch_id, "purge", r["path"], r["stored_at"], r["size"])
        except OSError as e:
            _log(conn, batch_id, "error", r["path"], r["stored_at"], 0, f"purge: {e}")
    conn.commit()
    _cleanup_empty(paths.quarantine_dir() / batch_id)
    return {"freed": freed}


def _cleanup_empty(folder) -> None:
    if not os.path.isdir(folder):
        return
    for dirpath, _dirs, _files in sorted(os.walk(folder), key=lambda t: -len(t[0])):
        try:
            os.rmdir(dirpath)
        except OSError:
            pass
