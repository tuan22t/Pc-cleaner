"""Safe removal: files are moved into a quarantine folder, logged, and can be restored.

Nothing is ever deleted outright. ``purge_older_than`` empties quarantine batches
after a grace period, and only when the user asks for it.

Crash safety (power cut, killed process): every move is written to the log
*before* the file moves, as a ``pending-…`` row, and that row is on disk
(SQLite synchronous=FULL) before anything touches the file. After the move the
row becomes ``quarantine`` / ``move``. If the app stops in between,
``recover()`` (run at every start) looks at the disk and settles each pending
row: moved files become restorable, untouched files are left alone.

Moves never cross drives: each drive has its own quarantine folder, and
``os.rename`` is used, which is atomic and refuses to copy between drives.
"""
from __future__ import annotations

import os
import time
import uuid
from pathlib import Path

from . import db, paths


class ProtectedPathError(PermissionError):
    pass


class Progress:
    """Shared with the UI while a long action runs (see server.JobManager)."""

    def __init__(self, stage: str = ""):
        self.stage, self.done, self.total, self.current = stage, 0, 0, ""


def _tick(progress, on_progress, path: str = "") -> None:
    if progress is not None:
        progress.done += 1
        progress.current = path
        if on_progress and (progress.done % 25 == 0 or progress.done == progress.total):
            on_progress(progress)


# Number of files whose log rows are written in one transaction. Smaller is
# not safer (each row is on disk before its file moves); larger is faster.
CHUNK = 200

# Test hook: called with a point name ("before_move", "after_move", …).
# Fault-injection tests replace it to kill the process at that exact point.
_fault = None


def _hit(point: str) -> None:
    if _fault is not None:
        _fault(point)


def _log(conn, batch_id, kind, path, stored_at=None, size=0, reason=None) -> int:
    cur = conn.execute(
        "INSERT INTO actions(batch_id, ts, kind, path, stored_at, size, reason) VALUES (?,?,?,?,?,?,?)",
        (batch_id, time.time(), kind, path, stored_at, size, reason),
    )
    return cur.lastrowid


def _inside(path: str, roots: list[str]) -> bool:
    """True if ``path`` (as given and fully resolved) lies inside one of ``roots``."""
    cands = {os.path.normcase(os.path.abspath(path)), os.path.normcase(os.path.realpath(path))}
    for root in roots:
        r = os.path.normcase(os.path.realpath(root)).rstrip("\\/")
        if all(c.startswith(r + os.sep) for c in cands):
            return True
    return False


def _new_batch() -> str:
    return time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]


def _rename(src: str, dst: str) -> None:
    """Atomic move on one drive. Raises instead of copying across drives."""
    os.rename(paths.lp(src), paths.lp(dst))


def _run_chunks(conn, jobs: list[dict], pending_kind: str, done_kind: str,
                cancel=None, progress=None, on_progress=None) -> tuple[list[dict], list[dict]]:
    """Journal, then move, a list of {src, dst, size, reason, batch, mkdirs}.

    Stops cleanly when ``cancel`` is set: files already moved stay logged and
    restorable, the rest are left untouched. Returns (done, failed).
    """
    done, failed = [], []
    if progress is not None:
        progress.total = len(jobs)
    for start in range(0, len(jobs), CHUNK):
        if cancel is not None and cancel.is_set():
            break
        chunk = jobs[start : start + CHUNK]
        for j in chunk:
            for d in j.get("mkdirs", []):
                _log(conn, j["batch"], "mkdir", d, None, 0, j["reason"])
            j["row"] = _log(conn, j["batch"], pending_kind, j["src"], j["dst"], j["size"], j["reason"])
        conn.commit()  # on disk before any file in this chunk moves
        _hit("after_journal")
        for j in chunk:
            if cancel is not None and cancel.is_set():
                conn.execute("UPDATE actions SET kind='aborted', reason=? WHERE id=?",
                             (f"{j['reason']}: đã dừng theo yêu cầu, file vẫn ở chỗ cũ", j["row"]))
                continue
            _tick(progress, on_progress, j["src"])
            try:
                _hit("before_move")
                os.makedirs(paths.lp(os.path.dirname(j["dst"])), exist_ok=True)
                if os.path.exists(paths.lp(j["dst"])):
                    raise FileExistsError("Đã có file cùng tên ở nơi đến")
                _rename(j["src"], j["dst"])
                _hit("after_move")
                j["ok"] = True
                done.append(j)
            except Exception as e:  # noqa: BLE001 - every failure is reported to the user
                conn.execute(
                    "UPDATE actions SET kind='error', stored_at=NULL, size=0, reason=? WHERE id=?",
                    (f"{j['reason']}: {_friendly(e)}", j["row"]),
                )
                failed.append({"path": j["src"], "error": _friendly(e)})
        ids = [j["row"] for j in chunk if j.get("ok")]
        conn.executemany(f"UPDATE actions SET kind='{done_kind}' WHERE id=?", [(i,) for i in ids])
        conn.commit()
        _hit("after_commit")
    return done, failed


