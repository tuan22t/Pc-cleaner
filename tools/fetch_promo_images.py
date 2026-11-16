"""Download the sponsors' photos (named in pccleaner/web/promo/promo.json) and
shrink them for the app (640x336 JPEG, about 50 KB each). Run by the build scripts; a photo that cannot be
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
        for img in p.get("images", []):
            url, target = img.get("url"), PROMO / img.get("file", "")
            if not url or not img.get("file"):
                continue
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 PCCleaner-build"})
                raw = urllib.request.urlopen(req, timeout=30).read(20 * 2**20)
                im = ImageOps.fit(Image.open(io.BytesIO(raw)).convert("RGB"), SIZE, Image.LANCZOS)
                im.save(target, "JPEG", quality=80, optimize=True, progressive=True)
                print(f"photo {target.name}: {target.stat().st_size // 1024} KB")
            except Exception as e:  # noqa: BLE001
                print(f"photo {target.name} skipped: {e}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
