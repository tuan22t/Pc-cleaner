"""The interface in a real browser: the main flows, in Vietnamese and English.

Runs only where Playwright for Python and Chromium are installed (CI installs
them in the "ui" job); elsewhere these tests are skipped. Only folders inside
tests/_tmp are scanned or cleaned. The system-junk check, the scheduled run and
startup changes are never started here.

PCCLEANER_SCREENSHOTS=<folder> also saves a screenshot of each screen in both
languages (used for the phase report).
"""
import glob
import json
import os
import re
import shutil
import tempfile
import time
import unittest
from pathlib import Path

_BASE = Path(__file__).resolve().parent / "_tmp"
_BASE.mkdir(exist_ok=True)
TMP = tempfile.mkdtemp(dir=_BASE)
os.environ.setdefault("PCCLEANER_DATA_DIR", os.path.join(TMP, "data"))
os.environ.setdefault("PCCLEANER_LANG", "vi")  # messages are checked in Vietnamese

from pccleaner import dashboard, db, server  # noqa: E402

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover - depends on the machine
    sync_playwright = None

VI = re.compile(r"[À-ÖØ-öø-ỹđĐ]")  # Latin letters with marks (not × or ÷)
SHOTS = os.environ.get("PCCLEANER_SCREENSHOTS")
VIEWS = ["home", "usage", "large", "old", "types", "dups", "similar", "junk", "startup", "organize", "schedule",
         "quarantine", "settings"]


def _browser(p):
    try:
        return p.chromium.launch()
    except Exception:  # noqa: BLE001 - fall back to a preinstalled Chromium
        exe = glob.glob("/opt/pw-browsers/chromium-*/chrome-linux*/chrome")
        if not exe:
            raise
        return p.chromium.launch(executable_path=exe[0], args=["--no-sandbox"])


