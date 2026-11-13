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
from dataclasses import dataclass, field
from pathlib import Path

from . import paths, quarantine


@dataclass
class JunkProgress:
    stage: str = ""
    done: int = 0
    total: int = 0
    current: str = ""


@dataclass
class Category:
    id: str
    name: str
    desc: str
    patterns: list[str]          # folders (glob allowed) whose files are junk
    label: str = "safe"          # safe | caution
    min_age_hours: float = 24    # skip files changed more recently (likely in use)
    file_glob: str | None = None  # only files matching this name pattern
    admin: bool = False           # usually needs administrator rights
    roots: list[str] = field(default_factory=list)


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def categories() -> list[Category]:
    home = str(Path.home())
    cats: list[Category] = []
    if paths.IS_WINDOWS:
        local = _env("LOCALAPPDATA", os.path.join(home, "AppData", "Local"))
        windir = _env("SystemRoot", r"C:\Windows")
        progdata = _env("ProgramData", r"C:\ProgramData")
        temp = _env("TEMP", os.path.join(local, "Temp"))
        cats += [
            Category("win_user_temp", "File tạm của người dùng", "Thư mục Temp: chương trình tạo ra khi cài đặt, giải nén, xem trước file… rồi bỏ lại.", [temp]),
            Category("win_temp", "File tạm của Windows", "Thư mục Windows\\Temp.", [os.path.join(windir, "Temp")], admin=True),
            Category("win_update", "Bản cập nhật Windows đã tải về", "Bộ cài cập nhật đã cài xong; Windows sẽ tải lại nếu cần.", [os.path.join(windir, "SoftwareDistribution", "Download")], min_age_hours=72, admin=True),
            Category("win_dumps", "File báo lỗi (crash dump)", "Bản ghi bộ nhớ khi chương trình hoặc Windows bị lỗi. Chỉ cần khi gửi cho kỹ thuật viên.", [os.path.join(local, "CrashDumps"), os.path.join(windir, "Minidump"), os.path.join(windir, "LiveKernelReports")], min_age_hours=0),
            Category("win_wer", "Báo cáo lỗi Windows", "Báo cáo lỗi đã gửi hoặc chờ gửi cho Microsoft.", [os.path.join(local, "Microsoft", "Windows", "WER"), os.path.join(progdata, "Microsoft", "Windows", "WER")], min_age_hours=0),
            Category("win_thumbs", "Bộ nhớ đệm ảnh thu nhỏ", "Ảnh thu nhỏ trong File Explorer; Windows tự tạo lại khi mở thư mục.", [os.path.join(local, "Microsoft", "Windows", "Explorer")], file_glob="thumbcache_*.db", min_age_hours=0),
            Category("browser_cache", "Bộ nhớ đệm trình duyệt", "Chrome, Edge, Firefox, Cốc Cốc. Không mất mật khẩu, lịch sử hay dấu trang. Nên đóng trình duyệt trước.", [
                os.path.join(local, "Google", "Chrome", "User Data", "*", d) for d in ("Cache", "Code Cache", "GPUCache")
            ] + [
                os.path.join(local, "Microsoft", "Edge", "User Data", "*", d) for d in ("Cache", "Code Cache", "GPUCache")
            ] + [
                os.path.join(local, "CocCoc", "Browser", "User Data", "*", d) for d in ("Cache", "Code Cache", "GPUCache")
            ] + [os.path.join(local, "Mozilla", "Firefox", "Profiles", "*", "cache2")], min_age_hours=1),
            Category("win_prefetch", "Prefetch", "Dữ liệu giúp Windows mở chương trình nhanh hơn. Xóa thì lần mở đầu tiên sẽ chậm hơn một chút.", [os.path.join(windir, "Prefetch")], label="caution", min_age_hours=0, admin=True),
        ]
    elif paths.IS_MAC:
        lib = os.path.join(home, "Library")
        cats += [
            Category("mac_caches", "Bộ nhớ đệm ứng dụng", "~/Library/Caches: dữ liệu tạm các ứng dụng tự tạo lại. Không mất tài liệu hay cài đặt.", [os.path.join(lib, "Caches")]),
            Category("mac_logs", "Nhật ký ứng dụng", "~/Library/Logs: file ghi hoạt động của ứng dụng.", [os.path.join(lib, "Logs")], min_age_hours=24),
            Category("mac_crash", "Báo cáo lỗi", "Báo cáo khi ứng dụng bị treo hoặc thoát đột ngột.", [os.path.join(lib, "Logs", "DiagnosticReports"), os.path.join(lib, "Application Support", "CrashReporter")], min_age_hours=0),
            Category("mac_xcode", "Dữ liệu tạm của Xcode", "DerivedData và bản lưu trữ thiết bị cũ của lập trình viên.", [os.path.join(lib, "Developer", "Xcode", "DerivedData"), os.path.join(lib, "Developer", "Xcode", "iOS DeviceSupport")], label="caution", min_age_hours=24),
        ]
    else:
        cats += [
            Category("linux_cache", "Bộ nhớ đệm", "~/.cache", [os.path.join(home, ".cache")]),
            Category("linux_tmp", "File tạm", "/tmp (chỉ file của bạn)", ["/tmp"]),
        ]
    for c in cats:
        roots: list[str] = []
        for pat in c.patterns:
            roots += [p for p in glob.glob(pat) if os.path.isdir(p) and not os.path.islink(p)]
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
