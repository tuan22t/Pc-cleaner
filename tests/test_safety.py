"""Phase A acceptance tests: crash safety, per-drive quarantine, protected packages,
cloud folders, schema versions, single instance, server hardening.

Everything runs inside tests/_tmp; no real user data is touched.
"""
import errno
import http.client
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

_BASE = Path(__file__).resolve().parent / "_tmp"
_BASE.mkdir(exist_ok=True)
TMP = tempfile.mkdtemp(dir=_BASE)
os.environ.setdefault("PCCLEANER_DATA_DIR", os.path.join(TMP, "data"))

from pccleaner import db, organizer, paths, quarantine, scanner, server, startup  # noqa: E402

CHILD = str(Path(__file__).resolve().parent / "_crash_child.py")
N = 5


class Base(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(dir=TMP))
        self.dbfile = Path(tempfile.mkdtemp(dir=TMP)) / "t.sqlite3"
        db.reset_for_tests(self.dbfile)

    def make_files(self, n=N, sub="files"):
        d = self.root / sub
        d.mkdir(parents=True, exist_ok=True)
        files = {}
        for i in range(n):
            p = d / f"f{i}.txt"
            p.write_bytes(f"content {i} ".encode() * (i + 1))
            files[str(p)] = p.read_bytes()
        return files

    def child(self, op, args, point, nth, chunk=None):
        cfg = {"db": str(self.dbfile), "op": op, "args": args, "point": point, "nth": nth}
        if chunk:
            cfg["chunk"] = chunk
        r = subprocess.run([sys.executable, CHILD, json.dumps(cfg)], capture_output=True, text=True, timeout=60)
        if r.returncode not in (0, 9):
            self.fail(r.stderr)
        db.reset_for_tests(self.dbfile)  # fresh connection, like a new app start
        return r.returncode

    def assert_all_back(self, files):
        for p, data in files.items():
            self.assertTrue(os.path.exists(p), f"missing after undo: {p}")
            self.assertEqual(Path(p).read_bytes(), data)

    def pending_rows(self):
        return db.connect().execute(
            "SELECT COUNT(*) AS n FROM actions WHERE kind LIKE 'pending-%'"
        ).fetchone()["n"]

    def undo_everything(self):
        for b in quarantine.batches():
            quarantine.restore(b["batch_id"])


class CrashDuringCleanupTest(Base):
    """Kill the process at every step of a cleanup; nothing may be lost or unlogged."""

    POINTS = [("after_journal", 1), ("before_move", 1), ("before_move", 3), ("after_move", 1),
              ("after_move", 3), ("after_move", N), ("after_commit", 1)]

    def test_kill_at_every_point(self):
        for chunk in (None, 2):  # one journal transaction, or several
            for point, nth in self.POINTS:
                with self.subTest(point=point, nth=nth, chunk=chunk):
                    self.setUp()
                    files = self.make_files()
                    code = self.child("quarantine", list(files), point, nth, chunk)
                    if point != "after_commit" or chunk:
                        self.assertEqual(code, 9, "fault point not reached")
                    quarantine.recover()
                    self.assertEqual(self.pending_rows(), 0)
                    # Every file is either untouched or listed as restorable.
                    rows = db.connect().execute("SELECT path, stored_at FROM actions WHERE kind='quarantine'").fetchall()
                    logged = {r["path"]: r["stored_at"] for r in rows}
                    for p in files:
                        self.assertTrue(os.path.exists(p) or (p in logged and os.path.exists(logged[p])), p)
                    self.undo_everything()
                    self.assert_all_back(files)

    def test_recover_is_idempotent(self):
        files = self.make_files()
        self.child("quarantine", list(files), "after_move", 2)
        first = quarantine.recover()
        self.assertEqual(first["finished"], 2)
        self.assertEqual(first["aborted"], N - 2)
        self.assertEqual(quarantine.recover(), {"finished": 0, "aborted": 0, "missing": 0})


class CrashDuringOrganizeTest(Base):
    def test_kill_while_sorting_folder(self):
        for point, nth in [("before_move", 2), ("after_move", 2), ("after_commit", 1)]:
            with self.subTest(point=point, nth=nth):
                self.setUp()
                d = self.root / "Downloads"
                d.mkdir()
                files = {}
                for name in ("a.jpg", "b.pdf", "c.zip", "d.mp3"):
                    (d / name).write_bytes(name.encode())
                    files[str(d / name)] = name.encode()
                plan = organizer.preview(str(d), by_year=False)
                moves = [[m["src"], m["dest"]] for m in plan["moves"]]
                self.child("move", moves, point, nth)
                quarantine.recover()
                self.undo_everything()
                self.assert_all_back(files)
                self.assertEqual(sorted(os.listdir(d)), sorted(n for n in ("a.jpg", "b.pdf", "c.zip", "d.mp3")))