@unittest.skipIf(sync_playwright is None, "Playwright for Python is not installed")
class UiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db.reset_for_tests(Path(TMP) / "ui.sqlite3")
        cls.root = Path(tempfile.mkdtemp(dir=TMP, prefix="scan-"))
        (cls.root / "Videos").mkdir()
        (cls.root / "Docs").mkdir()
        big = os.urandom(3_000_000)
        (cls.root / "Videos" / "holiday.mp4").write_bytes(big)
        (cls.root / "Docs" / "holiday copy.mp4").write_bytes(big)
        (cls.root / "Docs" / "report.pdf").write_bytes(os.urandom(11_000_000))
        (cls.root / "Docs" / "notes.txt").write_text("hello")
        old = time.time() - 3 * 365 * 86400
        os.utime(cls.root / "Docs" / "report.pdf", (old, old))
        cls._seed_history()
        cls.httpd, cls.url, _token = server.start_server(0)
        cls.pw = sync_playwright().start()
        try:
            cls.browser = _browser(cls.pw)
        except Exception as e:  # noqa: BLE001
            cls.pw.stop()
            cls.httpd.shutdown()
            raise unittest.SkipTest(f"Chromium is not available: {e}")
        cls.page = cls.browser.new_page(viewport={"width": 1280, "height": 860}, bypass_csp=True)
        cls.page.goto(cls.url)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
        cls.httpd.shutdown()
        cls.httpd.server_close()

    @classmethod
    def _seed_history(cls):
        """A month of disk readings in the test database, so the history chart has something to draw."""
        from pccleaner import paths

        conn = db.connect()
        for loc in paths.list_locations():
            step = max(loc["used"] // 200, 1)
            used = loc["used"] - 15 * step
            for d in range(30, 0, -1):
                day = time.strftime("%Y-%m-%d", time.localtime(time.time() - d * 86400))
                used += 2 * step if d % 7 else -6 * step  # grows, with a weekly cleanup
                conn.execute("INSERT OR REPLACE INTO disk_history(path, day, ts, total, used) VALUES (?,?,?,?,?)",
                             (loc["path"], day, time.time() - d * 86400, loc["total"], max(0, used)))
        conn.commit()
        dashboard.remember("last_startup", {"total": 9, "enabled": 7, "can_disable": 4})

    # -- helpers --
    def go(self, view):
        self.page.click(f'nav a[data-view="{view}"]')
        self.page.wait_for_selector(f"#view-{view}.active")
        self.page.wait_for_timeout(250)

    def wait_job(self, until=None):
        """Wait for the background job. ``until``: a condition to wait for as well,
        because the job may not have started yet when the progress bar is checked."""
        self.page.wait_for_selector("#jobBar.hidden", state="attached", timeout=30_000)
        self.page.wait_for_timeout(300)
        for _ in range(300):
            if until is None or until():
                return
            self.page.wait_for_timeout(100)
        self.page.wait_for_selector("#jobBar.hidden", state="attached", timeout=30_000)

    def shot(self, name):
        if SHOTS:
            os.makedirs(SHOTS, exist_ok=True)
            self.page.screenshot(path=os.path.join(SHOTS, f"{name}.png"))

    def visible_text(self):
        return self.page.evaluate("""() => {
            // Proper names (the sponsors' names and addresses) are marked translate="no".
            const text = (sel) => { const c = document.querySelector(sel).cloneNode(true);
                c.querySelectorAll('[translate="no"]').forEach((e) => e.remove());
                document.body.appendChild(c); const s = c.innerText; c.remove(); return s; };
            const parts = [text('.sidebar'), text('main')];
            for (const id of ['modal', 'guide', 'toast'])
                if (!document.getElementById(id).classList.contains('hidden')) parts.push(document.getElementById(id).innerText);
            for (const el of document.querySelectorAll('[title], [placeholder]'))
                if (el.offsetParent) parts.push(el.getAttribute('title') || '', el.getAttribute('placeholder') || '');
            return parts.join('\\n');
        }""")

    # -- the flows, in order --
    def test_1_first_run_guide(self):
        self.page.wait_for_selector("#guide:not(.hidden)")
        self.assertIn("Chào mừng", self.page.inner_text("#guide"))
        self.shot("vi-0-huong-dan")
        for _ in range(4):
            self.page.click("#guideNext")
        self.assertIn("Bắt đầu", self.page.inner_text("#guideNext"))
        self.page.click("#guideNext")
        self.page.wait_for_selector("#guide.hidden", state="attached")
        # The guide closes first and saves "seen" right after: wait for the save.
        for _ in range(100):
            if server._settings()["onboarded"]:
                break
            self.page.wait_for_timeout(100)
        self.assertTrue(server._settings()["onboarded"])

    def test_2_dashboard(self):
        self.page.wait_for_selector("#dashTiles .tile-stat")
        self.assertEqual(self.page.locator("#dashTiles .tile-stat").count(), 4)
        self.assertGreater(self.page.locator("#locations .card").count(), 0)
        self.page.wait_for_selector("#dashHistory svg polyline")

    def test_3_scan_and_reports(self):
        self.go("home")
        self.page.fill("#customPath", str(self.root))
        self.page.click("#customScanBtn")
        self.page.wait_for_selector("#view-usage.active", timeout=30_000)
        self.page.wait_for_selector("#treemap .tile")
        self.go("types")
        self.assertGreater(self.page.locator("#catList .b").count(), 0)
        self.go("old")
        self.page.select_option("#oldMin", "10485760")
        self.page.wait_for_timeout(300)
        self.assertIn("report.pdf", self.page.inner_text("#oldList"))

    def test_4_duplicates(self):
        self.go("dups")
        self.page.select_option("#dupMin", "102400")
        self.page.click("#dupRun")
        self.wait_job()
        self.page.wait_for_selector("#dupList .group, #dupList .row")
        self.assertIn("holiday", self.page.inner_text("#dupList"))

    def test_5_clean_and_undo(self):
        self.go("large")
        self.page.select_option("#largeMin", "0")
        self.page.wait_for_selector('#largeList input[data-sel="large"]')
        target = str(self.root / "Docs" / "report.pdf")
        self.page.check(f"#largeList input[value={json.dumps(target)}]")  # CSS string: Windows backslashes escaped
        self.page.click("#selClean")
        self.page.wait_for_selector("#modal:not(.hidden)")
        self.assertIn("Khu cách ly", self.page.inner_text("#modal"))
        self.page.click("#modalOk")
        self.wait_job(until=lambda: not os.path.exists(target))
        self.assertFalse(os.path.exists(target))
        self.go("quarantine")
        self.page.wait_for_selector("[data-restore]")
        self.page.click("[data-restore]")
        self.wait_job(until=lambda: os.path.exists(target))
        self.assertTrue(os.path.exists(target))

    def test_6_screens_in_vietnamese(self):
        self.go("home")
        self.page.wait_for_selector("#promoCard:not(.hidden) [data-promo]")
        self.assertIn("đồng hành", self.page.inner_text("#promoCard"))
        self.assertIn("Đồng hành", self.page.inner_text("#navSponsor"))
        self.go("settings")
        self.page.wait_for_selector("#promoList [data-promo]")
        self.assertEqual(self.page.locator("#promoList .promo-row").count(), 4)
        for v in VIEWS:
            self.go(v)
            self.shot(f"vi-{VIEWS.index(v) + 1:02d}-{v}")

    def test_7_english_and_dark_mode(self):
        self.go("settings")
        self.page.select_option("#setLang", "en")
        self.page.wait_for_function("document.documentElement.lang === 'en'")
        self.page.wait_for_timeout(300)
        self.assertIn("Dashboard", self.page.inner_text(".sidebar"))
        self.assertEqual(server._settings()["lang"], "en")
        leftovers = {}
        for v in VIEWS:
            self.go(v)
            self.shot(f"en-{VIEWS.index(v) + 1:02d}-{v}")
            text = self.visible_text().replace(str(self.root), "").replace("Tiếng Việt", "")
            bad = [line for line in text.splitlines() if VI.search(line)]
            if bad:
                leftovers[v] = bad
        self.assertEqual(leftovers, {}, "Vietnamese text left on English screens")
        # an error from the back end comes back in English too
        self.page.evaluate("document.querySelector('#customPath').value = ''")
        self.go("home")
        self.page.fill("#customPath", str(self.root / "missing"))
        self.page.click("#customScanBtn")
        self.page.wait_for_selector("#toast:not(.hidden)")
        self.assertIn("Folder does not exist", self.page.inner_text("#toast"))
        self.go("settings")
        self.page.select_option("#setTheme", "dark")
        self.page.wait_for_function("document.documentElement.dataset.theme === 'dark'")
        self.go("home")
        self.shot("en-dark-01-home")
        self.go("settings")
        self.page.select_option("#setTheme", "system")
        self.page.select_option("#setLang", "vi")
        self.page.wait_for_function("document.documentElement.lang === 'vi'")
        self.assertIn("Tổng quan", self.page.inner_text(".sidebar"))


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
