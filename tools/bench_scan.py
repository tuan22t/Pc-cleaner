"""Benchmark: first scan vs. rescan of a folder with many files.

Usage: python tools/bench_scan.py [files=100000] [min_ratio=3] [rounds=3]
Set BENCH_COLD=1 (Linux, root) to start both scans with an empty file cache.
Creates the files in a temporary folder (removed afterwards), scans it twice
and exits with status 1 if, in the slowest of the rounds, the rescan is not at least ``min_ratio`` times faster.
"""
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path


def drop_caches() -> None:
    """Linux and root only: forget cached file data, as after a restart (both scans start cold)."""
    if os.environ.get("BENCH_COLD") and sys.platform.startswith("linux"):
        os.sync()
        with open("/proc/sys/vm/drop_caches", "w") as fh:
            fh.write("3")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

N = int(sys.argv[1]) if len(sys.argv) > 1 else 100_000
MIN_RATIO = float(sys.argv[2]) if len(sys.argv) > 2 else 3.0
ROUNDS = int(sys.argv[3]) if len(sys.argv) > 3 else 3
PER_DIR = 100

work = Path(tempfile.mkdtemp(prefix="pcc-bench-"))
os.environ["PCCLEANER_DATA_DIR"] = str(work / "data")
from pccleaner import db, scanner  # noqa: E402

try:
    import random

    rng = random.Random(1)
    root = work / "tree"
    t = time.perf_counter()
    for i in range(N // PER_DIR):
        d = root / f"g{i // 50}" / f"d{i}"
        d.mkdir(parents=True)
        for j in range(PER_DIR):
            # Sparse files with a realistic spread of sizes (most small, about 1 in 5
            # over 64 KB); they take no real disk space.
            with open(d / f"f{j}.dat", "wb") as fh:
                fh.truncate(int(rng.lognormvariate(9.5, 2.2)))
    old = time.time() - 3600
    for dpath, _s, _f in os.walk(root):
        os.utime(dpath, (old, old))
    print(f"created {N} files in {time.perf_counter() - t:.1f}s")
    db.reset_for_tests(work / "bench.sqlite3")

    ok, worst = True, None
    for rnd in range(ROUNDS):
        drop_caches()
        t = time.perf_counter()
        first = scanner.scan(str(root), incremental=False, prune=False)
        t_full = time.perf_counter() - t
        scanner.prune_scans(str(root))
        # One folder changes between the scans, as in real use.
        (root / "g0" / "d0" / f"new{rnd}.dat").write_bytes(b"new")
        p = scanner.ScanProgress()
        drop_caches()
        t = time.perf_counter()
        second = scanner.scan(str(root), progress=p, prune=False)
        t_inc = time.perf_counter() - t
        # As in the app: old scans are pruned after the result is shown, not while the user waits.
        scanner.prune_scans(str(root))

        conn = db.connect()
        a = conn.execute("SELECT file_count FROM scans WHERE id=?", (first,)).fetchone()[0]
        b = conn.execute("SELECT file_count FROM scans WHERE id=?", (second,)).fetchone()[0]
        ratio = t_full / t_inc
        worst = ratio if worst is None else min(worst, ratio)
        print(f"round {rnd + 1}: first scan {t_full:.2f}s ({a} files), rescan {t_inc:.2f}s "
              f"({b} files, {p.reused_dirs} folders reused): {ratio:.1f}x")
        ok = ok and b == a + 1
    print(f"slowest round: rescan is {worst:.1f}x faster (needed: {MIN_RATIO}x)")
    ok = ok and worst >= MIN_RATIO
    print("PASS" if ok else "FAIL")
finally:
    shutil.rmtree(work, ignore_errors=True)
sys.exit(0 if ok else 1)
