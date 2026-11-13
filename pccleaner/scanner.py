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
    started: float = field(default_factory=time.time)


class Cancelled(Exception):
    pass


def _ext(name: str) -> str:
    dot = name.rfind(".")
    if dot <= 0 or dot == len(name) - 1:
        return ""
    return name[dot + 1 :].lower()[:16]


def scan(
    root: str,
    progress: ScanProgress | None = None,
    cancel: threading.Event | None = None,
    on_progress: Callable[[ScanProgress], None] | None = None,
) -> int:
    """Scan ``root`` and return the new scan id. Never modifies anything on disk."""
    root = os.path.abspath(root)
    if not os.path.isdir(root):
        raise FileNotFoundError(root)
    progress = progress or ScanProgress()
    cancel = cancel or threading.Event()
    conn = db.connect()
    cur = conn.execute("INSERT INTO scans(root, started) VALUES (?, ?)", (root, time.time()))
    scan_id = cur.lastrowid
    conn.commit()

    skip = paths.skip_dirs()
    seen_inodes: set[tuple[int, int]] = set()

    dir_paths: list[str] = [root]
    dir_parent: list[int | None] = [None]
    dir_size: list[int] = [0]
    dir_count: list[int] = [0]
    file_rows: list[tuple] = []
    stack: list[int] = [0]
    last_report = 0.0

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
            try:
                it = os.scandir(dpath)
            except OSError:
                progress.errors += 1
                continue
            with it:
                for entry in it:
                    try:
                        if entry.is_symlink():
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            full = entry.path
                            if os.path.normcase(full) in skip:
                                continue
                            # Skip Windows junctions / reparse points to avoid loops.
                            if paths.IS_WINDOWS:
                                st = entry.stat(follow_symlinks=False)
                                if getattr(st, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                                    continue
                            new_id = len(dir_paths)
                            dir_paths.append(full)
                            dir_parent.append(did)
                            dir_size.append(0)
                            dir_count.append(0)
                            stack.append(new_id)
                            progress.dirs += 1
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

        # Children always get larger ids than their parent, so one reverse pass
        # rolls sizes up the tree.
        for i in range(len(dir_paths) - 1, 0, -1):
            p = dir_parent[i]
            dir_size[p] += dir_size[i]
            dir_count[p] += dir_count[i]

        rows = (
            (scan_id, i, dir_parent[i], dir_paths[i], os.path.basename(dir_paths[i]) or dir_paths[i], dir_size[i], dir_count[i])
            for i in range(len(dir_paths))
        )
        conn.executemany(
            "INSERT INTO dirs(scan_id, id, parent_id, path, name, size, file_count) VALUES (?,?,?,?,?,?,?)", rows
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
    if on_progress:
        on_progress(progress)
    return scan_id


def delete_scan(scan_id: int) -> None:
    conn = db.connect()
    for table in ("files", "dirs", "dup_groups"):
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
    rows = db.connect().execute(
        """SELECT f.name, f.size, f.mtime, f.ext, d.path AS dpath FROM files f
           JOIN dirs d ON d.scan_id=f.scan_id AND d.id=f.dir_id
           WHERE f.scan_id=? AND f.size>=? ORDER BY f.size DESC LIMIT ?""",
        (scan_id, min_size, limit),
    ).fetchall()
    out = []
    for r in rows:
        p = r["dpath"].rstrip(sep) + sep + r["name"]
        out.append({
            "path": p, "name": r["name"], "size": r["size"], "mtime": r["mtime"],
            "category": category_of(r["ext"]), "protected": paths.is_protected(p),
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
    rows = db.connect().execute(
        """SELECT f.name, f.size, f.mtime, f.ext, d.path AS dpath FROM files f
           JOIN dirs d ON d.scan_id=f.scan_id AND d.id=f.dir_id
           WHERE f.scan_id=? AND f.size>=? AND f.mtime<? ORDER BY f.size DESC LIMIT ?""",
        (scan_id, min_size, cutoff, limit),
    ).fetchall()
    return [
        {"path": r["dpath"].rstrip(sep) + sep + r["name"], "name": r["name"], "size": r["size"],
         "mtime": r["mtime"], "category": category_of(r["ext"])}
        for r in rows
    ]
