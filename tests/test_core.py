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


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
