"""Disk scanner: walks a folder once and stores every file and folder size in SQLite."""
from __future__ import annotations

import os
import stat
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

from . import db, paths


@dataclass
class ScanProgress:
    files: int = 0
    dirs: int = 0
    bytes: int = 0
    errors: int = 0
    current: str = ""
    reused_dirs: int = 0
    started: float = field(default_factory=time.time)


class Cancelled(Exception):
    pass


def _ext(name: str) -> str:
    dot = name.rfind(".")
    if dot <= 0 or dot == len(name) - 1:
        return ""
    return name[dot + 1 :].lower()[:16]


# A rescan reuses the previous result for folders whose change time is the same.
# Older results, or results from drives whose folder times are unreliable, are
# never reused: the scan then reads everything again.
REUSE_MAX_AGE = 7 * 86400
KEEP_SCANS_PER_FOLDER = 3


def _reuse_allowed(root: str) -> bool:
    if paths.IS_WINDOWS:
        try:
            import ctypes

            fs = ctypes.create_unicode_buffer(32)
            ok = ctypes.windll.kernel32.GetVolumeInformationW(
                ctypes.c_wchar_p(paths.volume_root(root)), None, 0, None, None, None, fs, 32)
            return bool(ok) and fs.value.upper() in ("NTFS", "REFS")
        except Exception:  # noqa: BLE001
            return False
    if paths.IS_MAC:
        return not os.path.abspath(root).startswith("/Volumes/")  # external disks may be FAT/exFAT
    return True


def _previous(conn, root: str):
    """The latest finished scan of ``root`` that a rescan may build on, or None."""
    r = conn.execute(
        "SELECT * FROM scans WHERE root=? AND status='done' ORDER BY id DESC LIMIT 1", (root,)
    ).fetchone()
    if r is None or time.time() - r["started"] > REUSE_MAX_AGE:
        return None
    if conn.execute("SELECT 1 FROM dirs WHERE scan_id=? AND mtime IS NULL LIMIT 1", (r["id"],)).fetchone():
        return None  # made by a version that did not record folder times
    return r


def scan(
    root: str,
    progress: ScanProgress | None = None,
    cancel: threading.Event | None = None,
    on_progress: Callable[[ScanProgress], None] | None = None,
    incremental: bool = True,
) -> int:
    """Scan ``root`` and return the new scan id. Never modifies anything on disk.

    With ``incremental``, a folder whose change time equals the one recorded by
    the previous scan (less than a week old) is not read again: its files are
    copied from that scan. A folder's change time moves whenever a file in it is
    added, removed or renamed. A file edited in place keeps its old size in the
    report until the next full scan; nothing is ever cleaned on the strength of
    the report alone, since every cleanup checks the file on disk first.
    """
    root = os.path.abspath(root)
    if not os.path.isdir(root):
        raise FileNotFoundError(root)
    progress = progress or ScanProgress()
    cancel = cancel or threading.Event()
    conn = db.connect()
    # A scan is only a report: if power fails during it, losing the newest scan is
    # harmless, so it skips the wait for the disk (the action log never does).
    conn.execute("PRAGMA synchronous=NORMAL")
    try:
        return _scan(conn, root, progress, cancel, on_progress, incremental)
    finally:
        conn.execute("PRAGMA synchronous=FULL")


