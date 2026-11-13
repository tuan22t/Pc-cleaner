"""Near-duplicate photos: perceptual hash (dHash) + Hamming distance.

Two photos that look the same (re-saved, resized, lightly edited, burst shots)
get hashes that differ in only a few of their 64 bits, even though their bytes
are completely different.
"""
from __future__ import annotations

import os
import threading
from collections import defaultdict
from dataclasses import dataclass
from typing import Callable

from . import db, paths

IMAGE_EXTS = {"jpg", "jpeg", "png", "bmp", "gif", "webp", "tif", "tiff", "heic", "heif"}
DEFAULT_THRESHOLD = 6  # bits out of 64; must stay below 8 for the bucket search below


@dataclass
class SimProgress:
    stage: str = "Đọc ảnh"
    done: int = 0
    total: int = 0
    current: str = ""


def _open_image(path: str):
    from PIL import Image  # imported lazily: only this feature needs Pillow

    if path.lower().endswith((".heic", ".heif")):
        try:
            import pillow_heif  # type: ignore

            pillow_heif.register_heif_opener()
        except ImportError:
            raise OSError("Cần cài pillow-heif để đọc ảnh HEIC")
    return Image.open(path)


def dhash(path: str) -> tuple[int, int, int]:
    """Return (64-bit difference hash, width, height)."""
    from PIL import Image

    with _open_image(path) as im:
        w, h = im.size
        im.draft("L", (64, 64))  # fast JPEG downscale while decoding
        small = im.convert("L").resize((9, 8), Image.Resampling.LANCZOS)
        px = small.tobytes()  # one byte per pixel in "L" mode
    bits = 0
    for row in range(8):
        for col in range(8):
            bits = (bits << 1) | (px[row * 9 + col] > px[row * 9 + col + 1])
    return bits, w, h


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def find_similar(
    scan_id: int,
    threshold: int = DEFAULT_THRESHOLD,
    min_size: int = 8 * 1024,
    progress: SimProgress | None = None,
    cancel: threading.Event | None = None,
    on_progress: Callable[[SimProgress], None] | None = None,
) -> int:
    progress = progress or SimProgress()
    cancel = cancel or threading.Event()
    threshold = max(0, min(int(threshold), 7))
    conn = db.connect()
    sep = os.sep
    marks = ",".join("?" * len(IMAGE_EXTS))
    rows = conn.execute(
        f"""SELECT f.size, f.mtime, rtrim(d.path, ?) || ? || f.name AS path FROM files f
            JOIN dirs d ON d.scan_id=f.scan_id AND d.id=f.dir_id
            WHERE f.scan_id=? AND f.size>=? AND f.ext IN ({marks})""",
        (sep, sep, scan_id, min_size, *IMAGE_EXTS),
    ).fetchall()
    progress.total = len(rows)
    images: list[tuple[str, int, float, int, int, int]] = []  # path, size, mtime, hash, w, h
    for r in rows:
        if cancel.is_set():
            raise InterruptedError
        path, size, mtime = r["path"], r["size"], r["mtime"]
        progress.done += 1
        progress.current = path
        if on_progress and progress.done % 20 == 0:
            on_progress(progress)
        c = conn.execute("SELECT * FROM image_hashes WHERE path=?", (path,)).fetchone()
        if c and c["size"] == size and abs(c["mtime"] - mtime) < 1e-3 and c["dhash"]:
            h, w, hh = int(c["dhash"], 16), c["width"], c["height"]
        else:
            try:
                h, w, hh = dhash(path)
            except Exception:  # noqa: BLE001 - unreadable or unsupported image
                continue
            conn.execute(
                """INSERT INTO image_hashes(path, size, mtime, dhash, width, height) VALUES (?,?,?,?,?,?)
                   ON CONFLICT(path) DO UPDATE SET size=excluded.size, mtime=excluded.mtime,
                   dhash=excluded.dhash, width=excluded.width, height=excluded.height""",
                (path, size, mtime, f"{h:016x}", w, hh),
            )
        images.append((path, size, mtime, h, w, hh))
    conn.commit()

    # Pigeonhole: if two 64-bit hashes differ in at most 7 bits, at least one of
    # their eight bytes is identical. Comparing only within those byte buckets
    # avoids checking every pair.
    progress.stage = "So sánh ảnh"
    if on_progress:
        on_progress(progress)
    buckets: dict[tuple[int, int], list[int]] = defaultdict(list)
    for idx, img in enumerate(images):
        for k in range(8):
            buckets[(k, (img[3] >> (8 * k)) & 0xFF)].append(idx)
    parent = list(range(len(images)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    checked: set[tuple[int, int]] = set()
    for members in buckets.values():
        if cancel.is_set():
            raise InterruptedError
        for i in range(len(members)):
            a = members[i]
            for b in members[i + 1 :]:
                key = (a, b) if a < b else (b, a)
                if key in checked:
                    continue
                checked.add(key)
                if hamming(images[a][3], images[b][3]) <= threshold:
                    ra, rb = find(a), find(b)
                    if ra != rb:
                        parent[ra] = rb
    groups: dict[int, list[int]] = defaultdict(list)
    for idx in range(len(images)):
        groups[find(idx)].append(idx)
    result = [g for g in groups.values() if len(g) > 1]
    result.sort(key=lambda g: -sum(images[i][1] for i in g))

    conn.execute("DELETE FROM similar_groups WHERE scan_id=?", (scan_id,))
    for gid, members in enumerate(result):
        best = max(members, key=lambda i: (images[i][4] * images[i][5], images[i][1]))
        conn.executemany(
            "INSERT INTO similar_groups(scan_id, group_id, path, size, mtime, width, height, distance) VALUES (?,?,?,?,?,?,?,?)",
            [
                (scan_id, gid, images[i][0], images[i][1], images[i][2], images[i][4], images[i][5],
                 hamming(images[i][3], images[best][3]))
                for i in members
            ],
        )
    conn.commit()
    progress.stage = "Xong"
    if on_progress:
        on_progress(progress)
    return len(result)


def get_groups(scan_id: int, limit: int = 300) -> dict:
    conn = db.connect()
    rows = conn.execute(
        "SELECT * FROM similar_groups WHERE scan_id=? AND group_id<? ORDER BY group_id", (scan_id, limit)
    ).fetchall()
    groups: dict[int, dict] = {}
    for r in rows:
        g = groups.setdefault(r["group_id"], {"id": r["group_id"], "files": []})
        g["files"].append({
            "path": r["path"], "size": r["size"], "mtime": r["mtime"], "width": r["width"], "height": r["height"],
            "distance": r["distance"], **paths.file_flags(r["path"]), "exists": os.path.exists(r["path"]),
        })
    out = list(groups.values())
    for g in out:
        # Best first: still exists, highest resolution, then largest file.
        g["files"].sort(key=lambda f: (not f["exists"], -(f["width"] or 0) * (f["height"] or 0), -f["size"]))
        g["saving"] = sum(f["size"] for f in g["files"][1:])
    n = conn.execute("SELECT COUNT(DISTINCT group_id) AS n FROM similar_groups WHERE scan_id=?", (scan_id,)).fetchone()["n"]
    return {"groups": out, "group_count": n, "saving": sum(g["saving"] for g in out)}


def check_removal(scan_id: int, to_remove: list[str]) -> tuple[list[str], list[dict]]:
    """Allow removing photos only while at least one photo of each group stays."""
    conn = db.connect()
    removing = {os.path.normcase(os.path.abspath(p)) for p in to_remove}
    allowed, refused = [], []
    by_group: dict[int, list[str]] = defaultdict(list)
    for p in to_remove:
        r = conn.execute("SELECT group_id FROM similar_groups WHERE scan_id=? AND path=?", (scan_id, p)).fetchone()
        if r is None:
            refused.append({"path": p, "error": "Không thuộc nhóm ảnh giống nhau nào"})
        else:
            by_group[r["group_id"]].append(p)
    for gid, selected in by_group.items():
        members = [r["path"] for r in conn.execute(
            "SELECT path FROM similar_groups WHERE scan_id=? AND group_id=?", (scan_id, gid))]
        keepers = [m for m in members if os.path.normcase(os.path.abspath(m)) not in removing and os.path.isfile(m)]
        if not keepers:
            keep = next((p for p in selected if os.path.isfile(p)), None)
            if keep is None:
                refused += [{"path": p, "error": "Không còn ảnh nào trong nhóm"} for p in selected]
                continue
            selected = [p for p in selected if p != keep]
            refused.append({"path": keep, "error": "Giữ lại ảnh cuối cùng của nhóm"})
        allowed += selected
    return allowed, refused


def thumbnail(path: str, size: int = 240) -> bytes:
    """JPEG thumbnail for the UI. Only image files are served."""
    import io

    ext = os.path.splitext(path)[1].lower().lstrip(".")
    if ext not in IMAGE_EXTS or not os.path.isfile(path):
        raise FileNotFoundError(path)
    with _open_image(path) as im:
        from PIL import ImageOps

        im.draft("RGB", (size * 2, size * 2))
        im = ImageOps.exif_transpose(im).convert("RGB")
        im.thumbnail((size, size))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=80)
        return buf.getvalue()
