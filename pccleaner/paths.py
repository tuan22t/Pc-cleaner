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


def is_protected(path: str | os.PathLike) -> bool:
    """True if ``path`` is, or lies inside, a protected folder.

    Both the path as given and its fully resolved form are checked, so a
    symlink or junction that leads into a system folder cannot be used to
    reach files there.
    """
    roots = protected_roots()
    candidates = {_norm(path)}
    try:
        candidates.add(_norm(os.path.realpath(path)))
    except (OSError, ValueError):
        return True
    for p in candidates:
        # Never touch a drive/volume root itself.
        if os.path.dirname(p) == p:
            return True
        for root in roots:
            if p == root or p.startswith(root + os.sep):
                return True
    return False


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
