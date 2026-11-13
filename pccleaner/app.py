"""Entry point: opens the UI in a native window (pywebview) or, as a fallback, the browser."""
from __future__ import annotations

import argparse
import sys
import time
import webbrowser

from . import __version__
from . import server
from .server import start_server


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="pccleaner", description="Dọn dẹp máy tính")
    ap.add_argument("--browser", action="store_true", help="mở trong trình duyệt thay vì cửa sổ riêng")
    ap.add_argument("--headless", action="store_true", help="chỉ chạy máy chủ (dùng cho kiểm thử)")
    ap.add_argument("--port", type=int, default=0)
    args = ap.parse_args(argv)

    httpd, url, _token = start_server(args.port)
    print(f"PC Cleaner {__version__} đang chạy tại {url}", flush=True)

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
            print("Chưa cài pywebview, mở bằng trình duyệt.", file=sys.stderr)
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
