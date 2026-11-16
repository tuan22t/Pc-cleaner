"""Speed up: health check, heavy apps, closing apps and reversible tweaks.

Real settings of the test machine are only read, never changed: the tweak
tests use stand-in settings kept in memory. The only process closed for real
is one these tests start.
"""
import os
import shutil
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
os.environ.setdefault("PCCLEANER_LANG", "vi")

from pccleaner import db, server, speedup  # noqa: E402
from pccleaner.speedup import Tweak  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        db.reset_for_tests(Path(tempfile.mkdtemp(dir=TMP)) / "t.sqlite3")


class HealthTest(Base):
    """Read-only checks on the real computer."""

    def test_status(self):
        st = speedup.status()
        self.assertGreater(st["mem_total"], 0)
        self.assertTrue(0 <= st["mem_pct"] <= 100)
        self.assertTrue(0 <= st["cpu_pct"] <= 100)
        self.assertGreater(st["uptime"], 0)
        self.assertGreater(st["disk_total"], 0)

    def test_processes_and_own_app_protected(self):
        procs = speedup.processes()
        me = next(p for p in procs if p["pid"] == os.getpid())
        self.assertTrue(me["protected"])
        self.assertGreater(len(procs), 3)
        apps = speedup.heavy_apps(procs=procs)
        self.assertTrue(apps)
        for a in apps:
            self.assertEqual(a["closable"], bool(a["pids"]))
            if not a["closable"]:
                self.assertTrue(a["why"])

    def test_cpu_per_app_from_two_readings(self):
        speedup.processes()
        time.sleep(0.5)
        self.assertTrue(any(p.get("cpu") is not None for p in speedup.processes()))

    def test_tweaks_listed_without_changes(self):
        for item in speedup.tweak_list():
            self.assertIn("on", item)
            self.assertFalse(item["by_app"])

    def test_overview_and_api(self):
        o = server.route("GET", "/api/speed", {}, {})
        self.assertIn("status", o)
        self.assertTrue(o["advice"])
        self.assertIn("apps", o)
        with self.assertRaises(ValueError):
            server.route("POST", "/api/speed-close", {}, {"name": "x", "pids": []})
        with self.assertRaises(KeyError):
            server.route("POST", "/api/speed-tweak", {}, {"id": "nope", "on": True})


class ProtectionTest(Base):
    def proc(self, **kw):
        p = {"pid": 999999, "ppid": 1, "name": "notepad", "path": "", "mem": 1, "mine": True}
        p.update(kw)
        return p

    def test_rules(self):
        osm = speedup._platform()
        self.assertIsNone(speedup.protection(self.proc(), set()))
        self.assertTrue(speedup.protection(self.proc(), {999999}))  # this app or its family
        self.assertTrue(speedup.protection(self.proc(mine=False), set()))  # other users / services
        self.assertTrue(speedup.protection(self.proc(name="kaspersky agent"), set()))
        self.assertTrue(speedup.protection(self.proc(name="unikey"), set()))
        name = sorted(osm.PROTECTED_NAMES)[0]
        self.assertTrue(speedup.protection(self.proc(name=name), set()))
        root = osm.system_roots()[0]
        self.assertTrue(speedup.protection(self.proc(path=os.path.join(root, "x", "tool")), set()))

    def test_family(self):
        procs = [{"pid": 1, "ppid": 0}, {"pid": 10, "ppid": 1}, {"pid": 20, "ppid": 10},
                 {"pid": 21, "ppid": 20}, {"pid": 30, "ppid": 1}]
        self.assertEqual(speedup._family(procs, 20), {1, 10, 20, 21})

    def test_grouping(self):
        procs = [
            {"pid": 1, "name": "chrome", "mem": 300, "cpu": 2.0, "protected": None},
            {"pid": 2, "name": "chrome", "mem": 200, "cpu": None, "protected": None},
            {"pid": 3, "name": "MsMpEng", "mem": 900, "cpu": 1.0, "protected": "Thành phần của hệ điều hành"},
            {"pid": 4, "name": "tiny", "mem": 1, "cpu": 0.0, "protected": None},
        ]
        apps = speedup.heavy_apps(limit=2, procs=procs)
        self.assertEqual([a["name"] for a in apps], ["chrome", "MsMpEng"])  # processor use weighs in
        chrome = apps[0]
        self.assertEqual((chrome["mem"], chrome["cpu"], chrome["count"], sorted(chrome["pids"])), (500, 2.0, 2, [1, 2]))
        self.assertFalse(apps[1]["closable"])
        self.assertEqual(apps[1]["why"], "Thành phần của hệ điều hành")


class CloseTest(Base):
    def test_only_matching_closable_processes(self):
        listing = [
            {"pid": 11, "name": "editor", "protected": None},
            {"pid": 12, "name": "other", "protected": None},              # number reused by another program
            {"pid": 13, "name": "editor", "protected": "Thành phần của hệ điều hành"},
        ]
        osm = speedup._platform()
        with mock.patch.object(speedup, "processes", return_value=listing), \
                mock.patch.object(osm, "terminate") as term, mock.patch.object(osm, "alive", return_value=[]):
            r = speedup.close_app("Editor", [11, 12, 13, 14])
        term.assert_called_once_with([11], False)
        self.assertEqual((r["closed"], r["running"], r["refused"]), (1, 0, 3))

    def test_nothing_to_close(self):
        osm = speedup._platform()
        with mock.patch.object(speedup, "processes", return_value=[]), mock.patch.object(osm, "terminate") as term:
            r = speedup.close_app("x", [5])
        term.assert_not_called()
        self.assertEqual(r["closed"], 0)

    def test_force_close_real_process(self):
        """The operating-system part really ends a process (one started here)."""
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        try:
            osm = speedup._platform()
            self.assertEqual(osm.alive([child.pid]), [child.pid])
            osm.terminate([child.pid], True)
            child.wait(timeout=20)
            self.assertEqual(osm.alive([child.pid]), [])
        finally:
            if child.poll() is None:
                child.kill()


