"""Lists Vietnamese strings passed to tr('...') that have no English entry
in assets/i18n/en.json (same idea as the desktop tools/i18n_keys.py).
Usage: python tool/i18n_keys.py [--json]  -> prints missing keys."""
import json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAT = re.compile(r"""tr\(\s*'((?:[^'\\]|\\.)*)'""")

def keys():
    out = []
    for f in sorted((ROOT / "lib").rglob("*.dart")):
        for m in PAT.finditer(f.read_text(encoding="utf-8")):
            k = m.group(1).replace("\\'", "'")
            if k not in out:
                out.append(k)
    return out

if __name__ == "__main__":
    en = json.loads((ROOT / "assets/i18n/en.json").read_text(encoding="utf-8"))
    missing = [k for k in keys() if k not in en]
    if "--json" in sys.argv:
        print(json.dumps({k: "" for k in missing}, ensure_ascii=False, indent=1))
    else:
        print("\n".join(missing))
    sys.exit(1 if missing else 0)
