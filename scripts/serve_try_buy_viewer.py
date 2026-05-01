#!/usr/bin/env python3
"""Serve the Try & Buy results viewer locally."""

from __future__ import annotations

import argparse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Serve the Try & Buy web viewer.")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind. Default: 127.0.0.1")
    parser.add_argument("--port", default=8765, type=int, help="Port to bind. Default: 8765")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *handler_args, **handler_kwargs):
            super().__init__(*handler_args, directory=str(repo_root), **handler_kwargs)

        def do_GET(self) -> None:
            if self.path in ("/", "/viewer"):
                self.path = "/index.html"
            elif self.path in ("/list", "/list/"):
                self.path = "/list.html"
            super().do_GET()

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Serving Try & Buy viewer at http://{args.host}:{args.port}/viewer (list: /list)")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
