"""Platform-specific locations and the list of folders the app must never modify."""
from __future__ import annotations

import os
import string
import sys
from pathlib import Path

IS_WINDOWS = sys.platform.startswith("win")
IS_MAC = sys.platform == "darwin"

APP_NAME = "PCCleaner"


def data_dir() -> Path:
    """Folder for the SQLite cache, quarantine and action log."""
    override = os.environ.get("PCCLEANER_DATA_DIR")
    if override:
        base = Path(override)
    elif IS_WINDOWS:
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / APP_NAME
    elif IS_MAC:
        base = Path.home() / "Library" / "Application Support" / APP_NAME
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / APP_NAME.lower()
    base.mkdir(parents=True, exist_ok=True)
    return base


def quarantine_dir() -> Path:
    q = data_dir() / "quarantine"
    q.mkdir(parents=True, exist_ok=True)
    return q


def _norm(p: str | os.PathLike) -> str:
    s = os.path.normcase(os.path.abspath(os.fspath(p)))
    return s.rstrip("\\/") or s


def protected_roots() -> list[str]:
    """Folders whose contents are never moved or deleted by the app."""
    home = Path.home()
    roots: list[str] = []
    if IS_WINDOWS:
        sysdrive = os.environ.get("SystemDrive", "C:") + "\\"
        for var, default in (
            ("SystemRoot", sysdrive + "Windows"),
            ("ProgramFiles", sysdrive + "Program Files"),
            ("ProgramFiles(x86)", sysdrive + "Program Files (x86)"),
            ("ProgramData", sysdrive + "ProgramData"),
        ):
            roots.append(os.environ.get(var, default))
        roots += [
            sysdrive + "$Recycle.Bin",
            sysdrive + "System Volume Information",
            sysdrive + "Recovery",
            str(home / "AppData"),
        ]
    elif IS_MAC:
        roots += [
            "/System", "/Library", "/Applications", "/usr", "/bin", "/sbin",
            "/private", "/etc", "/var", "/opt", "/cores",
            str(home / "Library"), str(home / "Applications"),
        ]
    else:
        roots += [
            "/bin", "/boot", "/dev", "/etc", "/lib", "/lib32", "/lib64", "/opt",
            "/proc", "/root", "/run", "/sbin", "/snap", "/srv", "/sys", "/usr", "/var",
        ]
    roots.append(str(data_dir()))
    return [_norm(r) for r in roots]


# Name of the quarantine folder the app creates at the root of other drives
# (D:, external disks) so that cleaning there never copies data to the system drive.
VOLUME_QUARANTINE = ".PCCleaner-quarantine"

# Folders that are one unit: removing a single file inside breaks the whole
# thing (a photo library, an app, a code repository), even when that file is a
# true duplicate. Matched on any path component, case-insensitively.
PACKAGE_SUFFIXES = {
    ".photoslibrary": "thư viện Ảnh (Photos)",
    ".photolibrary": "thư viện iPhoto",
    ".aplibrary": "thư viện Aperture",
    ".lrdata": "dữ liệu Lightroom",
    ".lrlibrary": "thư viện Lightroom",
    ".cocatalog": "thư viện Capture One",
    ".imovielibrary": "thư viện iMovie",
    ".fcpbundle": "thư viện Final Cut Pro",
    ".musiclibrary": "thư viện Nhạc",
    ".tvlibrary": "thư viện TV",
    ".logicx": "dự án Logic Pro",
    ".band": "dự án GarageBand",
    ".app": "ứng dụng",
    ".bundle": "gói ứng dụng",
    ".framework": "thư viện phần mềm",
    ".plugin": "phần bổ trợ",
    ".kext": "phần mở rộng hệ thống",
    ".pkg": "bộ cài",
    ".sparsebundle": "ổ đĩa ảo",
    ".xcodeproj": "dự án Xcode",
    ".xcworkspace": "dự án Xcode",
    ".rtfd": "tài liệu",
    ".pages": "tài liệu Pages",
    ".numbers": "bảng tính Numbers",
    ".key": "bản trình chiếu Keynote",
}
PACKAGE_NAMES = {
    ".git": "kho mã nguồn (git)",
    ".svn": "kho mã nguồn (svn)",
    ".hg": "kho mã nguồn (hg)",
    "node_modules": "thư viện lập trình",
    "site-packages": "thư viện Python",
    ".venv": "môi trường Python",
    "venv": "môi trường Python",
    "steamapps": "thư viện game Steam",
    "windowsapps": "ứng dụng Windows",
    VOLUME_QUARANTINE.lower(): "khu cách ly",
}


