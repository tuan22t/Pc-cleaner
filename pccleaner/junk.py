"""System junk: temp files, caches, logs, crash dumps and update leftovers.

Every category is a fixed, well-known folder that the OS or the owning program
recreates on its own. Each one carries a label:

* ``safe``     – removing it never breaks anything; selected by default
* ``caution``  – safe, but has a small side effect (e.g. a slower first start);
                 not selected by default
Files are moved to quarantine like any other cleanup, so they can be restored.
"""
from __future__ import annotations

import fnmatch
import glob
import os
import threading
import time
from dataclasses import dataclass

from . import paths, platforms, quarantine
from .junk_base import SOURCES, Category  # noqa: F401 - Category is part of this module's API


@dataclass
class JunkProgress:
    stage: str = ""
    done: int = 0
    total: int = 0
    current: str = ""


def categories() -> list[Category]:
    """Every junk category of this computer, with its folders resolved."""
    platforms.load()
    cats: list[Category] = []
    for source in SOURCES:
        cats += source()
    for c in cats:
        roots: list[str] = []
        for pat in c.patterns:
            roots += [p for p in glob.glob(pat) if os.path.isdir(p) and not os.path.islink(p)
                      and not (c.skip_root and c.skip_root(os.path.basename(p)))]
        c.roots = roots
    return cats


def _iter_files(cat: Category, cancel: threading.Event | None = None):
    cutoff = time.time() - cat.min_age_hours * 3600
    data_dir = os.path.normcase(str(paths.data_dir()))
    for root in cat.roots:
        for dirpath, dirnames, filenames in os.walk(root, onerror=lambda e: None):
            if cancel is not None and cancel.is_set():
                raise InterruptedError
            if os.path.normcase(dirpath).startswith(data_dir):
                dirnames[:] = []
                continue
            dirnames[:] = [d for d in dirnames if not os.path.islink(os.path.join(dirpath, d))]
            for name in filenames:
                if cat.file_glob and not fnmatch.fnmatch(name.lower(), cat.file_glob.lower()):
                    continue
                full = os.path.join(dirpath, name)
                try:
                    st = os.lstat(full)
                except OSError:
                    continue
                if not os.path.isfile(full) or os.path.islink(full):
                    continue
                if not paths.IS_WINDOWS and st.st_uid != os.getuid():
                    continue  # never touch other users' files (e.g. in /tmp)
                if st.st_mtime > cutoff:
                    continue
                yield full, st.st_size


def scan(cancel: threading.Event | None = None, on_progress=None) -> list[dict]:
    out = []
    cats = categories()
    progress = JunkProgress(total=len(cats))
    for c in cats:
        progress.stage = c.name
        if on_progress:
            on_progress(progress)
        size = count = 0
        for _p, s in _iter_files(c, cancel):
            size += s
            count += 1
        out.append({
            "id": c.id, "name": c.name, "desc": c.desc, "label": c.label, "admin": c.admin,
            "size": size, "count": count, "selected": c.label == "safe" and count > 0,
            "locations": c.roots,
        })
        progress.done = len(out)
    return out


def clean(ids: list[str]) -> dict:
    """Move the files of the chosen categories into quarantine."""
    results = []
    total_moved = total_bytes = total_skipped = 0
    batch_ids = []
    for c in categories():
        if c.id not in ids:
            continue
        files = [p for p, _s in _iter_files(c)]
        if not files:
            continue
        r = quarantine.quarantine(files, f"Rác hệ thống: {c.name}", allow_roots=c.roots, log_failures=False)
        batch_ids.append(r["batch_id"])
        skipped = len(r["failed"])
        results.append({"id": c.id, "name": c.name, "moved": r["moved"], "bytes": r["bytes"], "skipped": skipped})
        total_moved += r["moved"]
        total_bytes += r["bytes"]
        total_skipped += skipped
    return {"categories": results, "moved": total_moved, "bytes": total_bytes, "skipped": total_skipped, "batch_ids": batch_ids}
