"""Entry point: opens the UI in a native window (pywebview) or, as a fallback, the browser."""
from __future__ import annotations

import argparse
import sys
import threading
import time
import webbrowser

from . import __version__, paths
from . import server
from .server import start_server


def _say(msg: str, err: bool = False) -> None:
    # Packaged windowed apps have no console: sys.stdout/sys.stderr can be None.
    stream = sys.stderr if err else sys.stdout
    if stream is not None:
        try:
            print(msg, file=stream, flush=True)
        except (OSError, ValueError):
            pass


def _startup_recovery() -> None:
    """Settle anything a crash or power cut left half done (see quarantine.recover)."""
    from . import quarantine, scanner

    try:
        r = quarantine.recover()
        if any(r.values()):
            _say(f"Đã phục hồi sau lần tắt đột ngột: {r}")
        scanner.cleanup_unfinished()
    except Exception:  # noqa: BLE001 - recovery must never stop the app from opening
        server._log_exc()


def _schedule_self_check() -> None:
    from . import scheduler

    try:
        r = scheduler.self_check()
        if r.get("fixed"):
            _say("Đã cập nhật lịch dọn tự động theo vị trí mới của ứng dụng.")
    except Exception:  # noqa: BLE001
        server._log_exc()


def _already_running() -> None:
    msg = "PC Cleaner đang chạy rồi. Hãy dùng cửa sổ đang mở (hoặc đợi lượt dọn tự động chạy xong)."
    _say(msg, err=True)
    try:
        if paths.IS_WINDOWS:
            import ctypes

            ctypes.windll.user32.MessageBoxW(None, msg, "PC Cleaner", 0x40)
        elif paths.IS_MAC:
            import subprocess

            subprocess.run(["osascript", "-e", f'display alert "PC Cleaner" message "{msg}"'], timeout=60)
    except Exception:  # noqa: BLE001
        pass


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="pccleaner", description="Dọn dẹp máy tính")
    ap.add_argument("--browser", action="store_true", help="mở trong trình duyệt thay vì cửa sổ riêng")
    ap.add_argument("--headless", action="store_true", help="chỉ chạy máy chủ (dùng cho kiểm thử)")
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--auto-clean", action="store_true", help="dọn dẹp tự động theo lịch rồi thoát")
    args = ap.parse_args(argv)

    if args.auto_clean:
        from . import scheduler

        if not paths.acquire_instance_lock():
            # The app window is open: never move files from two processes at once.
            scheduler.record_skipped("Ứng dụng đang mở nên lượt dọn tự động này được bỏ qua")
            return 0
        _startup_recovery()
        _say(str(scheduler.run_auto_clean()))
        return 0

    if not paths.acquire_instance_lock():
        _already_running()
        return 1
    _startup_recovery()
    threading.Thread(target=_schedule_self_check, daemon=True).start()

    httpd, url, _token = start_server(args.port)
    _say(f"PC Cleaner {__version__} đang chạy tại {url}")

    if not args.browser and not args.headless:
        try:
            import webview  # type: ignore

            server.window = webview.create_window(
                "PC Cleaner – Dọn dẹp máy tính", url, width=1200, height=800, min_size=(900, 600)
            )
            webview.start()
            httpd.shutdown()
            return 0
        except ImportError:
            _say("Chưa cài pywebview, mở bằng trình duyệt.", err=True)
    if not args.headless:
        webbrowser.open(url)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        httpd.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
