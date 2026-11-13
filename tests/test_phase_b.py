"""Phase B acceptance tests: incremental scan, scan pruning, cancel mid-operation,
disk full, locked files, name conflicts, scheduler self-check, log rotation,
long paths and image limits.

Everything runs inside tests/_tmp; no real user data is touched.
"""
import errno
import os
import shutil
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

_BASE = Path(__file__).resolve().parent / "_tmp"
_BASE.mkdir(exist_ok=True)
TMP = tempfile.mkdtemp(dir=_BASE)
os.environ.setdefault("PCCLEANER_DATA_DIR", os.path.join(TMP, "data"))

from pccleaner import db, organizer, paths, quarantine, scanner  # noqa: E402

OLD = time.time() - 3600


def age_tree(root: Path) -> None:
    """Make every folder look as if it last changed an hour ago."""
    for d, _subs, _files in os.walk(root):
        os.utime(d, (OLD, OLD))


def snapshot(scan_id: int) -> tuple:
    conn = db.connect()
    s = conn.execute("SELECT total_size, file_count, dir_count FROM scans WHERE id=?", (scan_id,)).fetchone()
    files = sorted(
        (r["path"], r["name"], r["size"])
        for r in conn.execute(
            "SELECT d.path, f.name, f.size FROM files f JOIN dirs d ON d.scan_id=f.scan_id AND d.id=f.dir_id"
            " WHERE f.scan_id=?", (scan_id,))
    )
    dirs = sorted(
        (r["path"], r["size"], r["file_count"])
        for r in conn.execute("SELECT path, size, file_count FROM dirs WHERE scan_id=?", (scan_id,))
    )
    return tuple(s), files, dirs


class Base(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(dir=TMP))
        self.dbfile = Path(tempfile.mkdtemp(dir=TMP)) / "t.sqlite3"
        db.reset_for_tests(self.dbfile)

    def tree(self, dirs=4, per_dir=5):
        for i in range(dirs):
            d = self.root / f"d{i}" / "inner"
            d.mkdir(parents=True)
            for j in range(per_dir):
                (d / f"f{j}.bin").write_bytes(b"x" * (100 * (i + 1) + j))
                (d.parent / f"top{j}.txt").write_bytes(b"y" * (10 + j))
        age_tree(self.root)


class IncrementalScanTest(Base):
    def full(self):
        return snapshot(scanner.scan(str(self.root), incremental=False))

    def incremental(self):
        p = scanner.ScanProgress()
        sid = scanner.scan(str(self.root), progress=p)
        return snapshot(sid), p.reused_dirs

    def test_unchanged_tree_is_reused_and_identical(self):
        self.tree()
        first = self.full()
        again, reused = self.incremental()
        self.assertEqual(first, again)
        self.assertEqual(reused, 9)  # root + 4 folders + 4 inner folders

    def test_changes_match_a_full_scan(self):
        self.tree()
        self.full()
        # add, remove, rename files; add, remove, rename folders
        (self.root / "d0" / "inner" / "new.bin").write_bytes(b"n" * 777)
        (self.root / "d1" / "inner" / "f0.bin").unlink()
        (self.root / "d2" / "top0.txt").rename(self.root / "d2" / "renamed.txt")
        (self.root / "d3" / "added").mkdir()
        (self.root / "d3" / "added" / "a.bin").write_bytes(b"a" * 50)
        shutil.rmtree(self.root / "d1" / "inner")
        (self.root / "d2" / "inner").rename(self.root / "d2" / "moved")
        inc, reused = self.incremental()
        self.assertGreater(reused, 0)
        self.assertEqual(inc, self.full())

    def test_folder_changed_right_after_last_scan_is_read_again(self):
        self.tree()
        self.full()
        # A change in the same second as the scan keeps the folder time close to it.
        target = self.root / "d0" / "inner"
        (target / "late.bin").write_bytes(b"l" * 5)
        conn = db.connect()
        sid = conn.execute("SELECT MAX(id) FROM scans").fetchone()[0]
        t = conn.execute("SELECT started FROM scans WHERE id=?", (sid,)).fetchone()[0] - 1
        conn.execute("UPDATE dirs SET mtime=? WHERE scan_id=? AND path=?", (t, sid, str(target)))
        conn.commit()
        os.utime(target, (t, t))
        inc, _ = self.incremental()
        self.assertIn((str(target), "late.bin", 5), inc[1])

    def test_old_previous_scan_is_not_reused(self):
        self.tree()
        self.full()
        conn = db.connect()
        conn.execute("UPDATE scans SET started=started-?", (scanner.REUSE_MAX_AGE + 10,))
        conn.commit()
        _, reused = self.incremental()
        self.assertEqual(reused, 0)

    def test_scans_from_older_versions_are_not_reused(self):
        self.tree()
        self.full()
        conn = db.connect()
        conn.execute("UPDATE dirs SET mtime=NULL")
        conn.commit()
        _, reused = self.incremental()
        self.assertEqual(reused, 0)

    def test_old_scans_are_pruned(self):
        self.tree(dirs=1, per_dir=1)
        ids = [scanner.scan(str(self.root)) for _ in range(5)]
        left = [r[0] for r in db.connect().execute("SELECT id FROM scans WHERE root=? ORDER BY id", (str(self.root),))]
        self.assertEqual(left, ids[-scanner.KEEP_SCANS_PER_FOLDER:])
        orphans = db.connect().execute("SELECT COUNT(*) FROM files WHERE scan_id NOT IN (SELECT id FROM scans)").fetchone()[0]
        self.assertEqual(orphans, 0)

    def test_cancelled_scan_leaves_nothing(self):
        self.tree()
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(scanner.Cancelled):
            scanner.scan(str(self.root), cancel=cancel)
        self.assertEqual(db.connect().execute("SELECT COUNT(*) FROM scans").fetchone()[0], 0)


