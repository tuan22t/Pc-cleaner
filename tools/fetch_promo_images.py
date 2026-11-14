"""Download the sponsors' photos (named in pccleaner/web/promo/promo.json) and
shrink them for the app. Run by the build scripts; a photo that cannot be
downloaded is skipped and the app shows a plain colour tile instead."""
from __future__ import annotations

import io
import json
import sys
import urllib.request
from pathlib import Path

PROMO = Path(__file__).resolve().parent.parent / "pccleaner" / "web" / "promo"
SIZE = (640, 336)


def main() -> int:
    from PIL import Image, ImageOps

    data = json.loads((PROMO / "promo.json").read_text(encoding="utf-8"))
    for p in data["places"]:
        url, target = p.get("image_url"), PROMO / p.get("image", "")
        if not url or not p.get("image"):
            continue
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 PCCleaner-build"})
            raw = urllib.request.urlopen(req, timeout=30).read(20 * 2**20)
            im = ImageOps.fit(Image.open(io.BytesIO(raw)).convert("RGB"), SIZE, Image.LANCZOS)
            im.save(target, "JPEG", quality=82, optimize=True, progressive=True)
            print(f"photo {target.name}: {target.stat().st_size // 1024} KB")
        except Exception as e:  # noqa: BLE001
            print(f"photo {p['id']} skipped: {e}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