def package_reason(path: str | os.PathLike) -> str | None:
    """Name the package ``path`` sits in (photo library, app, repository), or None."""
    parts = _norm(path).replace("\\", "/").split("/")
    for part in parts[:-1] if len(parts) > 1 else []:
        low = part.lower()
        if low in PACKAGE_NAMES:
            return PACKAGE_NAMES[low]
        for suffix, label in PACKAGE_SUFFIXES.items():
            if low.endswith(suffix) and len(low) > len(suffix):
                return label
    return None


_cloud_cache: tuple[float, str, list] | None = None


def cloud_roots() -> list[tuple[str, str]]:
    """Folders kept in sync with an online service: removing a file there removes it everywhere."""
    global _cloud_cache
    import time

    home = Path.home()
    if _cloud_cache and _cloud_cache[1] == str(home) and time.time() - _cloud_cache[0] < 30:
        return _cloud_cache[2]
    result = _find_cloud_roots(home)
    _cloud_cache = (time.time(), str(home), result)
    return result


def _find_cloud_roots(home: Path) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for var in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        v = os.environ.get(var)
        if v:
            found.append((v, "OneDrive"))
    try:
        for child in home.iterdir():
            name = child.name
            if name.startswith("OneDrive"):
                found.append((str(child), "OneDrive"))
            elif name == "Dropbox" or name.startswith("Dropbox ("):
                found.append((str(child), "Dropbox"))
            elif name in ("Google Drive", "My Drive"):
                found.append((str(child), "Google Drive"))
            elif name in ("iCloudDrive", "iCloud Drive"):
                found.append((str(child), "iCloud Drive"))
            elif name == "Box":
                found.append((str(child), "Box"))
    except OSError:
        pass
    if IS_MAC:
        found.append((str(home / "Library" / "Mobile Documents"), "iCloud Drive"))
        cs = home / "Library" / "CloudStorage"
        if cs.is_dir():
            for child in cs.iterdir():
                found.append((str(child), child.name.split("-")[0] or "Đám mây"))
    return [(_norm(p), label) for p, label in found]


def cloud_name(path: str | os.PathLike) -> str | None:
    """The sync service a file belongs to (OneDrive, Dropbox…), or None."""
    p = _norm(path)
    for root, label in cloud_roots():
        if p == root or p.startswith(root + os.sep):
            return label
    return None


def protection_reason(path: str | os.PathLike) -> str | None:
    """Why the app must not move or delete ``path``; None if it may.

    Both the path as given and its fully resolved form are checked, so a
    symlink or junction that leads into a system folder cannot be used to
    reach files there.
    """
    roots = protected_roots()
    candidates = {_norm(path)}
    try:
        candidates.add(_norm(os.path.realpath(path)))
    except (OSError, ValueError):
        return "Không xác định được vị trí thật của file"
    for p in candidates:
        # Never touch a drive/volume root itself.
        if os.path.dirname(p) == p:
            return "Thư mục gốc của ổ đĩa"
        for root in roots:
            if p == root or p.startswith(root + os.sep):
                return "Thư mục hệ thống/chương trình được bảo vệ"
        pkg = package_reason(p)
        if pkg:
            return f"Nằm trong {pkg}: dọn riêng một file sẽ làm hỏng cả gói"
    return None


def file_flags(path: str | os.PathLike) -> dict:
    """What the UI needs to know before offering a file for cleanup."""
    why = protection_reason(path)
    return {"protected": why is not None, "why": why, "cloud": None if why else cloud_name(path)}