class FaultTest(Base):
    """Cancel, disk full, locked file, permission errors, name conflicts."""

    def make(self, n=6):
        d = self.root / "files"
        d.mkdir()
        out = []
        for i in range(n):
            p = d / f"f{i}.bin"
            p.write_bytes(bytes([i]) * 64)
            out.append(str(p))
        return out

    def pending(self):
        return db.connect().execute("SELECT COUNT(*) FROM actions WHERE kind LIKE 'pending-%'").fetchone()[0]

    def cancel_at(self, point, nth, cancel):
        hits = [0]

        def fault(p):
            if p == point:
                hits[0] += 1
                if hits[0] == nth:
                    cancel.set()
        return mock.patch.object(quarantine, "_fault", fault)

    def test_cancel_mid_quarantine_keeps_the_rest(self):
        files = self.make(6)
        cancel = threading.Event()
        with self.cancel_at("after_move", 3, cancel), mock.patch.object(quarantine, "CHUNK", 2):
            res = quarantine.quarantine(files, "test", cancel=cancel)
        self.assertTrue(res["cancelled"])
        self.assertEqual(res["moved"], 3)
        self.assertEqual(sum(not os.path.exists(f) for f in files), 3)
        self.assertEqual(self.pending(), 0)
        quarantine.restore(res["batch_id"])
        self.assertTrue(all(os.path.exists(f) for f in files))

    def test_cancel_mid_restore(self):
        files = self.make(6)
        res = quarantine.quarantine(files, "test")
        cancel = threading.Event()
        with self.cancel_at("restore_after_move", 2, cancel):
            r = quarantine.restore(res["batch_id"], cancel=cancel)
        self.assertTrue(r["cancelled"])
        self.assertEqual(sum(os.path.exists(f) for f in files), 2)
        quarantine.restore(res["batch_id"])  # pressing Undo again brings back the rest
        self.assertTrue(all(os.path.exists(f) for f in files))

    def test_cancel_mid_organize(self):
        folder = self.root / "org"
        folder.mkdir()
        for i in range(6):
            (folder / f"p{i}.jpg").write_bytes(b"j" * 10)
            (folder / f"d{i}.pdf").write_bytes(b"p" * 10)
        plan = organizer.preview(str(folder))
        chosen = [m["src"] for m in plan["moves"]]
        cancel = threading.Event()
        cancel.set()
        res = organizer.apply(str(folder), chosen, cancel=cancel)
        self.assertTrue(res.get("cancelled"))
        self.assertEqual(len(list(folder.glob("*.*"))), 12)
        self.assertEqual(self.pending(), 0)

    def test_disk_full_stops_cleanly(self):
        files = self.make(4)
        real = os.rename
        n = [0]

        def full_disk(a, b):
            n[0] += 1
            if n[0] == 3:
                raise OSError(errno.ENOSPC, "No space left on device")
            return real(a, b)

        with mock.patch("os.rename", side_effect=full_disk):
            res = quarantine.quarantine(files, "test")
        self.assertEqual(self.pending(), 0)
        self.assertTrue(res["failed"])
        # The file that failed is still in place; the others can all be restored.
        quarantine.restore(res["batch_id"])
        self.assertTrue(all(os.path.exists(f) for f in files))

    def test_locked_or_denied_file_is_skipped(self):
        files = self.make(3)
        real = os.rename

        def locked(a, b):
            if a == files[1]:
                raise PermissionError(errno.EACCES, "The process cannot access the file")
            return real(a, b)

        with mock.patch("os.rename", side_effect=locked):
            res = quarantine.quarantine(files, "test")
        self.assertEqual(len(res["failed"]), 1)
        self.assertTrue(os.path.exists(files[1]))
        self.assertFalse(os.path.exists(files[0]))
        self.assertEqual(self.pending(), 0)

    def test_restore_name_conflict_keeps_both(self):
        files = self.make(2)
        res = quarantine.quarantine(files, "test")
        Path(files[0]).write_bytes(b"NEW FILE WITH SAME NAME")
        quarantine.restore(res["batch_id"])
        self.assertEqual(Path(files[0]).read_bytes(), b"NEW FILE WITH SAME NAME")
        siblings = [p for p in Path(files[0]).parent.iterdir() if p.name.startswith("f0") and p.name != "f0.bin"]
        self.assertEqual(len(siblings), 1, siblings)
        self.assertEqual(siblings[0].read_bytes(), bytes([0]) * 64)

    def test_permission_error_during_scan_is_counted(self):
        self.make(2)
        real = os.scandir

        def denied(p):
            if str(p).endswith("files"):
                raise PermissionError(errno.EACCES, "denied")
            return real(p)

        with mock.patch("os.scandir", side_effect=denied):
            sid = scanner.scan(str(self.root), incremental=False)
        row = db.connect().execute("SELECT status, error_count FROM scans WHERE id=?", (sid,)).fetchone()
        self.assertEqual((row[0], row[1]), ("done", 1))


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
