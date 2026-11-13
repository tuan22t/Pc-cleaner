"""Tests for phases 3-7: similar photos, system junk, startup items, organizer, schedule."""
import os
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

from pccleaner import db, junk, organizer, paths, quarantine, scanner, scheduler, similar, startup  # noqa: E402

try:
    from PIL import Image, ImageDraw, ImageEnhance
except ImportError:  # pragma: no cover
    Image = None


def _photo(seed: int, size=(640, 480)):
    im = Image.new("RGB", size, (30 * seed % 255, 80, 140))
    d = ImageDraw.Draw(im)
    for k in range(12):
        x = (seed * 97 + k * 53) % size[0]
        y = (seed * 31 + k * 71) % size[1]
        d.ellipse([x, y, x + 120, y + 90], fill=((k * 40 + seed * 13) % 255, (k * 90) % 255, (seed * 50) % 255))
    return im


class Base(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(dir=TMP))
        db.reset_for_tests(Path(tempfile.mkdtemp(dir=TMP)) / "t.sqlite3")


@unittest.skipIf(Image is None, "Pillow not installed")
class SimilarTest(Base):
    def test_finds_resized_and_reencoded_copies_only(self):
        a = _photo(1)
        a.save(self.root / "beach.jpg", quality=95)
        a.resize((320, 240)).save(self.root / "beach_small.jpg", quality=70)
        ImageEnhance.Brightness(a).enhance(1.08).save(self.root / "beach_bright.png")
        _photo(7).save(self.root / "mountain.jpg", quality=90)
        sid = scanner.scan(str(self.root))
        n = similar.find_similar(sid, min_size=0)
        self.assertEqual(n, 1)
        g = similar.get_groups(sid)["groups"][0]
        names = sorted(Path(f["path"]).name for f in g["files"])
        self.assertEqual(names, ["beach.jpg", "beach_bright.png", "beach_small.jpg"])
        # Highest resolution is suggested first, and one photo always stays.
        self.assertIn(Path(g["files"][0]["path"]).name, ("beach.jpg", "beach_bright.png"))
        allowed, refused = similar.check_removal(sid, [f["path"] for f in g["files"]])
        self.assertEqual(len(allowed), 2)
        self.assertEqual(len(refused), 1)

    def test_thumbnail(self):
        _photo(3).save(self.root / "x.jpg")
        data = similar.thumbnail(str(self.root / "x.jpg"))
        self.assertTrue(data.startswith(b"\xff\xd8"))
        (self.root / "notes.txt").write_text("hi")
        with self.assertRaises(FileNotFoundError):
            similar.thumbnail(str(self.root / "notes.txt"))


class JunkTest(Base):
    def _fake_category(self, root, **kw):
        c = junk.Category("test", "Test", "", [str(root)], **kw)
        c.roots = [str(root)]
        return c

    def test_clean_only_old_files_inside_junk_folder_and_undo(self):
        cache = self.root / "cache"
        (cache / "sub").mkdir(parents=True)
        old = cache / "sub" / "old.tmp"
        old.write_bytes(b"x" * 1000)
        past = time.time() - 3 * 86400
        os.utime(old, (past, past))
        fresh = cache / "fresh.tmp"
        fresh.write_bytes(b"y" * 10)
        outside = self.root / "keep.txt"
        outside.write_text("keep")
        if not paths.IS_WINDOWS:
            os.symlink(outside, cache / "link.txt")
        cat = self._fake_category(cache)
        orig = junk.categories
        junk.categories = lambda: [cat]
        try:
            found = junk.scan()
            self.assertEqual(found[0]["count"], 1)
            self.assertEqual(found[0]["size"], 1000)
            r = junk.clean(["test"])
        finally:
            junk.categories = orig
        self.assertEqual(r["moved"], 1)
        self.assertFalse(old.exists())
        self.assertTrue(fresh.exists())
        self.assertTrue(outside.exists())
        quarantine.restore(r["batch_ids"][0])
        self.assertTrue(old.exists())

    def test_allow_roots_cannot_escape(self):
        junkdir = self.root / "junk"
        junkdir.mkdir()
        victim = self.root / "important.doc"
        victim.write_text("data")
        r = quarantine.quarantine([str(junkdir / ".." / "important.doc")], "t", allow_roots=[str(junkdir)])
        self.assertEqual(r["moved"], 0)
        self.assertTrue(victim.exists())

    def test_real_categories_list(self):
        cats = junk.categories()
        self.assertTrue(cats)
        for c in cats:
            self.assertIn(c.label, ("safe", "caution"))
            for root in c.roots:
                self.assertFalse(os.path.normcase(root).startswith(os.path.normcase(str(paths.data_dir()))))


