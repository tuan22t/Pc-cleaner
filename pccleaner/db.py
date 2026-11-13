"""SQLite cache for scan results, file hashes and the action log."""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from . import APP_NAME, paths
from .i18n import _

SCHEMA = """
CREATE TABLE IF NOT EXISTS scans (
    id INTEGER PRIMARY KEY,
    root TEXT NOT NULL,
    started REAL NOT NULL,
    finished REAL,
    status TEXT NOT NULL DEFAULT 'running',
    total_size INTEGER DEFAULT 0,
    file_count INTEGER DEFAULT 0,
    dir_count INTEGER DEFAULT 0,
    error_count INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS dirs (
    scan_id INTEGER NOT NULL,
    id INTEGER NOT NULL,
    parent_id INTEGER,
    path TEXT NOT NULL,
    name TEXT NOT NULL,
    size INTEGER DEFAULT 0,
    file_count INTEGER DEFAULT 0,
    PRIMARY KEY (scan_id, id)
);
CREATE INDEX IF NOT EXISTS dirs_parent ON dirs(scan_id, parent_id);
CREATE INDEX IF NOT EXISTS dirs_path ON dirs(scan_id, path);
CREATE TABLE IF NOT EXISTS files (
    scan_id INTEGER NOT NULL,
    dir_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    ext TEXT NOT NULL,
    size INTEGER NOT NULL,
    mtime REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS files_dir ON files(scan_id, dir_id);
CREATE INDEX IF NOT EXISTS files_size ON files(scan_id, size);
CREATE TABLE IF NOT EXISTS hashes (
    path TEXT PRIMARY KEY,
    size INTEGER NOT NULL,
    mtime REAL NOT NULL,
    partial TEXT,
    full TEXT
);
CREATE TABLE IF NOT EXISTS dup_groups (
    scan_id INTEGER NOT NULL,
    group_id INTEGER NOT NULL,
    hash TEXT NOT NULL,
    size INTEGER NOT NULL,
    path TEXT NOT NULL,
    mtime REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS dup_scan ON dup_groups(scan_id, group_id);
CREATE TABLE IF NOT EXISTS actions (
    id INTEGER PRIMARY KEY,
    batch_id TEXT NOT NULL,
    ts REAL NOT NULL,
    kind TEXT NOT NULL,          -- quarantine | move | mkdir | restore | purge | error | pending-quarantine | pending-move | aborted
    path TEXT NOT NULL,          -- original location
    stored_at TEXT,              -- location inside quarantine
    size INTEGER DEFAULT 0,
    reason TEXT,
    restored INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS actions_batch ON actions(batch_id);
CREATE TABLE IF NOT EXISTS similar_groups (
    scan_id INTEGER NOT NULL,
    group_id INTEGER NOT NULL,
    path TEXT NOT NULL,
    size INTEGER NOT NULL,
    mtime REAL NOT NULL,
    width INTEGER,
    height INTEGER,
    distance INTEGER
);
CREATE INDEX IF NOT EXISTS similar_scan ON similar_groups(scan_id, group_id);
CREATE TABLE IF NOT EXISTS image_hashes (
    path TEXT PRIMARY KEY,
    size INTEGER NOT NULL,
    mtime REAL NOT NULL,
    dhash TEXT,
    width INTEGER,
    height INTEGER
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS startup_changes (
    id INTEGER PRIMARY KEY,
    ts REAL NOT NULL,
    item_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    name TEXT NOT NULL,
    original TEXT,              -- JSON describing how to restore it
    active INTEGER DEFAULT 1    -- 1 = currently disabled by us
);
"""

_local = threading.local()
_db_path: Path | None = None


def db_path() -> Path:
    global _db_path
    if _db_path is None:
        _db_path = paths.data_dir() / "cache.sqlite3"
    return _db_path


