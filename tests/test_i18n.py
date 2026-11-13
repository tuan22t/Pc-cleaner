"""Translations: every text has an English entry, nothing is hard-coded, and the
back end answers in the chosen language. Also the Dashboard figures."""
import json
import os
import re
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

_BASE = Path(__file__).resolve().parent / "_tmp"
_BASE.mkdir(exist_ok=True)
TMP = tempfile.mkdtemp(dir=_BASE)
os.environ.setdefault("PCCLEANER_DATA_DIR", os.path.join(TMP, "data"))
os.environ.setdefault("PCCLEANER_LANG", "vi")  # messages are checked in Vietnamese

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import i18n_keys  # noqa: E402

from pccleaner import APP_NAME, dashboard, db, i18n, organizer, quarantine, server  # noqa: E402
from pccleaner.i18n import _  # noqa: E402

EN = json.loads((Path(i18n.__file__).parent / "web" / "i18n" / "en.json").read_text(encoding="utf-8"))


class KeysTest(unittest.TestCase):
    def test_every_text_has_english(self):
        self.assertEqual(i18n_keys.missing("en"), [])

    def test_no_untranslatable_text(self):
        self.assertEqual(i18n_keys.fstring_texts(), [], "Vietnamese f-strings cannot be translated: use _('… {0}', x)")
        self.assertEqual(i18n_keys.js_hardcoded(), [], "UI text must go through t()")

    def test_placeholders_match(self):
        ph = re.compile(r"\{(\d+)")
        for k, v in EN.items():
            self.assertEqual(set(ph.findall(k)), set(ph.findall(v)), k)

    def test_english_has_no_vietnamese(self):
        vi = re.compile(r"[À-ÖØ-öø-ỹđĐ]")
        bad = [v for v in EN.values() if vi.search(v.replace("Cốc Cốc", ""))]
        self.assertEqual(bad, [])

    def test_html_keys_found(self):
        keys = i18n_keys.html_keys()
        self.assertIn("Tổng quan", keys)
        self.assertIn("Khu cách ly &amp; hoàn tác", keys)  # innerHTML keeps entities escaped

    def test_app_name_in_one_place(self):
        root = Path(i18n.__file__).parent
        hits = [p.name for p in root.rglob("*.py") if APP_NAME in p.read_text(encoding="utf-8")]
        self.assertEqual(hits, ["__init__.py"])


class BackendLanguageTest(unittest.TestCase):
    def setUp(self):
        db.reset_for_tests(Path(tempfile.mkdtemp(dir=TMP)) / "t.sqlite3")

    def tearDown(self):
        i18n.reset()

    def test_default_follows_env(self):
        self.assertEqual(i18n.lang(), "vi")
        self.assertEqual(_("Thư mục không tồn tại: {0}", "X"), "Thư mục không tồn tại: X")

    def test_switch_to_english(self):
        server._save_settings({"lang": "en"})
        self.assertEqual(i18n.lang(), "en")
        self.assertEqual(_("Thư mục không tồn tại: {0}", "X"), "Folder does not exist: X")
        with self.assertRaises(FileNotFoundError) as e:
            organizer.preview(os.path.join(TMP, "missing"))
        self.assertIn("Folder does not exist", str(e.exception))
        i18n.reset()  # read back from the database, as after a restart
        self.assertEqual(i18n.lang(), "en")

    def test_plural_and_fallback(self):
        server._save_settings({"lang": "en"})
        self.assertEqual(_("{0} ngày trước", 1), "1 day ago")
        self.assertEqual(_("{0} ngày trước", 3), "3 days ago")
        self.assertEqual(_("Chưa có bản dịch {0}", 5), "Chưa có bản dịch 5")  # missing: Vietnamese, never blank
        self.assertEqual(_("{0} và {1}", "a"), "{0} và {1}".replace("{0}", "a"))

    def test_bad_settings_refused(self):
        with self.assertRaises(ValueError):
            server._save_settings({"lang": "fr"})
        with self.assertRaises(ValueError):
            server._save_settings({"theme": "pink"})
        s = server._save_settings({"theme": "dark", "onboarded": True})
        self.assertEqual((s["theme"], s["onboarded"]), ("dark", True))

    def test_restored_name_in_english(self):
        server._save_settings({"lang": "en"})
        d = Path(tempfile.mkdtemp(dir=TMP))
        f = d / "a.txt"
        f.write_text("old")
        r = quarantine.quarantine([str(f)], "test")
        f.write_text("new")
        back = quarantine.restore(r["batch_id"])
        self.assertEqual(len(back["renamed"]), 1)
        self.assertTrue((d / "a (restored).txt").exists())


