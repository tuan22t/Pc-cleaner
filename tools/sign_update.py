"""Write the signed update announcement for one channel (run on the release machine).

  python tools/sign_update.py --channel stable --version 0.6.1 \
      --windows dist/PCCleaner-Setup-0.6.1.exe --mac dist/PCCleaner-0.6.1.dmg \
      --base-url https://example.com/pc-cleaner/0.6.1 --notes-vi "..." --notes-en "..." \
      -o dist/stable.json

The private key comes from the UPDATE_SIGNING_KEY environment variable (64 hex
characters). Never put it in the repository.
  python tools/sign_update.py --new-key   prints a new key pair
"""
from __future__ import annotations

import argparse
import hashlib
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pccleaner import APP_ID, ed25519, updater  # noqa: E402


def _file(path: str, base_url: str) -> dict:
    p = Path(path)
    return {"url": f"{base_url.rstrip('/')}/{p.name}", "size": p.stat().st_size,
            "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--new-key", action="store_true")
    ap.add_argument("--channel", choices=updater.CHANNELS)
    ap.add_argument("--version")
    ap.add_argument("--windows")
    ap.add_argument("--mac")
    ap.add_argument("--base-url")
    ap.add_argument("--notes-vi", default="")
    ap.add_argument("--notes-en", default="")
    ap.add_argument("-o", "--out")
    a = ap.parse_args()
    if a.new_key:
        secret = os.urandom(32)
        print("private (secret UPDATE_SIGNING_KEY):", secret.hex())
        print("public  (updater.UPDATE_PUBLIC_KEY):", ed25519.public_key(secret).hex())
        return 0
    key = os.environ.get("UPDATE_SIGNING_KEY", "")
    if len(key) != 64:
        sys.exit("UPDATE_SIGNING_KEY is not set")
    updater.parse_version(a.version)
    if a.channel == "stable" and "-beta" in a.version:
        sys.exit("a beta version cannot go to the stable channel")
    downloads = {}
    if a.windows:
        downloads["windows"] = _file(a.windows, a.base_url)
    if a.mac:
        downloads["mac"] = _file(a.mac, a.base_url)
    info = {"app": APP_ID, "channel": a.channel, "version": a.version, "date": time.strftime("%Y-%m-%d"),
            "notes": {"vi": a.notes_vi, "en": a.notes_en}, "downloads": downloads}
    Path(a.out).write_bytes(updater.make_announcement(key, info))
    print(f"wrote {a.out} ({a.channel} {a.version})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
