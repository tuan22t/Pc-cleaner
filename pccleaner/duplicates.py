"""Exact duplicate finder: same size -> same partial hash -> same full SHA-256."""
from __future__ import annotations

import hashlib
import os
import threading
from collections import defaultdict
from dataclasses import dataclass
from typing import Callable

from . import db, paths

CHUNK = 1024 * 1024
PARTIAL = 64 * 1024


@dataclass
class DupProgress:
    stage: str = "Nhóm theo kích thước"
    done: int = 0
    total: int = 0
    current: str = ""


# Windows cloud placeholders (OneDrive "online-only" files): reading them would
# download them, so they are left out of duplicate checks.
_CLOUD_ATTRS = 0x1000 | 0x40000 | 0x400000  # OFFLINE | RECALL_ON_OPEN | RECALL_ON_DATA_ACCESS


def _is_cloud_placeholder(path: str) -> bool:
    if not paths.IS_WINDOWS:
        return False
    try:
        return bool(getattr(os.stat(path), "st_file_attributes", 0) & _CLOUD_ATTRS)
    except OSError:
        return True


def _partial_hash(path: str, size: int) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        h.update(f.read(PARTIAL))
        if size > 2 * PARTIAL:
            f.seek(size - PARTIAL)
            h.update(f.read(PARTIAL))
    return h.hexdigest()


def _full_hash(path: str, cancel: threading.Event) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(CHUNK):
            if cancel.is_set():
                raise InterruptedError
            h.update(chunk)
    return h.hexdigest()


def _cached(conn, path: str, size: int, mtime: float):
    r = conn.execute("SELECT * FROM hashes WHERE path=?", (path,)).fetchone()
    if r and r["size"] == size and abs(r["mtime"] - mtime) < 1e-3:
        return r
    return None


def _store(conn, path, size, mtime, partial=None, full=None):
    conn.execute(
        """INSERT INTO hashes(path, size, mtime, partial, full) VALUES (?,?,?,?,?)
           ON CONFLICT(path) DO UPDATE SET size=excluded.size, mtime=excluded.mtime,
             partial=COALESCE(excluded.partial, CASE WHEN hashes.size=excluded.size AND hashes.mtime=excluded.mtime THEN hashes.partial END),
             full=COALESCE(excluded.full, CASE WHEN hashes.size=excluded.size AND hashes.mtime=excluded.mtime THEN hashes.full END)""",
        (path, size, mtime, partial, full),
    )


def find_duplicates(
    scan_id: int,
    min_size: int = 1024 * 1024,
    progress: DupProgress | None = None,
    cancel: threading.Event | None = None,
    on_progress: Callable[[DupProgress], None] | None = None,
) -> int:
    """Store duplicate groups for ``scan_id`` and return how many groups were found."""
    progress = progress or DupProgress()
    cancel = cancel or threading.Event()
    conn = db.connect()
    sep = os.sep
    rows = conn.execute(
        """SELECT f.size, f.mtime, rtrim(d.path, ?) || ? || f.name AS path FROM files f
           JOIN dirs d ON d.scan_id=f.scan_id AND d.id=f.dir_id
           WHERE f.scan_id=? AND f.size>=? AND f.size IN (
               SELECT size FROM files WHERE scan_id=? AND size>=? GROUP BY size HAVING COUNT(*)>1)""",
        (sep, sep, scan_id, max(min_size, 1), scan_id, max(min_size, 1)),
    ).fetchall()
    by_size: dict[int, list[tuple[str, float]]] = defaultdict(list)
    for r in rows:
        by_size[r["size"]].append((r["path"], r["mtime"]))

    def tick(path: str):
        progress.done += 1
        progress.current = path
        if on_progress and progress.done % 25 == 0:
            on_progress(progress)

    # Stage 2: partial hash
    progress.stage = "Băm nhanh (đầu + cuối file)"
    progress.total = sum(len(v) for v in by_size.values())
    progress.done = 0
    by_partial: dict[tuple[int, str], list[tuple[str, float]]] = defaultdict(list)
    for size, items in by_size.items():
        for path, mtime in items:
            if cancel.is_set():
                raise InterruptedError
            tick(path)
            c = _cached(conn, path, size, mtime)
            ph = c["partial"] if c and c["partial"] else None
            if ph is None:
                if _is_cloud_placeholder(path):
                    continue
                try:
                    ph = _partial_hash(path, size)
                except OSError:
                    continue
                _store(conn, path, size, mtime, partial=ph)
            by_partial[(size, ph)].append((path, mtime))
    conn.commit()

    # Stage 3: full hash only for files whose partial hash collides
    candidates = {k: v for k, v in by_partial.items() if len(v) > 1}
    progress.stage = "Băm đầy đủ SHA-256"
    progress.total = sum(len(v) for v in candidates.values())
    progress.done = 0
    by_full: dict[tuple[int, str], list[tuple[str, float]]] = defaultdict(list)
    for (size, _), items in candidates.items():
        for path, mtime in items:
            if cancel.is_set():
                raise InterruptedError
            tick(path)
            c = _cached(conn, path, size, mtime)
            fh = c["full"] if c and c["full"] else None
            if fh is None:
                try:
                    fh = _full_hash(path, cancel)
                except OSError:
                    continue
                _store(conn, path, size, mtime, full=fh)
            by_full[(size, fh)].append((path, mtime))
        conn.commit()

    conn.execute("DELETE FROM dup_groups WHERE scan_id=?", (scan_id,))
    groups = [(k, v) for k, v in by_full.items() if len(v) > 1]
    groups.sort(key=lambda kv: kv[0][0] * (len(kv[1]) - 1), reverse=True)
    for gid, ((size, fh), items) in enumerate(groups):
        conn.executemany(
            "INSERT INTO dup_groups(scan_id, group_id, hash, size, path, mtime) VALUES (?,?,?,?,?,?)",
            [(scan_id, gid, fh, size, p, m) for p, m in items],
        )
    conn.commit()
    progress.stage = "Xong"
    if on_progress:
        on_progress(progress)
    return len(groups)