class DashboardTest(unittest.TestCase):
    def setUp(self):
        db.reset_for_tests(Path(tempfile.mkdtemp(dir=TMP)) / "t.sqlite3")

    def test_summary_and_history(self):
        s = dashboard.summary()
        self.assertTrue(s["locations"])
        self.assertEqual([c["group"] for c in s["cleanable"]], ["quarantine"])
        self.assertIsNone(s["startup"])
        self.assertIsNone(s["last_cleanup"])
        hist = dashboard.history()
        self.assertTrue(all(len(v) == 1 for v in hist.values()))  # one reading today
        dashboard.record_disks()  # same day: replaced, not added
        self.assertEqual(dashboard.history(), {k: [dict(v[0], used=v[0]["used"])] for k, v in dashboard.history().items()})
        self.assertTrue(all(len(v) == 1 for v in dashboard.history().values()))

    def test_old_history_pruned(self):
        conn = db.connect()
        conn.execute("INSERT INTO disk_history VALUES ('X', '2000-01-01', 0, 10, 5)")
        conn.commit()
        dashboard.record_disks([{"path": "Y", "total": 10, "used": 1}])
        days = [r[0] for r in conn.execute("SELECT day FROM disk_history")]
        self.assertNotIn("2000-01-01", days)

    def test_cached_checks_and_last_cleanup(self):
        dashboard.remember("last_junk", {"bytes": 500, "files": 3})
        dashboard.remember("last_startup", {"total": 5, "enabled": 4, "can_disable": 2})
        d = Path(tempfile.mkdtemp(dir=TMP))
        (d / "x.bin").write_bytes(b"1234")
        quarantine.quarantine([str(d / "x.bin")], "File lớn")
        s = dashboard.summary()
        junk = next(c for c in s["cleanable"] if c["group"] == "junk")
        self.assertEqual((junk["bytes"], junk["files"]), (500, 3))
        self.assertEqual(s["startup"]["can_disable"], 2)
        self.assertEqual((s["last_cleanup"]["bytes"], s["last_cleanup"]["reason"]), (4, "File lớn"))
        self.assertEqual(next(c for c in s["cleanable"] if c["group"] == "quarantine")["bytes"], 4)

    def test_duplicate_waste(self):
        conn = db.connect()
        conn.execute("INSERT INTO scans(id, root, started, finished, status) VALUES (7, '/r', 1, ?, 'done')", (time.time(),))
        rows = [(7, 1, "h", 100, "/r/a", 0), (7, 1, "h", 100, "/r/b", 0), (7, 1, "h", 100, "/r/c", 0),
                (7, 2, "g", 50, "/r/d", 0), (7, 2, "g", 50, "/r/e", 0)]
        conn.executemany("INSERT INTO dup_groups VALUES (?,?,?,?,?,?)", rows)
        conn.commit()
        w = dashboard.duplicate_waste()
        self.assertEqual((w["bytes"], w["files"], w["root"]), (250, 3, "/r"))


class MigrationRaceTest(unittest.TestCase):
    def test_fresh_database_opened_by_many_threads(self):
        """The window, a background job and a scheduled run may open a new database at once."""
        import sqlite3
        import threading

        for _round in range(5):
            path = Path(tempfile.mkdtemp(dir=TMP)) / "race.sqlite3"
            db.reset_for_tests(path)
            errors, start = [], threading.Event()

            def open_it():
                start.wait()
                try:
                    db.connect()
                except Exception as e:  # noqa: BLE001
                    errors.append(e)

            threads = [threading.Thread(target=open_it) for _ in range(8)]
            for t in threads:
                t.start()
            start.set()
            for t in threads:
                t.join()
            self.assertEqual(errors, [])
            v = sqlite3.connect(path).execute("PRAGMA user_version").fetchone()[0]
            self.assertEqual(v, db.SCHEMA_VERSION)

    def test_newer_database_refused_and_untouched(self):
        import sqlite3

        path = Path(tempfile.mkdtemp(dir=TMP)) / "new.sqlite3"
        c = sqlite3.connect(path)
        c.execute(f"PRAGMA user_version={db.SCHEMA_VERSION + 1}")
        c.commit()
        c.close()
        db.reset_for_tests(path)
        with self.assertRaises(db.NewerDatabaseError):
            db.connect()
        self.assertEqual(sqlite3.connect(path).execute("PRAGMA user_version").fetchone()[0], db.SCHEMA_VERSION + 1)


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