def _free_name(path: str) -> str:
    """``a.txt`` -> ``a (khôi phục).txt``, ``a (khôi phục 2).txt``… the first name not in use."""
    stem, ext = os.path.splitext(path)
    for n in range(1, 1000):
        cand = f"{stem} (khôi phục{'' if n == 1 else ' ' + str(n)}){ext}"
        if not os.path.exists(paths.lp(cand)):
            return cand
    raise FileExistsError("Đã có file khác ở vị trí cũ")


def _friendly(e: Exception) -> str:
    import errno

    if isinstance(e, OSError) and e.errno == errno.EXDEV:
        return "Không di chuyển được giữa hai ổ đĩa khác nhau"
    if isinstance(e, PermissionError) and not isinstance(e, ProtectedPathError):
        return "Không có quyền hoặc file đang được chương trình khác sử dụng"
    return str(e)


def quarantine(
    file_paths: list[str],
    reason: str = "",
    refused: list[dict] | None = None,
    allow_roots: list[str] | None = None,
    log_failures: bool = True,
    allow_cloud: bool = True,
    cancel=None,
    progress: Progress | None = None,
    on_progress=None,
) -> dict:
    """Move files into quarantine. Returns a summary with the batch id for undo.

    ``refused`` lists files a caller already decided not to move; they are
    logged and reported alongside any failures here.

    ``allow_roots`` is used only by the system-junk cleaner: files inside these
    known junk folders (e.g. %TEMP%, ~/Library/Caches) may be moved even though
    the folder sits inside a protected area. The check uses the resolved path,
    so a link cannot be used to escape the junk folder.

    ``allow_cloud=False`` refuses files in OneDrive/Dropbox/iCloud folders
    (removing them there removes them on every device).
    """
    conn = db.connect()
    batch_id = _new_batch()
    failed: list[dict] = []
    for item in refused or []:
        _log(conn, batch_id, "error", item["path"], None, 0, f"{reason}: {item['error']}")
        failed.append(item)
    jobs = []
    for i, src in enumerate(file_paths):
        src = os.path.abspath(src)
        try:
            if allow_roots is not None:
                if not _inside(src, allow_roots):
                    raise ProtectedPathError("Nằm ngoài thư mục rác được phép dọn")
            else:
                why = paths.protection_reason(src)
                if why:
                    raise ProtectedPathError(why)
                if not allow_cloud:
                    cloud = paths.cloud_name(src)
                    if cloud:
                        raise ProtectedPathError(f"Nằm trong thư mục {cloud}: cần anh/chị xác nhận riêng")
            if not os.path.isfile(paths.lp(src)) or os.path.islink(paths.lp(src)):
                raise FileNotFoundError("Không phải file thường hoặc không còn tồn tại")
            dst = str(paths.quarantine_dir_for(src) / batch_id / str(i) / os.path.basename(src))
            jobs.append({"src": src, "dst": dst, "size": os.path.getsize(paths.lp(src)), "reason": reason, "batch": batch_id})
        except Exception as e:  # noqa: BLE001
            if log_failures:
                _log(conn, batch_id, "error", src, None, 0, f"{reason}: {_friendly(e)}")
            failed.append({"path": src, "error": _friendly(e)})
    conn.commit()
    done, move_failed = _run_chunks(conn, jobs, "pending-quarantine", "quarantine", cancel, progress, on_progress)
    if not log_failures:
        # Junk cleaning: locked or in-use files are skipped quietly, not logged as errors.
        conn.execute("DELETE FROM actions WHERE batch_id=? AND kind='error'", (batch_id,))
        conn.commit()
    return {
        "batch_id": batch_id,
        "moved": len(done),
        "bytes": sum(j["size"] for j in done),
        "failed": failed + move_failed,
        "cancelled": bool(cancel is not None and cancel.is_set()),
    }


