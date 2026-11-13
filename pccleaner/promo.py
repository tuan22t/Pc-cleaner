"""The businesses that sponsor the free app, shown in a small "Introducing" area.

The list ships with the app (web/promo/promo.json) and changes only with an
update. Nothing is tracked or sent: a link opens in the user's own browser only
when they click it. Website links carry utm_source=pccleaner so the sponsor can
see in their own web statistics how many visitors came from the app.
"""
from __future__ import annotations

import json
import webbrowser
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .i18n import _

KINDS = ("website", "maps", "facebook")


def _dir() -> Path:
    from .server import WEB_DIR

    return WEB_DIR / "promo"


def _load() -> dict:
    try:
        return json.loads((_dir() / "promo.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"places": []}


def with_utm(url: str, place_id: str) -> str:
    parts = urlsplit(url)
    q = [(k, v) for k, v in parse_qsl(parts.query) if not k.startswith("utm_")]
    q += [("utm_source", "pccleaner"), ("utm_medium", "app"), ("utm_campaign", place_id)]
    return urlunsplit(parts._replace(query=urlencode(q)))


def places() -> dict:
    data = _load()
    out = []
    for p in data.get("places", []):
        img = p.get("image")
        out.append({
            "id": p["id"], "name": p["name"], "tagline": p.get("tagline", {}), "address": p.get("address", ""),
            "phone": p.get("phone", ""), "links": [k for k in KINDS if k in p.get("links", {})], "icon": p.get("icon", ""),
            "image": f"promo/{img}" if img and (_dir() / img).is_file() else None,
        })
    return {"sponsor": data.get("sponsor", {}), "places": out}


def link(place_id: str, kind: str) -> str:
    """The address behind a button. Only addresses from the shipped list can be opened."""
    for p in _load().get("places", []):
        if p["id"] == place_id and kind in KINDS and kind in p.get("links", {}):
            url = p["links"][kind]
            if not url.startswith("https://"):
                break
            return with_utm(url, place_id) if kind == "website" else url
    raise ValueError(_("Không tìm thấy liên kết"))


def open_link(place_id: str, kind: str) -> dict:
    webbrowser.open(link(place_id, kind))
    return {"ok": True}
