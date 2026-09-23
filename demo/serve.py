"""零依赖启动 TRACER 静态演示；不会调用模型 API。"""

from __future__ import annotations

import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading
import webbrowser


DEMO_ROOT = Path(__file__).resolve().parent


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port 必须位于 1 到 65535")

    server = ThreadingHTTPServer(
        (args.host, args.port),
        partial(SimpleHTTPRequestHandler, directory=str(DEMO_ROOT)),
    )
    url = f"http://{args.host}:{args.port}/"
    print(f"TRACER demo: {url}")
    print("按 Ctrl+C 停止。演示只读取本地静态文件，不调用模型 API。")
    if not args.no_browser:
        threading.Timer(0.35, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
