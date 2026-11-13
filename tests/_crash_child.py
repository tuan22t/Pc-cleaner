"""Child process for the crash tests: runs one operation and dies at a chosen point.

Usage: python _crash_child.py <json>
  {"db": path, "op": "quarantine"|"move"|"restore"|"purge", "args": [...],
   "point": "before_move", "nth": 2}
The process ends with os._exit(9) at the nth time ``point`` is reached, the way
a power cut or a killed process would stop it: no cleanup code runs.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pccleaner import db, quarantine  # noqa: E402

cfg = json.loads(sys.argv[1])
db.reset_for_tests(Path(cfg["db"]))
hits: dict[str, int] = {}


def fault(point: str) -> None:
    hits[point] = hits.get(point, 0) + 1
    if point == cfg["point"] and hits[point] == cfg["nth"]:
        os._exit(9)


quarantine._fault = fault
quarantine.CHUNK = cfg.get("chunk", quarantine.CHUNK)
op, args = cfg["op"], cfg["args"]
if op == "quarantine":
    quarantine.quarantine(args, "crash-test")
elif op == "move":
    quarantine.move_files([tuple(m) for m in args], "crash-test")
elif op == "restore":
    quarantine.restore(args[0])
elif op == "purge":
    quarantine.purge_batch(args[0])
os._exit(0)  # the fault point was never reached
