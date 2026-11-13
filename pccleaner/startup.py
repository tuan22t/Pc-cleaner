"""Programs that start with the computer or keep running in the background.

Rules agreed for this feature:
* items are only ever *disabled*, never uninstalled or deleted;
* every change can be turned back on with one click;
* on Windows, a System Restore point is offered before changes that need
  administrator rights;
* each item gets a recommendation: "safe" (có thể tắt), "keep" (nên giữ) or
  "unknown" (chưa rõ).

Windows: Run keys and Startup folders (disabled the same way Task Manager does,
through the StartupApproved registry keys), non-Microsoft scheduled tasks, and
non-Microsoft services set to start automatically (switched to Manual).
macOS: Login Items, LaunchAgents and LaunchDaemons (via ``launchctl disable``).
"""
from __future__ import annotations

from . import db, paths, platforms
from .platforms.common import _ps, _ps_admin, _run, is_admin  # noqa: F401 - re-exported
from .i18n import _
from .startup_base import (  # noqa: F401 - re-exported
    KEEP_WORDS, PROVIDERS, SAFE_WORDS, Provider, _change, _close_change, _discard_change, _log_change, classify,
    history, register_provider,
)

_os = platforms.load()
if paths.IS_WINDOWS:
    RUN, RUN32, APPROVED = _os.RUN, _os.RUN32, _os.APPROVED
if paths.IS_MAC:
    _SAFE_LABEL = _os._SAFE_LABEL
    _mac_login_items = _os._mac_login_items
else:
    import re as _re

    _SAFE_LABEL = _re.compile(r"^[A-Za-z0-9._@+-]{1,200}$")  # same rule, so it is tested everywhere


def create_restore_point() -> dict:
    """Windows only: create a System Restore point (asks for administrator rights)."""
    if not paths.IS_WINDOWS:
        return {"ok": False, "error": _("Chỉ có trên Windows. Trên macOS hãy dùng Time Machine.")}
    return _os.create_restore_point()


def list_items() -> list[dict]:
    items: list[dict] = []
    for p in PROVIDERS:
        for it in p.list_items():
            it["provider"] = p.name
            items.append(it)
    disabled_by_us = {r["item_id"] for r in db.connect().execute("SELECT item_id FROM startup_changes WHERE active=1")}
    for it in items:
        it["changed_by_app"] = it["id"] in disabled_by_us
    order = {"safe": 0, "unknown": 1, "keep": 2}
    items.sort(key=lambda i: (not i["enabled"], order.get(i["label"], 3), i["name"].lower()))
    return items


def set_enabled(item_id: str, enable: bool) -> dict:
    """Turn one item off or back on. Only items found in the current listing are accepted.

    When turning off, the record of how to turn it back on is saved *before*
    the change, so a crash in between can never leave an item off with no way
    back from the app.
    """
    item = next((i for i in list_items() if i["id"] == item_id), None)
    if item is None:
        raise KeyError(item_id)
    if item["enabled"] == enable:
        return {"ok": True, "unchanged": True}
    provider = next(p for p in PROVIDERS if p.name == item["provider"])
    if enable:
        provider.set_enabled(item, True)
        _close_change(item_id)
        return {"ok": True}
    original = {"enabled": item["enabled"], "command": item.get("command")}
    if item["kind"] == "login":
        li = next((x for x in _os._mac_login_items() if x.get("name") == item["name"]), {})
        original.update(path=li.get("path"), hidden=li.get("hidden"))
    _log_change(item, original)
    try:
        provider.set_enabled(item, False)
    except Exception:
        _discard_change(item_id)
        raise
    return {"ok": True}
