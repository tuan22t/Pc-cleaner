"""Downloads the four promo photos named in assets/promo/promo.json into
assets/promo/, so they are packed inside the APK (the app itself has no
Internet permission). Run in CI before `flutter build`. A failed download
is not fatal: the card then shows a coloured placeholder."""
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "assets" / "promo"
data = json.loads((ROOT / "promo.json").read_text(encoding="utf-8"))
ok = 0
for p in data["places"]:
    url, name = p.get("image_url"), p.get("image")
    if not url or not name:
        continue
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (PC Cleaner build)"})
        with urllib.request.urlopen(req, timeout=30) as r:
            body = r.read()
        if len(body) < 2000 or len(body) > 3_000_000:
            raise ValueError(f"unexpected size {len(body)}")
        (ROOT / name).write_bytes(body)
        ok += 1
        print(f"ok   {name} ({len(body)//1024} KB)")
    except Exception as e:  # noqa: BLE001
        print(f"skip {name}: {e}", file=sys.stderr)
print(f"{ok}/{len(data['places'])} images")