def move_files(moves: list[tuple[str, str]], reason: str = "", cancel=None,
               progress: Progress | None = None, on_progress=None) -> dict:
    """Move files to new places inside the user's folders (folder reorganizer).

    Logged like a quarantine batch, so ``restore`` moves everything back.
    Never overwrites: an existing destination is refused.
    """
    conn = db.connect()
    batch_id = _new_batch()
    failed: list[dict] = []
    jobs = []
    planned_dirs: set[str] = set()
    for src, dst in moves:
        src, dst = os.path.abspath(src), os.path.abspath(dst)
        try:
            why = paths.protection_reason(src) or paths.protection_reason(dst)
            if why:
                raise ProtectedPathError(why)
            if not os.path.isfile(paths.lp(src)) or os.path.islink(paths.lp(src)):
                raise FileNotFoundError("Không phải file thường hoặc không còn tồn tại")
            if os.path.exists(paths.lp(dst)):
                raise FileExistsError("Đã có file cùng tên ở nơi đến")
            missing, d = [], os.path.dirname(dst)
            while not os.path.exists(paths.lp(d)) and os.path.normcase(d) not in planned_dirs:
                missing.append(d)
                d = os.path.dirname(d)
            planned_dirs.update(os.path.normcase(m) for m in missing)
            # Logged before they are created, so undo can remove them again.
            jobs.append({"src": src, "dst": dst, "size": os.path.getsize(paths.lp(src)), "reason": reason,
                         "batch": batch_id, "mkdirs": list(reversed(missing))})
        except Exception as e:  # noqa: BLE001
            _log(conn, batch_id, "error", src, None, 0, f"{reason}: {_friendly(e)}")
            failed.append({"path": src, "error": _friendly(e)})
    conn.commit()
    done, move_failed = _run_chunks(conn, jobs, "pending-move", "move", cancel, progress, on_progress)
    return {
        "batch_id": batch_id,
        "moved": len(done),
        "bytes": sum(j["size"] for j in done),
        "failed": failed + move_failed,
        "cancelled": bool(cancel is not None and cancel.is_set()),
    }