class OrganizerTest(Base):
    def test_preview_apply_undo(self):
        d = self.root / "Downloads"
        d.mkdir()
        (d / "a.jpg").write_bytes(b"1")
        (d / "b.pdf").write_bytes(b"2")
        (d / "c.zip").write_bytes(b"3")
        (d / "sub").mkdir()
        (d / "sub" / "inner.jpg").write_bytes(b"4")
        (d / "Tài liệu").mkdir()
        (d / "Tài liệu" / "b.pdf").write_bytes(b"old")  # name clash
        plan = organizer.preview(str(d), by_year=False)
        dests = {Path(m["src"]).name: os.path.relpath(m["dest"], d) for m in plan["moves"]}
        self.assertEqual(dests["a.jpg"], os.path.join("Ảnh", "a.jpg"))
        self.assertEqual(dests["b.pdf"], os.path.join("Tài liệu", "b (2).pdf"))
        self.assertNotIn("inner.jpg", dests)
        r = organizer.apply(str(d), [m["src"] for m in plan["moves"]], by_year=False)
        self.assertEqual(r["moved"], 3)
        self.assertEqual((d / "Tài liệu" / "b.pdf").read_bytes(), b"old")
        self.assertTrue((d / "Tài liệu" / "b (2).pdf").exists())
        back = quarantine.restore(r["batch_id"])
        self.assertEqual(back["restored"], 3)
        self.assertTrue((d / "a.jpg").exists() and (d / "b.pdf").exists() and (d / "c.zip").exists())
        self.assertFalse((d / "Ảnh").exists())  # empty folder removed again

    def test_protected_folder_refused(self):
        sysdir = os.environ.get("SystemRoot", r"C:\Windows") if paths.IS_WINDOWS else "/usr/bin"
        with self.assertRaises(PermissionError):
            organizer.preview(sysdir)


class StartupTest(Base):
    def test_classify(self):
        self.assertEqual(startup.classify("Spotify")[0], "safe")
        self.assertEqual(startup.classify("SecurityHealth", "Windows Defender")[0], "keep")
        self.assertEqual(startup.classify("xyz123")[0], "unknown")

    @unittest.skipUnless(paths.IS_WINDOWS, "Windows only")
    def test_windows_run_key_disable_enable(self):
        import winreg

        name = "PCCleanerTestItem"
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, startup.RUN) as k:
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, r'"C:\Program Files\Spotify\Spotify.exe" /minimized')
        try:
            items = {i["id"]: i for i in startup.list_items()}
            iid = f"run|HKCU|Run|{name}"
            self.assertIn(iid, items)
            self.assertTrue(items[iid]["enabled"])
            self.assertEqual(items[iid]["label"], "safe")
            startup.set_enabled(iid, False)
            self.assertFalse({i["id"]: i for i in startup.list_items()}[iid]["enabled"])
            # The program entry itself is untouched: only disabled, never removed.
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, startup.RUN) as k:
                self.assertTrue(winreg.QueryValueEx(k, name)[0])
            startup.set_enabled(iid, True)
            self.assertTrue({i["id"]: i for i in startup.list_items()}[iid]["enabled"])
        finally:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, startup.RUN, 0, winreg.KEY_SET_VALUE) as k:
                winreg.DeleteValue(k, name)
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, startup.APPROVED + r"\Run", 0, winreg.KEY_SET_VALUE) as k:
                    winreg.DeleteValue(k, name)
            except OSError:
                pass

    @unittest.skipUnless(paths.IS_MAC, "macOS only")
    def test_mac_launch_agent_disable_enable(self):
        import plistlib

        label = "com.pccleaner.testagent"
        p = Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "wb") as f:
            plistlib.dump({"Label": label, "ProgramArguments": ["/usr/bin/true"], "RunAtLoad": False}, f)
        try:
            items = {i["name"]: i for i in startup.list_items()}
            self.assertIn(label, items)
            iid = items[label]["id"]
            try:
                startup.set_enabled(iid, False)
            except RuntimeError as e:
                self.skipTest(f"launchctl not usable here: {e}")
            self.assertFalse({i["name"]: i for i in startup.list_items()}[label]["enabled"])
            self.assertTrue(p.exists())  # never deleted
            startup.set_enabled(iid, True)
            self.assertTrue({i["name"]: i for i in startup.list_items()}[label]["enabled"])
        finally:
            startup._run(["launchctl", "enable", f"gui/{os.getuid()}/{label}"])
            p.unlink(missing_ok=True)


class ScheduleTest(Base):
    @unittest.skipUnless(paths.IS_WINDOWS or paths.IS_MAC, "Windows/macOS only")
    def test_register_and_remove(self):
        cfg = scheduler.save({"enabled": True, "frequency": "weekly", "hour": 3, "junk": True, "purge_days": 30})
        try:
            self.assertTrue(cfg["enabled"])
            self.assertTrue(scheduler.is_registered())
        finally:
            scheduler.save({"enabled": False})
        self.assertFalse(scheduler.is_registered())

    def test_purge_older_than(self):
        f = self.root / "old.bin"
        f.write_bytes(b"z" * 500)
        r = quarantine.quarantine([str(f)], "t")
        conn = db.connect()
        conn.execute("UPDATE actions SET ts=? WHERE batch_id=?", (time.time() - 40 * 86400, r["batch_id"]))
        conn.commit()
        self.assertEqual(quarantine.purge_older_than(30)["freed"], 500)
        self.assertEqual(quarantine.purge_older_than(30)["batches"], 0)

    def test_command_line(self):
        cmd = scheduler._command()
        self.assertEqual(cmd[-1], "--auto-clean")


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