class CrashDuringUndoTest(Base):
    def test_kill_while_restoring(self):
        files = self.make_files()
        r = quarantine.quarantine(list(files), "t")
        self.assertEqual(r["moved"], N)
        self.child("restore", [r["batch_id"]], "restore_after_move", 2)
        back = quarantine.restore(r["batch_id"])  # the user presses Undo again
        self.assertEqual(back["failed"], [])
        self.assert_all_back(files)

    def test_kill_while_purging(self):
        files = self.make_files()
        r = quarantine.quarantine(list(files), "t")
        self.child("purge", [r["batch_id"]], "purge_after_remove", 2)
        quarantine.purge_batch(r["batch_id"])
        rows = db.connect().execute(
            "SELECT COUNT(*) AS n FROM actions WHERE batch_id=? AND kind='quarantine' AND restored=0", (r["batch_id"],)
        ).fetchone()["n"]
        self.assertEqual(rows, 0)
        self.assertFalse(any(os.path.exists(p) for p in files))  # purge = gone for good, as intended


class OtherDriveTest(Base):
    def test_other_drive_uses_its_own_quarantine(self):
        files = self.make_files(2)
        vol = self.root / "vol"
        vol.mkdir()
        home_dev = os.stat(paths.quarantine_dir()).st_dev
        with mock.patch.object(paths, "_device", lambda p: home_dev + 1 if str(self.root) in str(p) else home_dev), \
             mock.patch.object(paths, "volume_root", lambda p: str(vol)):
            r = quarantine.quarantine(list(files), "t")
        self.assertEqual(r["moved"], 2)
        stored = [x["stored_at"] for x in db.connect().execute("SELECT stored_at FROM actions WHERE kind='quarantine'")]
        for s in stored:
            self.assertTrue(s.startswith(str(vol / paths.VOLUME_QUARANTINE)), s)
        self.assertEqual(list((paths.quarantine_dir() / r["batch_id"]).rglob("*")), [])  # nothing on the system drive
        quarantine.restore(r["batch_id"])
        self.assert_all_back(files)

    def test_never_copies_between_drives(self):
        files = self.make_files(2)

        def cross(src, dst):
            raise OSError(errno.EXDEV, "cross-device")

        with mock.patch.object(quarantine, "_rename", cross):
            r = quarantine.quarantine(list(files), "t")
        self.assertEqual(r["moved"], 0)
        self.assertIn("hai ổ đĩa", r["failed"][0]["error"])
        self.assertEqual(self.pending_rows(), 0)
        self.assert_all_back(files)
        self.assertEqual(list((paths.quarantine_dir() / r["batch_id"]).rglob("*.txt")), [])

    def test_scanner_skips_drive_quarantine(self):
        (self.root / paths.VOLUME_QUARANTINE / "b" / "0").mkdir(parents=True)
        (self.root / paths.VOLUME_QUARANTINE / "b" / "0" / "x.bin").write_bytes(b"1" * 100)
        (self.root / "y.bin").write_bytes(b"2" * 10)
        sid = scanner.scan(str(self.root))
        self.assertEqual(scanner.get_scan(sid)["file_count"], 1)


class ProtectedPackagesTest(Base):
    CASES = [
        ("Pictures/Photos Library.photoslibrary/originals/A/IMG_1.jpg", "Photos"),
        ("Code/project/.git/objects/ab/cdef", "git"),
        ("Downloads/Tool.app/Contents/Resources/icon.png", "ứng dụng"),
        ("Code/web/node_modules/lib/index.js", "lập trình"),
        ("Movies/iMovie Library.imovielibrary/clip.mov", "iMovie"),
        ("Games/SteamLibrary/steamapps/common/x.pak", "Steam"),
    ]

    def test_files_inside_packages_are_refused(self):
        for rel, word in self.CASES:
            with self.subTest(rel=rel):
                p = self.root / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(b"data")
                self.assertIn(word, paths.protection_reason(p) or "")
                r = quarantine.quarantine([str(p)], "t")
                self.assertEqual(r["moved"], 0)
                self.assertTrue(p.exists())

    @unittest.skipIf(paths.IS_WINDOWS, "symlinks need admin rights on Windows")
    def test_link_into_package_is_refused(self):
        inner = self.root / "Lib.photoslibrary" / "originals" / "x.jpg"
        inner.parent.mkdir(parents=True)
        inner.write_bytes(b"photo")
        link_dir = self.root / "innocent"
        os.symlink(inner.parent, link_dir)
        r = quarantine.quarantine([str(link_dir / "x.jpg")], "t")
        self.assertEqual(r["moved"], 0)
        self.assertTrue(inner.exists())

    def test_ordinary_files_still_allowed(self):
        p = self.root / "Pictures" / "holiday.jpg"
        p.parent.mkdir(parents=True)
        p.write_bytes(b"x")
        self.assertIsNone(paths.protection_reason(p))
        self.assertEqual(quarantine.quarantine([str(p)], "t")["moved"], 1)


