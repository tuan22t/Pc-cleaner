"""The local API, end to end: the UI's real calls against a running server.

Only test folders inside tests/_tmp are scanned or cleaned. The system-junk
cleaner and the scheduled run are never started here (they act on the real
user folders of the machine running the tests).
"""
import http.client
import json
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path

_BASE = Path(__file__).resolve().parent / "_tmp"
_BASE.mkdir(exist_ok=True)
TMP = tempfile.mkdtemp(dir=_BASE)
os.environ.setdefault("PCCLEANER_DATA_DIR", os.path.join(TMP, "data"))

from pccleaner import db, server  # noqa: E402


class ApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd, _url, cls.token = server.start_server(0)
        cls.port = cls.httpd.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def setUp(self):
        db.reset_for_tests(Path(tempfile.mkdtemp(dir=TMP)) / "t.sqlite3")
        self.root = Path(tempfile.mkdtemp(dir=TMP))
        (self.root / "a").mkdir()
        (self.root / "b").mkdir()
        payload = os.urandom(300_000)
        (self.root / "a" / "movie.mp4").write_bytes(payload)
        (self.root / "b" / "movie copy.mp4").write_bytes(payload)
        (self.root / "b" / "notes.txt").write_text("hello")
        (self.root / "a" / "photo.jpg").write_bytes(b"\xff\xd8 not really a jpeg")

    def call(self, method, path, body=None, status=200):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        data = json.dumps(body).encode() if body is not None else None
        headers = {"X-Token": self.token}
        if data is not None:
            headers["Content-Type"] = "application/json"
        c.request(method, "/api/" + path, body=data, headers=headers)
        r = c.getresponse()
        out = json.loads(r.read() or b"null")
        c.close()
        self.assertEqual(r.status, status, out)
        return out

    def wait(self):
        for _ in range(600):
            st = self.call("GET", "job")
            if st["state"] != "running":
                self.assertEqual(st["state"], "done", st)
                return st.get("result")
            time.sleep(0.02)
        self.fail("job did not finish")

    def scan(self):
        self.call("POST", "scan", {"path": str(self.root), "full": True})
        sid = self.wait()
        self.assertIsInstance(sid, int)
        return sid

    def test_info_and_scan_reports(self):
        info = self.call("GET", "info")
        self.assertIn("version", info)
        sid = self.scan()
        self.assertTrue(any(s["id"] == sid for s in self.call("GET", "scans")))
        summary = self.call("GET", f"scan/{sid}/summary")
        self.assertEqual(summary["scan"]["file_count"], 4)
        kids = self.call("GET", f"scan/{sid}/children?dir=0")
        self.assertEqual({i["name"] for i in kids["items"] if i.get("type", "dir") == "dir"} & {"a", "b"}, {"a", "b"})
        large = self.call("GET", f"scan/{sid}/large?limit=10")
        self.assertEqual(large[0]["size"], 300_000)
        self.assertEqual(len(self.call("GET", f"scan/{sid}/old?days=0&min=1")), 4)
        self.call("GET", "scan/999999/summary", status=404)

    def test_duplicates_clean_and_undo(self):
        sid = self.scan()
        self.call("POST", "duplicates", {"scan_id": sid, "min_size": 1000})
        self.wait()
        groups = self.call("GET", f"scan/{sid}/duplicates")["groups"]
        self.assertEqual(len(groups), 1)
        victim = str(self.root / "b" / "movie copy.mp4")
        self.call("POST", "quarantine", {"paths": [victim], "reason": "dup", "dup_scan_id": sid})
        r = self.wait()
        self.assertEqual(r["moved"], 1)
        self.assertFalse(os.path.exists(victim))
        self.assertTrue(any(b["batch_id"] == r["batch_id"] for b in self.call("GET", "batches")))
        self.assertTrue(self.call("GET", "log"))
        self.call("POST", "restore", {"batch_ids": [r["batch_id"]]})
        back = self.wait()
        self.assertEqual(back["restored"], 1)
        self.assertTrue(os.path.exists(victim))

    def test_duplicate_changed_after_scan_is_refused(self):
        sid = self.scan()
        self.call("POST", "duplicates", {"scan_id": sid, "min_size": 1000})
        self.wait()
        victim = self.root / "b" / "movie copy.mp4"
        victim.write_bytes(os.urandom(300_000))
        self.call("POST", "quarantine", {"paths": [str(victim)], "dup_scan_id": sid})
        r = self.wait()
        self.assertEqual(r["moved"], 0)
        self.assertTrue(victim.exists())

    def test_purge_after_quarantine(self):
        f = self.root / "b" / "notes.txt"
        self.call("POST", "quarantine", {"paths": [str(f)], "reason": "test"})
        r = self.wait()
        self.call("POST", "purge", {"batch_id": r["batch_id"]})
        self.wait()
        self.assertFalse(f.exists())
        self.assertFalse(any(b["batch_id"] == r["batch_id"] and b.get("pending") for b in self.call("GET", "batches")))

    def test_organize_preview_apply_undo(self):
        folder = self.root / "a"
        plan = self.call("POST", "organize-preview", {"folder": str(folder)})
        chosen = [m["src"] for m in plan["moves"]]
        self.assertTrue(chosen)
        self.call("POST", "organize-apply", {"folder": str(folder), "chosen": chosen})
        r = self.wait()
        self.assertEqual(r["moved"], len(chosen))
        self.call("POST", "restore", {"batch_id": r["batch_id"]})
        self.wait()
        self.assertTrue((folder / "movie.mp4").exists())

    def test_bad_requests(self):
        self.call("POST", "quarantine", {"paths": []}, status=400)
        self.call("POST", "junk-clean", {"ids": []}, status=400)
        self.call("POST", "scan", {"path": str(self.root / "missing")}, status=400)
        self.call("POST", "organize-preview", {"folder": str(Path.home().anchor)}, status=400)

    def test_cancel_and_one_job_at_a_time(self):
        self.call("POST", "scan", {"path": str(self.root)})
        self.call("POST", "scan", {"path": str(self.root)}, status=400)  # a job is already running
        self.call("POST", "cancel", {})
        for _ in range(500):
            if self.call("GET", "job")["state"] != "running":
                break
            time.sleep(0.02)
        self.assertIn(self.call("GET", "job")["state"], ("done", "cancelled"))

    def test_settings_screens_load(self):
        sched = self.call("GET", "schedule")
        self.assertIn("health", sched)
        self.assertIn("items", self.call("GET", "startup"))
        self.assertIsInstance(self.call("GET", "startup-history"), list)


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
