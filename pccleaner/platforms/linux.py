"""Linux: only used while developing; never cleaned for real by the tests."""
from __future__ import annotations

import os
from pathlib import Path

from ..junk_base import Category, register_source


@register_source
def junk_categories() -> list[Category]:
    home = str(Path.home())
    cats: list[Category] = []
    cats += [
        Category("linux_cache", "Bộ nhớ đệm", "~/.cache", [os.path.join(home, ".cache")]),
        Category("linux_tmp", "File tạm", "/tmp (chỉ file của bạn)", ["/tmp"]),
    ]
    return cats
