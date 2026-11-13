"""Every text the user can see, as translation keys (the Vietnamese text).

Used by the tests (each key needs an English entry) and when translating:
    python tools/i18n_keys.py            # list keys that en.json is missing
    python tools/i18n_keys.py --all      # list every key
Sources: t("...") and Vietnamese string literals in web/app.js, _("...") and
Vietnamese string literals in the Python back end, data-i18n markup in index.html.
"""
from __future__ import annotations

import ast
import html
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "pccleaner"
WEB = PKG / "web"
VI = re.compile(r"[À-ÖØ-öø-ỹđĐ]")  # Latin letters with marks (not × or ÷)
# Vietnamese literals that are not shown to the user: file-name patterns and
# words matched in system messages.
NOT_TEXT = {"bản sao", "tải về", "hủy"}
JS_FILES = ["app.js"]


T_CALL = re.compile(r'\bt\(\s*"((?:[^"\\\n]|\\.)*)"')
# Lines holding canonical Vietnamese values that are shown through t() later.
JS_CANON = re.compile(r"^const (SELECTABLE|LABELS|GROUPS) = .*$", re.M)
JS_STR = re.compile(r'"((?:[^"\\\n]|\\.)*)"')


def js_keys() -> set[str]:
    keys = set()
    for name in JS_FILES:
        src = (WEB / name).read_text(encoding="utf-8")
        keys |= {json.loads('"' + m.group(1) + '"') for m in T_CALL.finditer(src)}
        for line in JS_CANON.finditer(src):
            keys |= {json.loads('"' + m.group(1) + '"') for m in JS_STR.finditer(line.group(0)) if VI.search(m.group(1))}
    return keys


def js_hardcoded() -> list[str]:
    """Vietnamese text in the UI code that does not go through t()."""
    bad = []
    for name in JS_FILES:
        src = JS_CANON.sub("", T_CALL.sub("", (WEB / name).read_text(encoding="utf-8")))
        bad += [f"{name}: {line.strip()[:120]}" for line in src.splitlines() if VI.search(line)]
    return bad


def _docstrings(tree) -> set[int]:
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                ids.add(id(body[0].value))
    return ids


def py_keys() -> set[str]:
    keys = set()
    for path in sorted(PKG.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        skip = _docstrings(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.JoinedStr):
                for v in node.values:
                    skip.add(id(v))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in skip:
                s = node.value
                if VI.search(s) and s not in NOT_TEXT and not s.startswith("(copy|"):
                    keys.add(s)
    return keys


def fstring_texts() -> list[str]:
    """Vietnamese f-strings in the back end: these cannot be translated."""
    bad = []
    for path in sorted(PKG.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.JoinedStr):
                text = "".join(v.value for v in node.values if isinstance(v, ast.Constant))
                if VI.search(text):
                    bad.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    return bad


class _Marked(HTMLParser):
    """Collects the keys applyI18n() reads: normalized innerHTML of data-i18n elements."""

    VOID = {"br", "img", "input", "meta", "link", "hr", "source", "wbr"}

    def __init__(self, src: str):
        super().__init__(convert_charrefs=False)
        self.src = src
        self.lines = [0]
        for line in src.splitlines(keepends=True):
            self.lines.append(self.lines[-1] + len(line))
        self.stack: list[tuple[str, bool, int]] = []
        self.keys: set[str] = set()
        self.feed(src)

    def _pos(self) -> int:
        line, col = self.getpos()
        return self.lines[line - 1] + col

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        for at in ("placeholder", "title", "aria-label"):
            if f"data-i18n-{at}" in a and a.get(at):
                self.keys.add(_norm(html.unescape(a[at])))
        if tag in self.VOID:
            return
        end = self._pos() + len(self.get_starttag_text())
        self.stack.append((tag, "data-i18n" in a, end))

    def handle_endtag(self, tag):
        while self.stack:
            t, marked, start = self.stack.pop()
            if t == tag:
                if marked:
                    # innerHTML as the browser serializes it: entities like &amp; stay escaped
                    self.keys.add(_norm(self.src[start:self._pos()]))
                return


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip())


def html_keys() -> set[str]:
    return _Marked((WEB / "index.html").read_text(encoding="utf-8")).keys


def all_keys() -> set[str]:
    return js_keys() | py_keys() | html_keys()


def missing(lang: str = "en") -> list[str]:
    d = json.loads((WEB / "i18n" / f"{lang}.json").read_text(encoding="utf-8"))
    return sorted(k for k in all_keys() if not d.get(k))


if __name__ == "__main__":
    if "--all" in sys.argv:
        print(json.dumps(sorted(all_keys()), ensure_ascii=False, indent=1))
    else:
        try:
            print(json.dumps(missing(), ensure_ascii=False, indent=1))
        except FileNotFoundError:
            print(json.dumps(sorted(all_keys()), ensure_ascii=False, indent=1))
    for f in fstring_texts():
        print("f-string with Vietnamese text:", f, file=sys.stderr)
    for f in js_hardcoded():
        print("not translated:", f, file=sys.stderr)