def restore(batch_id: str, cancel=None, progress: Progress | None = None, on_progress=None) -> dict:
    """Undo a quarantine batch: put every file back where it was.

    Safe to stop at any point: a file already back in place is recognised the
    next time (see below), so Undo can simply be pressed again.
    """
    conn = db.connect()
    rows = conn.execute(
        "SELECT * FROM actions WHERE batch_id=? AND kind IN ('quarantine','move') AND restored=0 ORDER BY id DESC",
        (batch_id,),
    ).fetchall()
    ok, failed, renamed = 0, [], []
    if progress is not None:
        progress.total = len(rows)
    for n, r in enumerate(rows):
        if cancel is not None and cancel.is_set():
            break
        _tick(progress, on_progress, r["path"])
        if n % CHUNK == 0:
            conn.commit()
        try:
            target = r["path"]
            if os.path.exists(paths.lp(target)):
                if r["stored_at"] and not os.path.exists(paths.lp(r["stored_at"])):
                    # Already back in place (an earlier undo stopped before saving that).
                    conn.execute("UPDATE actions SET restored=1 WHERE id=?", (r["id"],))
                    ok += 1
                    continue
                # A new file now has this name: never overwrite it, put ours beside it.
                target = _free_name(target)
            if not r["stored_at"] or not os.path.exists(paths.lp(r["stored_at"])):
                raise FileNotFoundError("Không còn bản lưu trong khu cách ly (ổ đĩa đã bị rút ra hoặc bị xóa?)")
            os.makedirs(paths.lp(os.path.dirname(target)), exist_ok=True)
            _rename(r["stored_at"], target)
            _hit("restore_after_move")
            conn.execute("UPDATE actions SET restored=1 WHERE id=?", (r["id"],))
            _log(conn, batch_id, "restore", target, r["stored_at"], r["size"],
                 None if target == r["path"] else f"Đã có file mới cùng tên, bản cũ được đặt tên {os.path.basename(target)}")
            if target != r["path"]:
                renamed.append({"path": r["path"], "restored_as": target})
            ok += 1
        except Exception as e:  # noqa: BLE001
            failed.append({"path": r["path"], "error": _friendly(e)})
    # Remove folders the organizer created, deepest first, if they are empty again.
    for r in conn.execute("SELECT path FROM actions WHERE batch_id=? AND kind='mkdir' ORDER BY id DESC", (batch_id,)):
        try:
            os.rmdir(paths.lp(r["path"]))
        except OSError:
            pass
    conn.commit()
    _cleanup_batch_dirs(conn, batch_id)
    return {"restored": ok, "failed": failed, "renamed": renamed,
            "cancelled": bool(cancel is not None and cancel.is_set())}


def batches() -> list[dict]:
    rows = db.connect().execute(
        """SELECT batch_id, MIN(ts) AS ts, MAX(reason) AS reason,
                  SUM(CASE WHEN kind IN ('quarantine','move') THEN 1 ELSE 0 END) AS files,
                  SUM(CASE WHEN kind IN ('quarantine','move') THEN size ELSE 0 END) AS bytes,
                  SUM(CASE WHEN kind IN ('quarantine','move') AND restored=0 THEN 1 ELSE 0 END) AS pending,
                  SUM(CASE WHEN kind='move' THEN 1 ELSE 0 END) AS moves,
                  SUM(CASE WHEN kind='purge' THEN 1 ELSE 0 END) AS purged
           FROM actions GROUP BY batch_id ORDER BY ts DESC LIMIT 200"""
    ).fetchall()
    return [dict(r) for r in rows]