def _scan(conn, root, progress, cancel, on_progress, incremental) -> int:
    prev = _previous(conn, root) if incremental and _reuse_allowed(root) else None
    cur = conn.execute("INSERT INTO scans(root, started) VALUES (?, ?)", (root, time.time()))
    scan_id = cur.lastrowid
    conn.commit()

    prev_dirs: dict[str, tuple[int, float]] = {}
    prev_children: dict[int, list[str]] = {}
    prev_own: dict[int, tuple[int, int]] = {}
    if prev is not None:
        # A folder's own files = its totals minus those of its sub-folders (no need to read the files).
        for r in conn.execute(
            "SELECT id, parent_id, path, mtime, size, file_count FROM dirs WHERE scan_id=?", (prev["id"],)
        ):
            prev_dirs[r["path"]] = (r["id"], r["mtime"])
            prev_children.setdefault(r["parent_id"], []).append(r["path"])
            own = prev_own.get(r["id"], (0, 0))
            prev_own[r["id"]] = (own[0] + r["size"], own[1] + r["file_count"])
            if r["parent_id"] is not None:
                p = prev_own.get(r["parent_id"], (0, 0))
                prev_own[r["parent_id"]] = (p[0] - r["size"], p[1] - r["file_count"])
        # Folders changed this close to the previous scan may have changed again within the same tick.
        fresh_limit = prev["started"] - 2

    skip = paths.skip_dirs()
    seen_inodes: set[tuple[int, int]] = set()

    try:
        root_mtime = os.stat(root).st_mtime
    except OSError:
        root_mtime = None
    dir_paths: list[str] = [root]
    dir_parent: list[int | None] = [None]
    dir_size: list[int] = [0]
    dir_count: list[int] = [0]
    dir_mtime: list[float | None] = [root_mtime]
    file_rows: list[tuple] = []
    reuse: list[tuple[int, int]] = []  # (previous dir id, new dir id)
    stack: list[int] = [0]
    last_report = 0.0

    def add_dir(path: str, parent: int, mtime) -> None:
        dir_paths.append(path)
        dir_parent.append(parent)
        dir_size.append(0)
        dir_count.append(0)
        dir_mtime.append(mtime)
        stack.append(len(dir_paths) - 1)
        progress.dirs += 1

    def flush_files() -> None:
        if file_rows:
            conn.executemany(
                "INSERT INTO files(scan_id, dir_id, name, ext, size, mtime) VALUES (?,?,?,?,?,?)",
                file_rows,
            )
            file_rows.clear()

    try:
        while stack:
            if cancel.is_set():
                raise Cancelled()
            did = stack.pop()
            dpath = dir_paths[did]
            progress.current = dpath
            old = prev_dirs.get(dpath) if prev is not None else None
            if old is not None and dir_mtime[did] is not None and old[1] == dir_mtime[did] and old[1] < fresh_limit:
                # Unchanged folder: same files and sub-folders as last time.
                reuse.append((old[0], did))
                size, count = prev_own.get(old[0], (0, 0))
                dir_size[did] += size
                dir_count[did] += count
                progress.files += count
                progress.bytes += size
                for child in prev_children.get(old[0], []):
                    try:
                        st = os.lstat(paths.lp(child))
                    except OSError:
                        continue
                    if stat.S_ISDIR(st.st_mode):
                        add_dir(child, did, st.st_mtime)
            else:
                try:
                    it = os.scandir(paths.lp(dpath))
                except OSError:
                    progress.errors += 1
                    continue
                with it:
                    for entry in it:
                        try:
                            if entry.is_symlink():
                                continue
                            if entry.is_dir(follow_symlinks=False):
                                full = os.path.join(dpath, entry.name)  # without the long-path prefix
                                if os.path.normcase(full) in skip or entry.name == paths.VOLUME_QUARANTINE:
                                    continue
                                st = entry.stat(follow_symlinks=False)
                                # Skip Windows junctions and directory symlinks (they can loop
                                # or lead elsewhere), but keep other reparse points such as
                                # OneDrive folders.
                                if paths.IS_WINDOWS and getattr(st, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT \
                                        and getattr(st, "st_reparse_tag", 0) in (0xA0000003, 0xA000000C):  # junction, symlink
                                    continue
                                add_dir(full, did, st.st_mtime)
                            elif entry.is_file(follow_symlinks=False):
                                st = entry.stat(follow_symlinks=False)
                                size = st.st_size
                                if not paths.IS_WINDOWS and st.st_nlink > 1:
                                    key = (st.st_dev, st.st_ino)
                                    if key in seen_inodes:
                                        size = 0  # hard link already counted
                                    else:
                                        seen_inodes.add(key)
                                dir_size[did] += size
                                dir_count[did] += 1
                                file_rows.append((scan_id, did, entry.name, _ext(entry.name), size, st.st_mtime))
                                progress.files += 1
                                progress.bytes += size
                        except OSError:
                            progress.errors += 1
            if len(file_rows) >= 5000:
                flush_files()
            now = time.time()
            if on_progress and now - last_report > 0.25:
                last_report = now
                on_progress(progress)
        flush_files()
        if reuse:
            conn.execute("CREATE TEMP TABLE IF NOT EXISTS reuse(prev_id INTEGER PRIMARY KEY, new_id INTEGER)")
            conn.execute("DELETE FROM reuse")
            conn.executemany("INSERT INTO reuse(prev_id, new_id) VALUES (?,?)", reuse)
            conn.execute(
                """INSERT INTO files(scan_id, dir_id, name, ext, size, mtime)
                   SELECT ?, r.new_id, f.name, f.ext, f.size, f.mtime
                   FROM files f JOIN reuse r ON f.dir_id = r.prev_id WHERE f.scan_id = ?""",
                (scan_id, prev["id"]),
            )
            conn.execute("DELETE FROM reuse")

        # Children always get larger ids than their parent, so one reverse pass
        # rolls sizes up the tree.
        for i in range(len(dir_paths) - 1, 0, -1):
            p = dir_parent[i]
            dir_size[p] += dir_size[i]
            dir_count[p] += dir_count[i]

        rows = (
            (scan_id, i, dir_parent[i], dir_paths[i], os.path.basename(dir_paths[i]) or dir_paths[i],
             dir_size[i], dir_count[i], dir_mtime[i])
            for i in range(len(dir_paths))
        )
        conn.executemany(
            "INSERT INTO dirs(scan_id, id, parent_id, path, name, size, file_count, mtime) VALUES (?,?,?,?,?,?,?,?)", rows
        )
        conn.execute(
            "UPDATE scans SET finished=?, status='done', total_size=?, file_count=?, dir_count=?, error_count=? WHERE id=?",
            (time.time(), dir_size[0], progress.files, len(dir_paths), progress.errors, scan_id),
        )
        conn.commit()
    except Cancelled:
        conn.rollback()
        delete_scan(scan_id)
        raise
    except Exception:
        conn.rollback()
        conn.execute("UPDATE scans SET status='error', finished=? WHERE id=?", (time.time(), scan_id))
        conn.commit()
        raise
    progress.reused_dirs = len(reuse)
    prune_scans(root)
    if on_progress:
        on_progress(progress)
    return scan_id


def prune_scans(root: str, keep: int = KEEP_SCANS_PER_FOLDER) -> int:
    """Delete all but the newest ``keep`` finished scans of ``root`` (the database stays small)."""
    ids = [r["id"] for r in db.connect().execute(
        "SELECT id FROM scans WHERE root=? AND status IN ('done','error') ORDER BY id DESC", (root,))]
    for sid in ids[keep:]:
        delete_scan(sid)
    return max(0, len(ids) - keep)


def cleanup_unfinished() -> int:
    """Remove scans a crash left half written. Call only while holding the instance lock."""
    ids = [r["id"] for r in db.connect().execute("SELECT id FROM scans WHERE status='running'")]
    for sid in ids:
        delete_scan(sid)
    return len(ids)


def delete_scan(scan_id: int) -> None:
    conn = db.connect()
    for table in ("files", "dirs", "dup_groups", "similar_groups"):
        conn.execute(f"DELETE FROM {table} WHERE scan_id=?", (scan_id,))
    conn.execute("DELETE FROM scans WHERE id=?", (scan_id,))
    conn.commit()


# ---------- report queries ----------

CATEGORIES = {
    "Video": {"mp4", "mkv", "avi", "mov", "wmv", "flv", "webm", "m4v", "mpg", "mpeg", "3gp"},
    "Ảnh": {"jpg", "jpeg", "png", "gif", "bmp", "tif", "tiff", "heic", "heif", "webp", "raw", "cr2", "nef", "arw", "dng", "psd", "svg"},
    "Âm thanh": {"mp3", "wav", "flac", "aac", "m4a", "ogg", "wma", "aiff"},
    "Tài liệu": {"pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "txt", "rtf", "odt", "ods", "odp", "csv", "md", "pages", "numbers", "key", "epub"},
    "Nén / bộ cài": {"zip", "rar", "7z", "tar", "gz", "bz2", "xz", "iso", "dmg", "pkg", "exe", "msi", "img", "apk", "cab"},
    "Mã nguồn / dev": {"py", "js", "ts", "java", "c", "cpp", "h", "cs", "go", "rs", "rb", "php", "html", "css", "json", "xml", "yml", "yaml", "jar", "class", "o", "pyc", "node", "so", "dll", "dylib", "lib", "a"},
    "Tạm / bộ nhớ đệm": {"tmp", "temp", "log", "cache", "bak", "old", "dmp", "crdownload", "part"},
}


def category_of(ext: str) -> str:
    for cat, exts in CATEGORIES.items():
        if ext in exts:
            return cat
    return "Khác"


def latest_scans(limit: int = 20) -> list[dict]:
    rows = db.connect().execute(
        "SELECT * FROM scans WHERE status='done' ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    return [dict(r) for r in rows]


def get_scan(scan_id: int) -> dict | None:
    r = db.connect().execute("SELECT * FROM scans WHERE id=?", (scan_id,)).fetchone()
    return dict(r) if r else None


def children(scan_id: int, dir_id: int = 0, limit: int = 300) -> dict:
    conn = db.connect()
    me = conn.execute("SELECT * FROM dirs WHERE scan_id=? AND id=?", (scan_id, dir_id)).fetchone()
    if me is None:
        raise KeyError(dir_id)
    # Breadcrumb
    crumbs = []
    cur = me
    while cur is not None:
        crumbs.append({"id": cur["id"], "name": cur["name"], "path": cur["path"]})
        cur = (
            conn.execute("SELECT * FROM dirs WHERE scan_id=? AND id=?", (scan_id, cur["parent_id"])).fetchone()
            if cur["parent_id"] is not None
            else None
        )
    crumbs.reverse()
    items = [
        {"type": "dir", "id": r["id"], "name": r["name"], "path": r["path"], "size": r["size"], "count": r["file_count"]}
        for r in conn.execute(
            "SELECT * FROM dirs WHERE scan_id=? AND parent_id=? ORDER BY size DESC LIMIT ?", (scan_id, dir_id, limit)
        )
    ]
    sep = os.sep
    for r in conn.execute(
        "SELECT name, size, mtime FROM files WHERE scan_id=? AND dir_id=? ORDER BY size DESC LIMIT ?",
        (scan_id, dir_id, limit),
    ):
        items.append({
            "type": "file", "name": r["name"], "path": me["path"].rstrip(sep) + sep + r["name"],
            "size": r["size"], "mtime": r["mtime"],
        })
    items.sort(key=lambda x: x["size"], reverse=True)
    return {
        "dir": {"id": me["id"], "path": me["path"], "size": me["size"], "count": me["file_count"]},
        "crumbs": crumbs,
        "items": items[:limit],
    }


def large_files(scan_id: int, limit: int = 200, min_size: int = 0) -> list[dict]:
    sep = os.sep

    def query(extra: str):
        return db.connect().execute(
            f"""SELECT f.name, f.size, f.mtime, f.ext, d.path AS dpath FROM files f
               JOIN dirs d ON d.scan_id=f.scan_id AND d.id=f.dir_id
               WHERE f.scan_id=? AND f.size>=? {extra} ORDER BY f.size DESC LIMIT ?""",
            (scan_id, min_size, limit),
        ).fetchall()

    rows = query("AND f." + db.BIG_FILE_SQL)  # fast: uses the index of files >= 64 KB
    if len(rows) < limit and min_size < db.BIG_FILE:
        rows = query("")  # a small folder: not enough big files to fill the list
    out = []
    for r in rows:
        p = r["dpath"].rstrip(sep) + sep + r["name"]
        out.append({
            "path": p, "name": r["name"], "size": r["size"], "mtime": r["mtime"],
            "category": category_of(r["ext"]), **paths.file_flags(p),
        })
    return out


def type_breakdown(scan_id: int) -> dict:
    conn = db.connect()
    by_ext = conn.execute(
        "SELECT ext, SUM(size) AS size, COUNT(*) AS n FROM files WHERE scan_id=? GROUP BY ext ORDER BY size DESC",
        (scan_id,),
    ).fetchall()
    cats: dict[str, dict] = {}
    for r in by_ext:
        c = category_of(r["ext"])
        slot = cats.setdefault(c, {"category": c, "size": 0, "count": 0})
        slot["size"] += r["size"] or 0
        slot["count"] += r["n"]
    return {
        "categories": sorted(cats.values(), key=lambda x: x["size"], reverse=True),
        "extensions": [
            {"ext": r["ext"] or "(không đuôi)", "size": r["size"] or 0, "count": r["n"]} for r in by_ext[:30]
        ],
    }


def old_files(scan_id: int, older_than_days: int = 365, min_size: int = 50 * 1024 * 1024, limit: int = 200) -> list[dict]:
    cutoff = time.time() - older_than_days * 86400
    sep = os.sep
    big = ("AND f." + db.BIG_FILE_SQL) if min_size >= db.BIG_FILE else ""
    rows = db.connect().execute(
        f"""SELECT f.name, f.size, f.mtime, f.ext, d.path AS dpath FROM files f
           JOIN dirs d ON d.scan_id=f.scan_id AND d.id=f.dir_id
           WHERE f.scan_id=? AND f.size>=? {big} AND f.mtime<? ORDER BY f.size DESC LIMIT ?""",
        (scan_id, min_size, cutoff, limit),
    ).fetchall()
    return [
        {"path": (p := r["dpath"].rstrip(sep) + sep + r["name"]), "name": r["name"], "size": r["size"],
         "mtime": r["mtime"], "category": category_of(r["ext"]), **paths.file_flags(p)}
        for r in rows
    ]
