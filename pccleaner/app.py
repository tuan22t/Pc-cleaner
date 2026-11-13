"""Entry point: opens the UI in a native window (pywebview) or, as a fallback, the browser."""
from __future__ import annotations

import argparse
import sys
import time
import webbrowser

from . import __version__
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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="pccleaner", description="Dọn dẹp máy tính")
    ap.add_argument("--browser", action="store_true", help="mở trong trình duyệt thay vì cửa sổ riêng")
    ap.add_argument("--headless", action="store_true", help="chỉ chạy máy chủ (dùng cho kiểm thử)")
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--auto-clean", action="store_true", help="dọn dẹp tự động theo lịch rồi thoát")
    args = ap.parse_args(argv)

    if args.auto_clean:
        from . import scheduler

        _say(str(scheduler.run_auto_clean()))
        return 0

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