def log(limit: int = 500) -> list[dict]:
    rows = db.connect().execute(
        "SELECT * FROM actions WHERE kind NOT IN ('mkdir','pending-quarantine','pending-move') ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def purge_batch(batch_id: str, cancel=None, progress: Progress | None = None, on_progress=None) -> dict:
    """Permanently delete the quarantined copies of one batch (explicit user action)."""
    conn = db.connect()
    rows = conn.execute(
        "SELECT * FROM actions WHERE batch_id=? AND kind='quarantine' AND restored=0", (batch_id,)
    ).fetchall()
    freed = 0
    if progress is not None:
        progress.total = len(rows)
    for n, r in enumerate(rows):
        if cancel is not None and cancel.is_set():
            break
        _tick(progress, on_progress, r["path"])
        if n % CHUNK == 0:
            conn.commit()
        try:
            if r["stored_at"] and os.path.exists(paths.lp(r["stored_at"])):
                if not _is_quarantine_copy(r["stored_at"]):
                    raise ProtectedPathError("Bản lưu không nằm trong khu cách ly")
                os.remove(paths.lp(r["stored_at"]))
                _hit("purge_after_remove")
                freed += r["size"]
            conn.execute("UPDATE actions SET restored=2 WHERE id=?", (r["id"],))
            _log(conn, batch_id, "purge", r["path"], r["stored_at"], r["size"])
        except OSError as e:
            _log(conn, batch_id, "error", r["path"], r["stored_at"], 0, f"purge: {e}")
    conn.commit()
    _cleanup_batch_dirs(conn, batch_id)
    return {"freed": freed}


def purge_older_than(days: int) -> dict:
    """Permanently delete quarantine batches older than ``days`` (used by scheduled cleanup)."""
    cutoff = time.time() - days * 86400
    rows = db.connect().execute(
        """SELECT batch_id FROM actions WHERE kind='quarantine' AND restored=0
           GROUP BY batch_id HAVING MAX(ts) < ?""",
        (cutoff,),
    ).fetchall()
    freed = 0
    for r in rows:
        freed += purge_batch(r["batch_id"])["freed"]
    return {"batches": len(rows), "freed": freed}


def pending_bytes() -> int:
    r = db.connect().execute(
        "SELECT COALESCE(SUM(size),0) AS s FROM actions WHERE kind='quarantine' AND restored=0"
    ).fetchone()
    return r["s"]


def recover() -> dict:
    """Settle moves that were cut off by a crash or power cut. Run at every start.

    For each pending row, the disk tells what happened:
      * file at the destination, not at the source → the move finished: keep it (restorable)
      * file at the source, not at the destination → the move never happened: mark aborted
      * file at both → keep the source (the original), mark aborted
      * file at neither → report it; nothing to do
    Only the pending rows themselves are changed; no file is deleted.
    """
    conn = db.connect()
    rows = conn.execute(
        "SELECT * FROM actions WHERE kind IN ('pending-quarantine','pending-move') ORDER BY id"
    ).fetchall()
    finished = aborted = missing = 0
    for r in rows:
        src_ok = os.path.exists(paths.lp(r["path"]))
        dst_ok = bool(r["stored_at"]) and os.path.exists(paths.lp(r["stored_at"]))
        done_kind = "quarantine" if r["kind"] == "pending-quarantine" else "move"
        if dst_ok and not src_ok:
            conn.execute("UPDATE actions SET kind=? WHERE id=?", (done_kind, r["id"]))
            finished += 1
        elif src_ok:
            conn.execute(
                "UPDATE actions SET kind='aborted', reason=? WHERE id=?",
                ((r["reason"] or "") + " (bị dừng giữa chừng, file vẫn ở chỗ cũ)", r["id"]),
            )
            aborted += 1
        else:
            conn.execute(
                "UPDATE actions SET kind='error', reason=? WHERE id=?",
                ((r["reason"] or "") + ": không thấy file ở chỗ cũ lẫn trong khu cách ly", r["id"]),
            )
            missing += 1
    conn.commit()
    return {"finished": finished, "aborted": aborted, "missing": missing}


def _is_quarantine_copy(stored_at: str) -> bool:
    p = os.path.normcase(os.path.abspath(stored_at))
    roots = [os.path.normcase(str(paths.quarantine_dir()))]
    parts = p.replace("\\", "/").split("/")
    return any(p.startswith(r + os.sep) for r in roots) or paths.VOLUME_QUARANTINE.lower() in (x.lower() for x in parts)


def _cleanup_batch_dirs(conn, batch_id: str) -> None:
    """Remove the batch's now-empty folders in every quarantine it used."""
    dirs = {str(paths.quarantine_dir() / batch_id)}
    for r in conn.execute(
        "SELECT DISTINCT stored_at FROM actions WHERE batch_id=? AND kind IN ('quarantine','restore','purge')", (batch_id,)
    ):
        if r["stored_at"]:
            # stored_at = <quarantine>/<batch>/<i>/<name>
            dirs.add(str(Path(r["stored_at"]).parent.parent))
    for d in dirs:
        if Path(d).name == batch_id:
            _cleanup_empty(d)


def _cleanup_empty(folder) -> None:
    if not os.path.isdir(folder):
        return
    for dirpath, _dirs, _files in sorted(os.walk(folder), key=lambda t: -len(t[0])):
        try:
            os.rmdir(dirpath)
        except OSError:
            pass
