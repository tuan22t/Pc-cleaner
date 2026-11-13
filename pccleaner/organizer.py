"""Suggested folder reorganization, always previewed before anything moves.

Only the files sitting directly in the chosen folder are considered (subfolders
are left alone). Each file is sorted into a sub-folder by type, optionally
split by year for photos and videos. Moves never overwrite: a name clash gets
" (2)", " (3)"… appended. Every move is logged and can be undone in one click.
"""
from __future__ import annotations

import os
import time

from . import paths, quarantine, scanner

FOLDER_NAMES = {
    "Ảnh": "Ảnh",
    "Video": "Video",
    "Âm thanh": "Âm thanh",
    "Tài liệu": "Tài liệu",
    "Nén / bộ cài": "Nén - Bộ cài",
    "Mã nguồn / dev": "Lập trình",
    "Tạm / bộ nhớ đệm": "File tạm",
    "Khác": "Khác",
}
BY_YEAR = {"Ảnh", "Video"}
SKIP_EXTS = {"lnk", "url", "ini", "desktop", "ds_store", "localized", "alias", "webloc"}


def _unique(dest: str, taken: set[str]) -> str:
    base, ext = os.path.splitext(dest)
    cand, n = dest, 2
    while os.path.exists(cand) or os.path.normcase(cand) in taken:
        cand = f"{base} ({n}){ext}"
        n += 1
    return cand


def preview(folder: str, by_year: bool = True) -> dict:
    folder = os.path.abspath(os.path.expanduser(folder))
    if not os.path.isdir(folder):
        raise FileNotFoundError(f"Thư mục không tồn tại: {folder}")
    if paths.is_protected(folder):
        raise PermissionError("Đây là thư mục hệ thống hoặc chương trình, ứng dụng không sắp xếp ở đây.")
    plan, taken = [], set()
    with os.scandir(folder) as it:
        entries = sorted((e for e in it), key=lambda e: e.name.lower())
    for e in entries:
        if e.name.startswith(".") or e.is_symlink() or not e.is_file(follow_symlinks=False):
            continue
        ext = scanner._ext(e.name)
        if ext in SKIP_EXTS or e.name.lower() in ("desktop.ini", "thumbs.db"):
            continue
        st = e.stat(follow_symlinks=False)
        cat = scanner.category_of(ext)
        sub = FOLDER_NAMES.get(cat, "Khác")
        parts = [folder, sub]
        if by_year and cat in BY_YEAR:
            parts.append(time.strftime("%Y", time.localtime(st.st_mtime)))
        dest = _unique(os.path.join(*parts, e.name), taken)
        taken.add(os.path.normcase(dest))
        plan.append({
            "src": e.path, "dest": dest, "name": e.name, "category": cat,
            "target": os.path.relpath(os.path.dirname(dest), folder), "size": st.st_size,
            "renamed": os.path.basename(dest) != e.name,
        })
    summary: dict[str, dict] = {}
    for p in plan:
        s = summary.setdefault(p["target"], {"target": p["target"], "count": 0, "size": 0})
        s["count"] += 1
        s["size"] += p["size"]
    return {"folder": folder, "moves": plan, "summary": sorted(summary.values(), key=lambda x: -x["count"])}


def apply(folder: str, chosen: list[str], by_year: bool = True, cancel=None, progress=None, on_progress=None) -> dict:
    """Carry out the previewed moves for the chosen source files.

    The plan is computed again here, so only moves the preview would show can
    happen, whatever the caller sends.
    """
    fresh = preview(folder, by_year)
    wanted = {os.path.normcase(os.path.abspath(p)) for p in chosen}
    moves = [(m["src"], m["dest"]) for m in fresh["moves"] if os.path.normcase(m["src"]) in wanted]
    if not moves:
        raise ValueError("Chưa chọn file nào để sắp xếp")
    return quarantine.move_files(moves, f"Sắp xếp thư mục: {os.path.basename(fresh['folder']) or fresh['folder']}",
                                 cancel=cancel, progress=progress, on_progress=on_progress)
