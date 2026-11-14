"""Draws the launcher icon (blue tile with three sparkles) at every Android size."""
import sys
from pathlib import Path
from PIL import Image, ImageDraw

S = 768
def star(d, cx, cy, r, w):
    pts = []
    import math
    for k in range(8):
        ang = math.pi / 4 * k - math.pi / 2
        rad = r if k % 2 == 0 else w
        pts.append((cx + rad * math.cos(ang), cy + rad * math.sin(ang)))
    d.polygon(pts, fill="white")

def draw(rounded=True):
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    if rounded:
        d.ellipse([0, 0, S - 1, S - 1], fill=(47, 111, 237, 255))
    else:
        d.rectangle([0, 0, S, S], fill=(47, 111, 237, 255))
    star(d, S * .44, S * .56, S * .25, S * .07)
    star(d, S * .70, S * .30, S * .13, S * .035)
    star(d, S * .72, S * .72, S * .09, S * .026)
    return im

root = Path(sys.argv[1] if len(sys.argv) > 1 else "android/app/src/main/res")
for name, px in {"mdpi": 48, "hdpi": 72, "xhdpi": 96, "xxhdpi": 144, "xxxhdpi": 192}.items():
    out = root / f"mipmap-{name}" / "ic_launcher.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    draw().resize((px, px), Image.LANCZOS).save(out)
draw(False).resize((512, 512), Image.LANCZOS).save(Path("tool") / "icon-512.png")
print("ok")