# Schema version, stored in SQLite's user_version. Each entry upgrades the
# database from the previous version; never edit an entry once released, add a
# new one instead. Version 1 is the original schema (CREATE ... IF NOT EXISTS,
# so databases made before versioning existed are adopted as version 1).
MIGRATIONS: list[str] = [
    SCHEMA,                                                            # 1
    "CREATE INDEX IF NOT EXISTS actions_kind ON actions(kind);",       # 2: fast look-up of unfinished moves
    "ALTER TABLE dirs ADD COLUMN mtime REAL;",                          # 3: folder change time, for quick rescans
    # 4: index only files of 64 KB or more by size. Most files are small, so
    # writing a scan (and copying rows on a rescan) is about twice as fast.
    "DROP INDEX IF EXISTS files_size;"
    "CREATE INDEX IF NOT EXISTS files_big ON files(scan_id, size) WHERE size >= 65536;",
    # 5: a folder's file rows may belong to an earlier scan (fscan, fdir): a rescan
    # points unchanged folders at them instead of copying every row again.
    "ALTER TABLE dirs ADD COLUMN fscan INTEGER;"
    "ALTER TABLE dirs ADD COLUMN fdir INTEGER;"
    "UPDATE dirs SET fscan=scan_id, fdir=id;"
    "CREATE INDEX IF NOT EXISTS dirs_src ON dirs(fscan, fdir, scan_id);",
    # 6: used space of each drive, one reading a day, for the Dashboard history chart.
    "CREATE TABLE IF NOT EXISTS disk_history (path TEXT NOT NULL, day TEXT NOT NULL, ts REAL NOT NULL,"
    " total INTEGER NOT NULL, used INTEGER NOT NULL, PRIMARY KEY (path, day));",
]
# Queries on size can use the files_big index only when they repeat this
# condition literally (SQLite does not match it against a bound parameter).
BIG_FILE = 65536
BIG_FILE_SQL = "size >= 65536"
SCHEMA_VERSION = len(MIGRATIONS)


class NewerDatabaseError(RuntimeError):
    pass


def _statements(script: str) -> list[str]:
    out, buf = [], ""
    for part in script.split(";"):
        buf += part + ";"
        if sqlite3.complete_statement(buf):
            if buf.strip(" \n;"):
                out.append(buf)
            buf = ""
    return out


def _migrate(conn: sqlite3.Connection) -> None:
    """Bring the schema up to date. Several threads or processes (the window and
    a scheduled run) may open a fresh database at once: the write lock is taken
    before the version is read, so each upgrade runs exactly once."""
    if conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION:
        return
    conn.execute("BEGIN IMMEDIATE")
    try:
        current = conn.execute("PRAGMA user_version").fetchone()[0]
        if current > SCHEMA_VERSION:
            raise NewerDatabaseError()
        for version in range(current + 1, SCHEMA_VERSION + 1):
            for stmt in _statements(MIGRATIONS[version - 1]):
                conn.execute(stmt)
        conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        conn.execute("COMMIT")
    except NewerDatabaseError:
        conn.execute("ROLLBACK")
        conn.close()
        # Written by a newer version of the app: refuse rather than risk damaging it.
        # (The message is looked up only now: that may open the database again.)
        raise NewerDatabaseError(
            _("Dữ liệu được tạo bởi phiên bản {0} mới hơn. Hãy cài lại phiên bản mới nhất.", APP_NAME)
        ) from None
    except BaseException:
        conn.execute("ROLLBACK")
        raise


def connect() -> sqlite3.Connection:
    """One connection per thread; WAL lets the UI read while a scan writes.

    synchronous=FULL: a committed transaction survives a power cut. The action
    log depends on this: a file is only moved after its log row is on disk.
    """
    conn = getattr(_local, "conn", None)
    if conn is None or getattr(_local, "path", None) != db_path():
        conn = sqlite3.connect(db_path(), timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=FULL")
        _migrate(conn)
        _local.conn = conn
        _local.path = db_path()
    return conn


def reset_for_tests(path: Path) -> None:
    global _db_path
    _db_path = path
    _local.conn = None
    from . import i18n

    i18n.reset()


def get_setting(key: str, default=None):
    r = connect().execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return r["value"] if r else default


def set_setting(key: str, value) -> None:
    conn = connect()
    conn.execute("INSERT INTO settings(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))
    conn.commit()


def scan_sources(conn, scan_id: int) -> list[int]:
    """The scans whose file rows make up ``scan_id`` (itself plus any it reuses)."""
    return [r[0] for r in conn.execute("SELECT DISTINCT fscan FROM dirs WHERE scan_id=?", (scan_id,))] or [scan_id]


def scan_files(conn, scan_id: int) -> tuple[str, list]:
    """SQL (FROM … WHERE …, aliases f and d) and parameters selecting every file of a scan."""
    src = scan_sources(conn, scan_id)
    marks = ",".join("?" * len(src))
    return (f"FROM files f JOIN dirs d ON d.scan_id=? AND d.fscan=f.scan_id AND d.fdir=f.dir_id "
            f"WHERE f.scan_id IN ({marks})", [scan_id, *src])
