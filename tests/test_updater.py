"""Phase D: signed update announcements, verified downloads, update settings.

A local web server in this test plays the release server. No real update is
installed; only files inside tests/_tmp are written.
"""
import base64
import hashlib
import json
import os
import shutil
import tempfile
import threading
import unittest
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

_BASE = Path(__file__).resolve().parent / "_tmp"
_BASE.mkdir(exist_ok=True)
TMP = tempfile.mkdtemp(dir=_BASE)
os.environ.setdefault("PCCLEANER_DATA_DIR", os.path.join(TMP, "data"))
os.environ.setdefault("PCCLEANER_LANG", "vi")

from pccleaner import __version__, db, ed25519, paths, quarantine, server, updater  # noqa: E402

SECRET = bytes(range(32))
PUBLIC = ed25519.public_key(SECRET).hex()
OTHER = bytes(range(1, 33))


class Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


class Ed25519Test(unittest.TestCase):
    def test_rfc8032_vectors(self):
        for sk, pk, msg, sig in [
            ("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60",
             "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a", "",
             "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"),
            ("4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb",
             "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c", "72",
             "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00"),
        ]:
            sk, pk, msg, sig = map(bytes.fromhex, (sk, pk, msg, sig))
            self.assertEqual(ed25519.public_key(sk), pk)
            self.assertEqual(ed25519.sign(sk, msg), sig)
            self.assertTrue(ed25519.verify(pk, msg, sig))
            self.assertFalse(ed25519.verify(pk, msg + b"x", sig))
            bad = bytearray(sig)
            bad[5] ^= 1
            self.assertFalse(ed25519.verify(pk, msg, bytes(bad)))
            self.assertFalse(ed25519.verify(pk, msg, sig[:63]))


