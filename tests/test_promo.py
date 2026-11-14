"""Sponsors area: only the shipped links can be opened, website visits are tagged."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_BASE = Path(__file__).resolve().parent / "_tmp"
_BASE.mkdir(exist_ok=True)
os.environ.setdefault("PCCLEANER_DATA_DIR", os.path.join(tempfile.mkdtemp(dir=_BASE), "data"))
os.environ.setdefault("PCCLEANER_LANG", "vi")

from pccleaner import promo, server  # noqa: E402


class PromoTest(unittest.TestCase):
    def test_places(self):
        d = server.route("GET", "/api/promo", {}, {})
        self.assertEqual(len(d["places"]), 4)
        for p in d["places"]:
            self.assertEqual(p["links"], ["website", "maps", "facebook"])
            self.assertTrue(p["tagline"]["vi"] and p["tagline"]["en"])

    def test_open_only_shipped_links(self):
        with mock.patch("webbrowser.open") as opened:
            server.route("POST", "/api/open-link", {}, {"id": "tananpalace-wedding", "kind": "website"})
            url = opened.call_args[0][0]
            self.assertTrue(url.startswith("https://tananpalace.com/?"))
            self.assertIn("utm_source=pccleaner", url)
            server.route("POST", "/api/open-link", {}, {"id": "zen-halong", "kind": "facebook"})
            self.assertEqual(opened.call_args[0][0], "https://www.facebook.com/100305381635417")
            for bad in ({"id": "nope", "kind": "website"}, {"id": "zen-halong", "kind": "file"},
                        {"id": "zen-halong", "kind": "javascript:alert(1)"}):
                with self.assertRaises(ValueError):
                    server.route("POST", "/api/open-link", {}, bad)
            self.assertEqual(opened.call_count, 2)

    def test_utm_keeps_query(self):
        u = promo.with_utm("https://x.com/a?b=1&utm_source=old", "p1")
        self.assertEqual(u, "https://x.com/a?b=1&utm_source=pccleaner&utm_medium=app&utm_campaign=p1")

    def test_only_https(self):
        with mock.patch.object(promo, "_load", return_value={"places": [{"id": "x", "name": "X", "links": {"website": "http://x.com"}}]}):
            with self.assertRaises(ValueError):
                promo.link("x", "website")


if __name__ == "__main__":
    unittest.main()