def get_groups(scan_id: int, limit: int = 500) -> dict:
    conn = db.connect()
    rows = conn.execute(
        "SELECT * FROM dup_groups WHERE scan_id=? AND group_id<? ORDER BY group_id, mtime", (scan_id, limit)
    ).fetchall()
    groups: dict[int, dict] = {}
    for r in rows:
        g = groups.setdefault(r["group_id"], {"id": r["group_id"], "hash": r["hash"], "size": r["size"], "files": []})
        g["files"].append({
            "path": r["path"], "mtime": r["mtime"], "protected": paths.is_protected(r["path"]),
            "exists": os.path.exists(r["path"]),
        })
    out = list(groups.values())
    for g in out:
        # Suggest keeping the oldest copy that is not protected-only; mark the rest.
        g["files"].sort(key=lambda f: (f["mtime"], len(f["path"])))
        g["wasted"] = g["size"] * (len(g["files"]) - 1)
    total = conn.execute(
        "SELECT COUNT(DISTINCT group_id) AS n, COALESCE(SUM(size),0) AS s FROM dup_groups WHERE scan_id=?", (scan_id,)
    ).fetchone()
    per_group = conn.execute(
        "SELECT COALESCE(SUM(size * (c - 1)),0) AS w FROM (SELECT size, COUNT(*) AS c FROM dup_groups WHERE scan_id=? GROUP BY group_id)",
        (scan_id,),
    ).fetchone()
    return {"groups": out, "group_count": total["n"], "wasted": per_group["w"]}


def check_removal(scan_id: int, to_remove: list[str]) -> tuple[list[str], list[dict]]:
    """Re-check duplicates right before they are moved.

    A file is allowed only if its content still matches its group right now,
    and at least one copy with that same content stays on disk. If every copy
    of a group was selected, the first one is kept back.
    Returns (allowed paths, refused [{path, error}]).
    """
    conn = db.connect()
    never = threading.Event()
    removing = {os.path.normcase(os.path.abspath(p)) for p in to_remove}

    def matches(path: str, expected: str) -> bool:
        try:
            return os.path.isfile(path) and _full_hash(path, never) == expected
        except OSError:
            return False

    allowed: list[str] = []
    refused: list[dict] = []
    by_group: dict[int, list[str]] = defaultdict(list)
    hashes: dict[int, str] = {}
    for path in to_remove:
        row = conn.execute(
            "SELECT group_id, hash FROM dup_groups WHERE scan_id=? AND path=?", (scan_id, path)
        ).fetchone()
        if row is None:
            refused.append({"path": path, "error": "Không thuộc nhóm file trùng nào"})
            continue
        by_group[row["group_id"]].append(path)
        hashes[row["group_id"]] = row["hash"]

    for gid, selected in by_group.items():
        expected = hashes[gid]
        keeper = None
        for m in conn.execute("SELECT path FROM dup_groups WHERE scan_id=? AND group_id=?", (scan_id, gid)):
            other = m["path"]
            if os.path.normcase(os.path.abspath(other)) not in removing and matches(other, expected):
                keeper = other
                break
        candidates = list(selected)
        if keeper is None:
            # Every remaining copy was selected: keep the first one that still matches.
            for p in candidates:
                if matches(p, expected):
                    keeper = p
                    break
            if keeper is None:
                refused += [{"path": p, "error": "Không còn bản nào giống hệt để giữ lại"} for p in candidates]
                continue
            candidates.remove(keeper)
            refused.append({"path": keeper, "error": "Giữ lại bản cuối cùng của nhóm"})
        for p in candidates:
            if matches(p, expected):
                allowed.append(p)
            else:
                refused.append({"path": p, "error": "Nội dung file đã thay đổi từ lần quét trước"})
    return allowed, refused
