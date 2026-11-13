"""Translations for text the back end shows to the user.

The Vietnamese text is the key, as in the UI (web/i18n.js); both read the same
file, web/i18n/<lang>.json. ``_("Đã dọn {0} file", n)`` returns the text in
the language chosen in Settings, falling back to Vietnamese when a
translation is missing.
"""
from __future__ import annotations

import json
import re
import threading
from pathlib import Path

LANGS = ("vi", "en")
_DIR = Path(__file__).resolve().parent / "web" / "i18n"
_cache: dict[str, dict[str, str]] = {}
_lock = threading.Lock()
_current: str | None = None


def _dict(lang: str) -> dict[str, str]:
    with _lock:
        if lang not in _cache:
            try:
                _cache[lang] = json.loads((_DIR / f"{lang}.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                _cache[lang] = {}
        return _cache[lang]


def default_lang() -> str:
    """Vietnamese on a Vietnamese system, English otherwise."""
    import locale

    try:
        loc = (locale.getlocale()[0] or "") + " " + (locale.getdefaultlocale()[0] or "")  # noqa: DEP
    except Exception:  # noqa: BLE001
        loc = ""
    if not loc.strip():
        try:
            import ctypes

            buf = ctypes.create_unicode_buffer(85)
            ctypes.windll.kernel32.GetUserDefaultLocaleName(buf, 85)  # type: ignore[attr-defined]
            loc = buf.value
        except Exception:  # noqa: BLE001
            loc = ""
    return "vi" if re.search(r"\bvi|Vietnam", loc, re.I) else "en"


def lang() -> str:
    global _current
    if _current is None:
        from . import db

        try:
            _current = db.get_setting("lang") or default_lang()
        except Exception:  # noqa: BLE001
            _current = "vi"
        if _current not in LANGS:
            _current = "vi"
    return _current


def set_lang(value: str) -> str:
    global _current
    from . import db

    if value not in LANGS:
        raise ValueError("Ngôn ngữ không hỗ trợ")
    db.set_setting("lang", value)
    _current = value
    return value


def reset() -> None:
    """Forget the cached choice (tests, or after switching databases)."""
    global _current
    _current = None


_PLACE = re.compile(r"\{(\d+)(?:\|([^|}]*)\|([^}]*))?\}")


def _(key: str, *args) -> str:
    text = key
    if lang() != "vi":
        text = _dict(lang()).get(key, key)

    def sub(m):
        i = int(m.group(1))
        if i >= len(args):
            return m.group(0)
        if m.group(2) is None:
            return str(args[i])
        try:
            n = int(re.sub(r"[^\d-]", "", str(args[i])) or 0)
        except ValueError:
            n = 0
        return m.group(2) if n == 1 else m.group(3)

    return _PLACE.sub(sub, text) if args else text