def is_protected(path: str | os.PathLike) -> bool:
    """True if ``path`` is, or lies inside, a protected folder or package."""
    return protection_reason(path) is not None


def volume_root(path: str | os.PathLike) -> str:
    """The root of the drive/volume holding ``path`` (C:\\, D:\\, /Volumes/USB, /)."""
    p = os.path.abspath(os.fspath(path))
    if IS_WINDOWS:
        drive = os.path.splitdrive(p)[0]
        return drive + "\\" if drive else p
    while not os.path.ismount(p):
        parent = os.path.dirname(p)
        if parent == p:
            break
        p = parent
    return p


def _device(path: str) -> int | None:
    try:
        return os.stat(path).st_dev
    except OSError:
        return None


def quarantine_dir_for(path: str | os.PathLike) -> Path:
    """Quarantine folder on the same drive as ``path``.

    Moving a file within one drive is a rename: instant, atomic, and it needs no
    extra space. Files on the system drive go to the app's data folder; files on
    other drives go to a hidden folder at that drive's root.
    """
    folder = os.path.dirname(os.path.abspath(os.fspath(path)))
    home_q = quarantine_dir()
    dev = _device(folder)
    if dev is not None and dev == _device(str(home_q)):
        return home_q
    q = Path(volume_root(folder)) / VOLUME_QUARANTINE
    q.mkdir(exist_ok=True)
    if IS_WINDOWS:
        try:
            import ctypes

            ctypes.windll.kernel32.SetFileAttributesW(str(q), 0x2)  # hidden
        except Exception:  # noqa: BLE001 - cosmetic only
            pass
    return q


_lock_handle = None


def acquire_instance_lock() -> bool:
    """Make sure only one copy of the app (window or scheduled run) works at a time.

    Returns False if another copy holds the lock. The lock is released by the
    operating system when this process ends, even after a crash.
    """
    global _lock_handle
    if _lock_handle is not None:
        return True
    f = open(data_dir() / "app.lock", "a+")
    try:
        if IS_WINDOWS:
            import msvcrt

            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.close()
        return False
    _lock_handle = f
    return True


def release_instance_lock() -> None:
    global _lock_handle
    if _lock_handle is not None:
        _lock_handle.close()
        _lock_handle = None


# Virtual or system-managed trees that the scanner skips entirely.
def skip_dirs() -> set[str]:
    if IS_WINDOWS:
        sysdrive = os.environ.get("SystemDrive", "C:") + "\\"
        return {_norm(sysdrive + "System Volume Information"), _norm(sysdrive + "$Recycle.Bin")}
    if IS_MAC:
        return {_norm(p) for p in ("/System/Volumes", "/Volumes", "/dev", "/private/var/vm", "/.Spotlight-V100", "/.fseventsd")}
    return {_norm(p) for p in ("/proc", "/sys", "/dev", "/run", "/snap")}


def list_locations() -> list[dict]:
    """Drives / volumes plus the home folder, with free space."""
    import shutil

    locs: list[dict] = []
    candidates: list[tuple[str, str]] = [(str(Path.home()), "Thư mục cá nhân")]
    if IS_WINDOWS:
        for letter in string.ascii_uppercase:
            root = f"{letter}:\\"
            if os.path.exists(root):
                candidates.append((root, f"Ổ {letter}:"))
    elif IS_MAC:
        candidates.append(("/", "Macintosh HD"))
        if os.path.isdir("/Volumes"):
            for name in sorted(os.listdir("/Volumes")):
                full = os.path.join("/Volumes", name)
                if os.path.ismount(full) and os.path.realpath(full) != "/":
                    candidates.append((full, name))
    else:
        candidates.append(("/", "Hệ thống (/)"))
    for path, label in candidates:
        try:
            du = shutil.disk_usage(path)
        except OSError:
            continue
        locs.append({"path": path, "label": label, "total": du.total, "used": du.used, "free": du.free})
    return locs