class CloudFolderTest(Base):
    def test_cloud_files_need_explicit_confirmation(self):
        cloud = self.root / "OneDrive - Company"
        cloud.mkdir()
        f = cloud / "report.docx"
        f.write_bytes(b"doc")
        paths._cloud_cache = None
        with mock.patch.dict(os.environ, {"OneDrive": str(cloud)}):
            self.assertEqual(paths.cloud_name(f), "OneDrive")
            self.assertEqual(paths.file_flags(f)["cloud"], "OneDrive")
            r = quarantine.quarantine([str(f)], "t", allow_cloud=False)
            self.assertEqual(r["moved"], 0)
            self.assertIn("OneDrive", r["failed"][0]["error"])
            r = quarantine.quarantine([str(f)], "t", allow_cloud=True)
            self.assertEqual(r["moved"], 1)
        paths._cloud_cache = None


class SchemaVersionTest(Base):
    def test_old_database_is_upgraded(self):
        old = Path(tempfile.mkdtemp(dir=TMP)) / "old.sqlite3"
        c = sqlite3.connect(old)
        c.executescript(db.MIGRATIONS[0])  # a database from before versioning (user_version 0)
        c.execute("INSERT INTO actions(batch_id, ts, kind, path) VALUES ('b', 1, 'quarantine', '/x')")
        c.commit()
        c.close()
        db.reset_for_tests(old)
        conn = db.connect()
        self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], db.SCHEMA_VERSION)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM actions").fetchone()[0], 1)  # data kept

    def test_newer_database_is_not_touched(self):
        newer = Path(tempfile.mkdtemp(dir=TMP)) / "new.sqlite3"
        c = sqlite3.connect(newer)
        c.execute("PRAGMA user_version=99")
        c.commit()
        c.close()
        db.reset_for_tests(newer)
        with self.assertRaises(db.NewerDatabaseError):
            db.connect()


class StartupTasksTest(Base):
    def test_unfinished_scans_are_removed(self):
        conn = db.connect()
        conn.execute("INSERT INTO scans(root, started, status) VALUES ('/x', 1, 'running')")
        conn.commit()
        self.assertEqual(scanner.cleanup_unfinished(), 1)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM scans").fetchone()[0], 0)

    def test_single_instance(self):
        code = (
            "import sys,time; sys.path.insert(0, %r); from pccleaner import paths;"
            "print(paths.acquire_instance_lock(), flush=True); time.sleep(30)"
        ) % str(Path(__file__).resolve().parent.parent)
        p = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(p.stdout.readline().strip(), "True")
            self.assertFalse(paths.acquire_instance_lock())
        finally:
            p.kill()
            p.wait()
        deadline = time.time() + 10
        while not paths.acquire_instance_lock() and time.time() < deadline:
            time.sleep(0.2)
        self.assertTrue(paths.acquire_instance_lock())  # freed by the OS when the holder died
        paths.release_instance_lock()


class HardeningTest(Base):
    def test_macos_labels_are_validated(self):
        self.assertTrue(startup._SAFE_LABEL.match("com.example.helper"))
        for bad in ("x; rm -rf /", "a b", "$(id)", "a'b", ""):
            self.assertIsNone(startup._SAFE_LABEL.match(bad))

    def test_server_headers_and_host_check(self):
        httpd, url, token = server.start_server(0)
        try:
            port = httpd.server_address[1]
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
            c.request("GET", "/")
            r = c.getresponse()
            r.read()
            self.assertEqual(r.status, 200)
            self.assertIn("script-src 'self'", r.getheader("Content-Security-Policy"))
            c.request("GET", "/api/info", headers={"Host": "evil.example:%d" % port, "X-Token": token})
            r = c.getresponse()
            r.read()
            self.assertEqual(r.status, 403)
            c.request("GET", "/api/info", headers={"X-Token": "wrong"})
            r = c.getresponse()
            r.read()
            self.assertEqual(r.status, 401)
        finally:
            httpd.shutdown()


def tearDownModule():
    paths.release_instance_lock()
    shutil.rmtree(TMP, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
