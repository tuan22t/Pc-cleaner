import os
import tempfile
import shutil
import unittest
from pathlib import Path

# The system temp dir lives under protected folders on Windows (AppData) and
# macOS (/private/var), so test files go in a folder next to the tests.
_BASE = Path(__file__).resolve().parent / "_tmp"
_BASE.mkdir(exist_ok=True)
TMP = tempfile.mkdtemp(dir=_BASE)
os.environ["PCCLEANER_DATA_DIR"] = os.path.join(TMP, "data")
os.environ.setdefault("PCCLEANER_LANG", "vi")  # messages are checked in Vietnamese

from pccleaner import db, duplicates, paths, quarantine, scanner  # noqa: E402


class CoreTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(dir=TMP))
        db.reset_for_tests(Path(tempfile.mkdtemp(dir=TMP)) / "t.sqlite3")
        data = os.urandom(300_000)
        (self.root / "a" / "b").mkdir(parents=True)
        (self.root / "c").mkdir()
        (self.root / "a" / "one.bin").write_bytes(data)
        (self.root / "a" / "b" / "two.bin").write_bytes(data)
        (self.root / "c" / "three.bin").write_bytes(data)
        # Same size and same head/tail but different middle: must NOT be a duplicate.
        tricky = bytearray(data)
        tricky[150_000] ^= 0xFF
        (self.root / "c" / "tricky.bin").write_bytes(bytes(tricky))
        (self.root / "c" / "small.txt").write_text("hello")

    def test_scan_sizes_roll_up(self):
        sid = scanner.scan(str(self.root))
        s = scanner.get_scan(sid)
        self.assertEqual(s["file_count"], 5)
        self.assertEqual(s["total_size"], 4 * 300_000 + 5)
        kids = {i["name"]: i["size"] for i in scanner.children(sid)["items"]}
        self.assertEqual(kids["a"], 600_000)
        self.assertEqual(kids["c"], 600_005)
        self.assertEqual(scanner.large_files(sid, limit=1)[0]["size"], 300_000)

    def test_duplicates_exact_only(self):
        sid = scanner.scan(str(self.root))
        n = duplicates.find_duplicates(sid, min_size=1000)
        self.assertEqual(n, 1)
        g = duplicates.get_groups(sid)["groups"][0]
        names = sorted(Path(f["path"]).name for f in g["files"])
        self.assertEqual(names, ["one.bin", "three.bin", "two.bin"])
        # Second run uses the hash cache and gives the same answer.
        self.assertEqual(duplicates.find_duplicates(sid, min_size=1000), 1)

    def test_quarantine_and_restore(self):
        target = self.root / "c" / "three.bin"
        r = quarantine.quarantine([str(target)], "test")
        self.assertEqual(r["moved"], 1)
        self.assertFalse(target.exists())
        back = quarantine.restore(r["batch_id"])
        self.assertEqual(back["restored"], 1)
        self.assertTrue(target.exists())
        kinds = [a["kind"] for a in quarantine.log()]
        self.assertIn("quarantine", kinds)
        self.assertIn("restore", kinds)

    def test_protected_paths_refused(self):
        sysfile = "C:\\Windows\\notepad.exe" if paths.IS_WINDOWS else "/usr/bin/env"
        self.assertTrue(paths.is_protected(sysfile))
        r = quarantine.quarantine([sysfile], "test")
        self.assertEqual(r["moved"], 0)
        self.assertEqual(len(r["failed"]), 1)
        self.assertTrue(os.path.exists(sysfile))

    def test_purge(self):
        target = self.root / "a" / "one.bin"
        r = quarantine.quarantine([str(target)], "test")
        self.assertEqual(quarantine.purge_batch(r["batch_id"])["freed"], 300_000)
        self.assertEqual(quarantine.restore(r["batch_id"])["restored"], 0)

    def test_symlink_into_system_folder_refused(self):
        if paths.IS_WINDOWS:
            self.skipTest("symlinks need admin rights on Windows")
        link = self.root / "sneaky"
        os.symlink("/usr/bin", link)
        target = link / "env"
        self.assertTrue(paths.is_protected(target))
        r = quarantine.quarantine([str(target)], "test")
        self.assertEqual(r["moved"], 0)
        self.assertTrue(os.path.exists("/usr/bin/env"))

    def test_duplicate_removal_keeps_one_copy(self):
        sid = scanner.scan(str(self.root))
        duplicates.find_duplicates(sid, min_size=1000)
        files = [f["path"] for f in duplicates.get_groups(sid)["groups"][0]["files"]]
        # Asking to remove every copy must leave at least one behind.
        allowed, refused = duplicates.check_removal(sid, files)
        self.assertEqual(len(allowed), 2)
        self.assertEqual(len(refused), 1)
        self.assertTrue(os.path.exists(refused[0]["path"]))

    def test_duplicate_changed_since_scan_refused(self):
        sid = scanner.scan(str(self.root))
        duplicates.find_duplicates(sid, min_size=1000)
        files = [f["path"] for f in duplicates.get_groups(sid)["groups"][0]["files"]]
        Path(files[1]).write_bytes(b"changed" * 1000)
        allowed, refused = duplicates.check_removal(sid, [files[1]])
        self.assertEqual(allowed, [])
        self.assertIn("thay đổi", refused[0]["error"])

    def test_restore_does_not_overwrite(self):
        target = self.root / "c" / "three.bin"
        r = quarantine.quarantine([str(target)], "test")
        target.write_bytes(b"new file in the same place")
        back = quarantine.restore(r["batch_id"])
        self.assertEqual(target.read_bytes(), b"new file in the same place")
        self.assertEqual(back["restored"], 1)  # the old copy comes back under a new name
        self.assertTrue(Path(back["renamed"][0]["restored_as"]).exists())

    def test_scan_cancel_leaves_nothing(self):
        import threading
        ev = threading.Event()
        ev.set()
        with self.assertRaises(scanner.Cancelled):
            scanner.scan(str(self.root), cancel=ev)
        self.assertEqual(scanner.latest_scans(), [])

    def test_scan_skips_links_and_junctions(self):
        loop = self.root / "a" / "loop"
        if paths.IS_WINDOWS:
            import subprocess
            subprocess.run(["cmd", "/c", "mklink", "/J", str(loop), str(self.root)], check=True, capture_output=True)
        else:
            os.symlink(self.root, loop)
        sid = scanner.scan(str(self.root))
        self.assertEqual(scanner.get_scan(sid)["file_count"], 5)
        # The link itself must never be offered for removal through its target.
        self.assertTrue(os.path.isdir(loop))

    def test_keep_suggestion_prefers_original(self):
        fs = [
            {"path": os.path.join("u", "Downloads", "IMG_1 (1).jpg"), "mtime": 1, "exists": True},
            {"path": os.path.join("u", "Desktop", "IMG_1 - Copy.jpg"), "mtime": 0, "exists": True},
            {"path": os.path.join("u", "Pictures", "IMG_1.jpg"), "mtime": 2, "exists": True},
        ]
        self.assertTrue(sorted(fs, key=duplicates._keep_rank)[0]["path"].endswith("IMG_1.jpg"))


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