class UpdaterTest(unittest.TestCase):
    def setUp(self):
        db.reset_for_tests(Path(tempfile.mkdtemp(dir=TMP)) / "t.sqlite3")
        self.www = Path(tempfile.mkdtemp(dir=TMP))
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), partial(Quiet, directory=str(self.www)))
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.env = mock.patch.dict(os.environ, {"PCCLEANER_UPDATE_KEY": PUBLIC, "PCCLEANER_UPDATE_URL": self.url})
        self.env.start()
        shutil.rmtree(paths.data_dir() / "updates", ignore_errors=True)

    def tearDown(self):
        self.env.stop()
        self.httpd.shutdown()
        self.httpd.server_close()

    def publish(self, version="99.0.0", channel="stable", secret=SECRET, body=b"installer " * 1000, **over):
        (self.www / "setup.bin").write_bytes(body)
        dl = {"url": f"{self.url}/setup.bin", "size": len(body), "sha256": hashlib.sha256(body).hexdigest()}
        info = {"app": "PCCleaner", "channel": channel, "version": version, "notes": {"vi": "Sửa lỗi", "en": "Fixes"},
                "downloads": {k: dict(dl) for k in ("windows", "mac", "linux")}}
        info.update(over)
        (self.www / f"{channel}.json").write_bytes(updater.make_announcement(secret.hex(), info))
        return info

    def test_versions(self):
        v = updater.parse_version
        self.assertLess(v("0.6.0"), v("0.6.1"))
        self.assertLess(v("0.7.0-beta.1"), v("0.7.0"))
        self.assertLess(v("0.7.0-beta.1"), v("0.7.0-beta.2"))
        self.assertLess(v("0.6.9"), v("0.10.0"))
        for bad in ("1.0", "v1.0.0", "1.0.0-rc1", ""):
            with self.assertRaises(ValueError):
                v(bad)

    def test_newer_version_is_offered(self):
        self.publish()
        st = updater.check()
        self.assertEqual(st["available"]["version"], "99.0.0")
        self.assertEqual(st["current"], __version__)

    def test_same_or_older_version_is_not_offered(self):
        self.publish(version=__version__)
        self.assertIsNone(updater.check()["available"])
        self.publish(version="0.0.1")
        self.assertIsNone(updater.check()["available"])

    def test_wrong_key_is_refused(self):
        self.publish(secret=OTHER)
        with self.assertRaisesRegex(ValueError, "Chữ ký"):
            updater.check()
        self.assertIsNone(updater.status()["available"])

    def test_changed_announcement_is_refused(self):
        self.publish()
        p = self.www / "stable.json"
        outer = json.loads(p.read_bytes())
        payload = base64.b64decode(outer["payload"]).replace(b"99.0.0", b"99.0.1")
        outer["payload"] = base64.b64encode(payload).decode()
        p.write_text(json.dumps(outer))
        with self.assertRaisesRegex(ValueError, "Chữ ký"):
            updater.check()

    def test_other_app_or_channel_is_refused(self):
        self.publish(app="SomethingElse")
        with self.assertRaises(ValueError):
            updater.check()
        self.publish(channel="stable", version="99.0.0")
        updater.save_settings({"channel": "beta"})
        (self.www / "beta.json").write_bytes((self.www / "stable.json").read_bytes())  # a stable file served as beta
        with self.assertRaisesRegex(ValueError, "không dành cho"):
            updater.check()

    def test_beta_channel(self):
        self.publish(version="99.0.0-beta.1", channel="beta")
        self.assertIsNone(updater.check()["available"] if (self.www / "stable.json").exists() else None)
        updater.save_settings({"channel": "beta"})
        self.assertEqual(updater.check()["available"]["version"], "99.0.0-beta.1")
        with self.assertRaises(ValueError):
            updater.save_settings({"channel": "nightly"})

    def test_not_configured_does_nothing(self):
        with mock.patch.dict(os.environ, {"PCCLEANER_UPDATE_KEY": "", "PCCLEANER_UPDATE_URL": ""}):
            with mock.patch.object(updater, "UPDATE_PUBLIC_KEY", ""), mock.patch.object(updater, "UPDATE_BASE_URL", ""):
                self.assertFalse(updater.check()["configured"])
                updater.check_if_due()

    def test_download_checks_size_and_hash(self):
        self.publish()
        updater.check()
        r = updater.download()
        self.assertTrue(Path(r["path"]).is_file())
        self.assertEqual(Path(r["path"]).parent, paths.data_dir() / "updates")
        # The server now hands out a different file than the signed announcement names.
        (self.www / "setup.bin").write_bytes(b"evil " * 2000)
        Path(r["path"]).unlink()
        with self.assertRaisesRegex(ValueError, "không khớp"):
            updater.download()
        self.assertEqual(list((paths.data_dir() / "updates").iterdir()), [])

    def test_download_too_long_is_refused(self):
        self.publish()
        updater.check()
        (self.www / "setup.bin").write_bytes(b"installer " * 1000 + b"more")
        with self.assertRaisesRegex(ValueError, "không khớp"):
            updater.download()

    def test_install_only_verified_download(self):
        self.publish()
        updater.check()
        stray = Path(TMP) / "other.exe"
        stray.write_bytes(b"x")
        with self.assertRaisesRegex(ValueError, "Chỉ cài"):
            updater.install(str(stray))
        r = updater.download()
        Path(r["path"]).write_bytes(b"changed after download")
        with self.assertRaisesRegex(ValueError, "không khớp"):
            updater.install(r["path"])

    def test_update_keeps_quarantine(self):
        f = Path(TMP) / "keep.bin"
        f.write_bytes(b"k" * 10)
        batch = quarantine.quarantine([str(f)], "t")["batch_id"]
        self.publish()
        updater.check()
        updater.download()
        self.assertTrue(any(b["batch_id"] == batch for b in quarantine.batches()))

    def test_api(self):
        self.publish()
        st = server.route("POST", "/api/update-check", {}, {})
        self.assertEqual(st["available"]["version"], "99.0.0")
        self.assertEqual(server.route("GET", "/api/update", {}, {})["channel"], "stable")
        self.assertFalse(server.route("POST", "/api/update-settings", {}, {"auto_check": False})["auto_check"])

    def test_check_if_due_once_a_day(self):
        self.publish()
        updater.check_if_due()
        self.assertIsNotNone(updater.status()["available"])
        self.publish(version="99.0.1")
        updater.check_if_due()  # checked moments ago: no new request
        self.assertEqual(updater.status()["available"]["version"], "99.0.0")


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
