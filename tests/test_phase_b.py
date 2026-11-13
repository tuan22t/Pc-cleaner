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

from pccleaner import db, organizer, paths, quarantine, scanner, scheduler, server, similar, startup, startup_base  # noqa: E402

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


class SchedulerHealthTest(Base):
    def cfg(self):
        return dict(scheduler.DEFAULTS, enabled=True)

    def test_disabled_is_healthy(self):
        self.assertTrue(scheduler.health(dict(scheduler.DEFAULTS))["ok"])

    def test_detects_moved_app_and_fixes_it(self):
        db.set_setting("schedule", __import__("json").dumps(self.cfg()))
        registered = []
        with mock.patch.object(paths, "IS_WINDOWS", True), \
                mock.patch.object(scheduler, "_registered_command", return_value='"D:\\Old place\\PCCleaner.exe" --auto-clean'), \
                mock.patch.object(scheduler, "_command", return_value=["C:\\New\\PCCleaner.exe", "--auto-clean"]), \
                mock.patch.object(scheduler, "_register", side_effect=registered.append):
            self.assertEqual(scheduler.health(self.cfg())["problem"], "moved")
            r = scheduler.self_check()
        self.assertEqual(r.get("fixed"), "moved")
        self.assertEqual(len(registered), 1)

    def test_same_command_is_healthy(self):
        with mock.patch.object(paths, "IS_WINDOWS", True), \
                mock.patch.object(scheduler, "_registered_command", return_value='"C:\\Program Files\\PCCleaner\\PCCleaner.exe" --auto-clean'), \
                mock.patch.object(scheduler, "_command", return_value=["C:\\Program Files\\PCCleaner\\PCCleaner.exe", "--auto-clean"]):
            self.assertTrue(scheduler.health(self.cfg())["ok"])

    def test_missing_task_is_reported(self):
        with mock.patch.object(paths, "IS_WINDOWS", True), \
                mock.patch.object(scheduler, "_registered_command", return_value=None):
            self.assertEqual(scheduler.health(self.cfg())["problem"], "missing")

    def test_mac_translocation_is_not_registered(self):
        db.set_setting("schedule", __import__("json").dumps(self.cfg()))
        with mock.patch.object(paths, "IS_WINDOWS", False), mock.patch.object(paths, "IS_MAC", True), \
                mock.patch.object(scheduler.sys, "executable", "/private/var/folders/x/AppTranslocation/ABC/d/PCCleaner.app/Contents/MacOS/PCCleaner"), \
                mock.patch.object(scheduler, "_register") as reg:
            r = scheduler.self_check()
        self.assertEqual(r["problem"], "translocated")
        reg.assert_not_called()


class LogRotationTest(Base):
    def test_log_is_rotated(self):
        log = paths.data_dir() / "app.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_bytes(b"x" * server.LOG_MAX_BYTES)
        try:
            raise ValueError("boom")
        except ValueError:
            server._log_exc()
        self.assertEqual((paths.data_dir() / "app.log.1").stat().st_size, server.LOG_MAX_BYTES)
        self.assertIn("boom", log.read_text(encoding="utf-8"))
        self.assertLess(log.stat().st_size, 10_000)


class LongPathTest(Base):
    def test_prefix_rules(self):
        with mock.patch.object(paths, "IS_WINDOWS", True):
            long_path = "C:\\" + "folder\\" * 40 + "f.txt"
            self.assertTrue(paths.lp(long_path).startswith("\\\\?\\C:\\"))
            self.assertTrue(paths.lp("\\\\server\\share\\" + "d\\" * 130).startswith("\\\\?\\UNC\\server"))
            self.assertEqual(paths.lp("C:\\short.txt"), "C:\\short.txt")
        with mock.patch.object(paths, "IS_WINDOWS", False):
            self.assertEqual(paths.lp("/x" * 200), "/x" * 200)  # unchanged elsewhere

    @unittest.skipUnless(paths.IS_WINDOWS, "Windows only")
    def test_quarantine_and_restore_deep_file(self):
        deep = str(self.root) + "\\" + "\\".join(["thu-muc-rat-dai-%02d" % i for i in range(16)])
        self.assertGreater(len(deep), 300)
        os.makedirs(paths.lp(deep))
        f = deep + "\\tai-lieu.txt"
        with open(paths.lp(f), "w") as fh:
            fh.write("hello")
        res = quarantine.quarantine([f], "test")
        self.assertEqual(res["moved"], 1, res)
        self.assertFalse(os.path.exists(paths.lp(f)))
        quarantine.restore(res["batch_id"])
        self.assertTrue(os.path.exists(paths.lp(f)))
        sid = scanner.scan(str(self.root), incremental=False)
        self.assertGreaterEqual(db.connect().execute("SELECT file_count FROM scans WHERE id=?", (sid,)).fetchone()[0], 1)


