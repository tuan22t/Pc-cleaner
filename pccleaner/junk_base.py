"""Building blocks for system-junk categories, shared by the core and the platform modules."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Callable

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
    skip_root: object = None      # optional test(folder name) -> True to leave that folder alone

# Each source returns the junk categories of one platform or one app.
SOURCES: list[Callable[[], list[Category]]] = []


def register_source(fn: Callable[[], list[Category]]) -> Callable[[], list[Category]]:
    if fn not in SOURCES:
        SOURCES.append(fn)
    return fn


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)