class FakeSetting:
    def __init__(self, value):
        self.value, self.writes, self.fail = value, [], False

    def read(self):
        return self.value

    def write(self, v):
        if self.fail:
            raise OSError("refused")
        self.writes.append(v)
        self.value = v


class TweakTest(Base):
    def setUp(self):
        super().setUp()
        self.a, self.b = FakeSetting(1), FakeSetting(None)
        self.list = [Tweak("a", "A", "", self.a.read, self.a.write, 0, 1),
                     Tweak("b", "B", "", self.b.read, self.b.write, [0, 0], None),
                     Tweak("c", "C", "", lambda: 0, lambda v: None, 1, 0, available=lambda: "Không có")]
        p = mock.patch.object(speedup, "tweaks", lambda: self.list)
        p.start()
        self.addCleanup(p.stop)

    def test_apply_and_undo_restores_original(self):
        self.a.value = 7  # the user's own value, not the default
        speedup.set_tweak("a", True)
        self.assertEqual(self.a.value, 0)
        item = next(i for i in speedup.tweak_list() if i["id"] == "a")
        self.assertTrue(item["on"] and item["by_app"])
        self.assertTrue(speedup.set_tweak("a", True)["unchanged"])
        speedup.set_tweak("a", False)
        self.assertEqual(self.a.value, 7)
        self.assertFalse(next(i for i in speedup.tweak_list() if i["id"] == "a")["by_app"])

    def test_missing_setting_comes_back_missing(self):
        speedup.set_tweak("b", True)
        self.assertEqual(self.b.value, [0, 0])
        speedup.set_tweak("b", False)
        self.assertIsNone(self.b.value)

    def test_failed_change_leaves_no_record(self):
        self.a.fail = True
        with self.assertRaises(OSError):
            speedup.set_tweak("a", True)
        self.assertIsNone(speedup._record("a"))
        self.assertEqual(self.a.value, 1)

    def test_record_written_before_change(self):
        seen = []
        self.list[0] = Tweak("a", "A", "", self.a.read, lambda v: seen.append(speedup._record("a")), 0, 1)
        speedup.set_tweak("a", True)
        self.assertEqual(seen[0]["original"], 1)

    def test_unavailable_refused(self):
        item = next(i for i in speedup.tweak_list() if i["id"] == "c")
        self.assertEqual(item["unavailable"], "Không có")
        self.assertFalse(item["on"])
        with self.assertRaises(RuntimeError):
            speedup.set_tweak("c", True)

    def test_off_when_already_off_does_nothing(self):
        self.assertTrue(speedup.set_tweak("a", False)["unchanged"])
        self.assertEqual(self.a.writes, [])

    def test_undo_all(self):
        self.a.value, self.b.value = 5, None
        speedup.set_tweak("a", True)
        speedup.set_tweak("b", True)
        r = speedup.undo_all()
        self.assertEqual((r["restored"], r["failed"]), (2, []))
        self.assertEqual((self.a.value, self.b.value), (5, None))

    def test_advice_counts_tweaks_off(self):
        tips = speedup.advice({}, speedup.tweak_list(), {"can_disable": 0})
        self.assertEqual([t["id"] for t in tips], ["tweaks"])


class AdviceTest(Base):
    def test_each_warning(self):
        st = {"mem_pct": 92, "cpu_pct": 95, "disk_free_pct": 4, "disk_free": 2**30, "uptime": 10 * 86400}
        ids = [t["id"] for t in speedup.advice(st, [], {"can_disable": 3})]
        self.assertEqual(ids, ["mem", "cpu", "disk", "uptime", "startup"])

    def test_all_good(self):
        st = {"mem_pct": 30, "cpu_pct": 5, "disk_free_pct": 50, "disk_free": 200 * 2**30, "uptime": 3600}
        self.assertEqual([t["id"] for t in speedup.advice(st, [], {"can_disable": 0})], ["ok"])

    def test_startup_not_checked(self):
        self.assertEqual([t["id"] for t in speedup.advice({}, [], None)], ["startup"])


class SafeCleanTest(Base):
    def test_only_safe_user_categories(self):
        from pccleaner import junk

        found = [{"id": "s", "label": "safe", "admin": False, "count": 3},
                 {"id": "c", "label": "caution", "admin": False, "count": 3},
                 {"id": "a", "label": "safe", "admin": True, "count": 3},
                 {"id": "e", "label": "safe", "admin": False, "count": 0}]
        with mock.patch.object(junk, "scan", return_value=found), \
                mock.patch.object(junk, "clean", return_value={"moved": 3}) as clean:
            self.assertEqual(speedup.clean_safe_junk()["moved"], 3)
        self.assertEqual(clean.call_args[0][0], ["s"])
        with mock.patch.object(junk, "scan", return_value=found[1:]), mock.patch.object(junk, "clean") as clean:
            self.assertEqual(speedup.clean_safe_junk()["moved"], 0)
        clean.assert_not_called()


class SelfTestFlag(unittest.TestCase):
    def test_self_test_writes_ok(self):
        from pccleaner import app

        out = os.path.join(TMP, "self-test.txt")
        self.assertEqual(app.main(["--self-test", out]), 0)
        self.assertTrue(Path(out).read_text(encoding="utf-8").startswith("ok "))


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