class ImageLimitTest(Base):
    def test_huge_image_is_skipped(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow not installed")
        p = self.root / "big.png"
        Image.new("L", (100, 100)).save(p)
        with mock.patch.object(similar, "MAX_PIXELS", 5000):
            with self.assertRaises(OSError):
                similar.dhash(str(p))
        self.assertEqual(similar.dhash(str(p))[1:], (100, 100))


class FakeRun:
    """Records commands instead of running them."""

    def __init__(self, rc=0, out="", err=""):
        self.calls, self.rc, self.out, self.err = [], rc, out, err

    def __call__(self, cmd):
        self.calls.append(cmd)
        return mock.Mock(returncode=self.rc, stdout=self.out, stderr=self.err)


class SchedulerRegisterTest(Base):
    def test_windows_task_is_created_for_current_user(self):
        run = FakeRun()
        with mock.patch.object(paths, "IS_WINDOWS", True), mock.patch.object(paths, "IS_MAC", False), \
                mock.patch.object(scheduler, "_run", run), mock.patch.object(scheduler, "health", return_value={"ok": True}):
            cfg = scheduler.save({"enabled": True, "frequency": "weekly", "hour": 30, "purge_days": 9999})
        cmd = run.calls[0]
        self.assertEqual(cmd[:2], ["schtasks", "/Create"])
        self.assertIn("SUN", cmd)
        self.assertNotIn("/RU", cmd)  # no "run as" another account, no admin rights
        self.assertEqual((cfg["hour"], cfg["purge_days"]), (23, 365))

    def test_windows_failure_is_reported(self):
        with mock.patch.object(paths, "IS_WINDOWS", True), mock.patch.object(paths, "IS_MAC", False), \
                mock.patch.object(scheduler, "_run", FakeRun(rc=1, err="Access is denied")):
            with self.assertRaises(RuntimeError):
                scheduler.save({"enabled": True})

    def test_bad_frequency_refused(self):
        with self.assertRaises(ValueError):
            scheduler.save({"enabled": True, "frequency": "hourly"})

    def test_mac_launch_agent(self):
        home = Path(tempfile.mkdtemp(dir=TMP))
        run = FakeRun()
        with mock.patch.object(paths, "IS_WINDOWS", False), mock.patch.object(paths, "IS_MAC", True), \
                mock.patch.object(scheduler, "_run", run), mock.patch.object(scheduler.Path, "home", return_value=home), \
                mock.patch.object(scheduler.os, "getuid", create=True, return_value=501), \
                mock.patch.object(scheduler, "health", return_value={"ok": True}):
            scheduler.save({"enabled": True, "frequency": "monthly", "hour": 9})
            plist = scheduler._plist_path()
            self.assertTrue(plist.exists())
            self.assertEqual(scheduler._registered_command(), __import__("subprocess").list2cmdline(scheduler._command()))
            self.assertTrue(scheduler.is_registered())
            scheduler.save({"enabled": False})
            self.assertFalse(plist.exists())
        self.assertIn(["launchctl", "bootstrap", "gui/501", str(plist)], run.calls)

    def test_windows_registered_command_is_read_from_xml(self):
        xml = "<Task><Actions><Exec><Command>\"C:\\A &amp; B\\PCCleaner.exe\"</Command>" \
              "<Arguments>--auto-clean</Arguments></Exec></Actions></Task>"
        with mock.patch.object(paths, "IS_WINDOWS", True), mock.patch.object(scheduler, "_run", FakeRun(out=xml)):
            self.assertEqual(scheduler._registered_command(), '"C:\\A & B\\PCCleaner.exe" --auto-clean')

    def test_auto_clean_purges_only_old_batches(self):
        f = self.root / "old.bin"
        f.write_bytes(b"o" * 10)
        res = quarantine.quarantine([str(f)], "test")
        db.set_setting("schedule", __import__("json").dumps(dict(scheduler.DEFAULTS, junk=False, purge_days=1)))
        self.assertEqual(scheduler.run_auto_clean()["purged_bytes"], 0)  # too recent
        conn = db.connect()
        conn.execute("UPDATE actions SET ts=ts-? WHERE batch_id=?", (2 * 86400, res["batch_id"]))
        conn.commit()
        self.assertEqual(scheduler.run_auto_clean()["purged_bytes"], 10)
        scheduler.record_skipped("app open")
        self.assertEqual(scheduler.get()["last_run"]["skipped"], "app open")


class StartupRecordTest(Base):
    def setUp(self):
        super().setUp()
        self.items = [{"id": "x1", "kind": "run", "name": "Spotify", "enabled": True, "label": "safe", "command": "s.exe"}]
        self.fail_next = False

        def set_enabled(item, on):
            if self.fail_next:
                raise PermissionError("denied")
            next(i for i in self.items if i["id"] == item["id"])["enabled"] = on

        self.saved = list(startup_base.PROVIDERS)
        startup_base.PROVIDERS[:] = []
        startup_base.register_provider(startup_base.Provider("fake", {"run"}, lambda: [dict(i) for i in self.items], set_enabled))

    def tearDown(self):
        startup_base.PROVIDERS[:] = self.saved

    def test_disable_records_first_and_enable_closes(self):
        startup.set_enabled("x1", False)
        self.assertEqual(startup_base._change("x1")["command"], "s.exe")
        self.assertTrue(startup.list_items()[0]["changed_by_app"])
        self.assertEqual(startup.set_enabled("x1", False), {"ok": True, "unchanged": True})
        startup.set_enabled("x1", True)
        self.assertIsNone(startup_base._change("x1"))
        self.assertEqual(len(startup_base.history()), 1)

    def test_failed_disable_leaves_no_record(self):
        self.fail_next = True
        with self.assertRaises(PermissionError):
            startup.set_enabled("x1", False)
        self.assertIsNone(startup_base._change("x1"))

    def test_unknown_item_refused(self):
        with self.assertRaises(KeyError):
            startup.set_enabled("nope", False)

    def test_labels(self):
        self.assertEqual(startup_base.classify("Windows Defender")[0], "keep")
        self.assertEqual(startup_base.classify("Zalo")[0], "safe")
        self.assertEqual(startup_base.classify("xyz")[0], "unknown")


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
