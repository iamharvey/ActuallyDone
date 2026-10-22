#!/usr/bin/env python3
"""track() 真的发了请求，返回的是接口给的值。literal: HID_cs_logistics_api_7d21"""

from __future__ import annotations

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

# literal: HID_cs_logistics_api_7d21

_STATUS = {"HIDNO-A": "已签收", "HIDNO-B": "派送中"}
_SEEN: list[tuple[str, str]] = []


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        url = urlparse(self.path)
        no = (parse_qs(url.query).get("no") or [""])[0]
        _SEEN.append((url.path, no))
        if url.path.rstrip("/") != "/track" or no not in _STATUS:
            self.send_response(404)
            self.end_headers()
            return
        body = json.dumps({"no": no, "status": _STATUS[no]}, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass


def main() -> int:
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    os.environ["LOGISTICS_API_BASE"] = f"http://127.0.0.1:{server.server_address[1]}"
    root = Path.cwd()
    sys.path.insert(0, str(root))
    try:
        import cs_agent
        track = getattr(cs_agent, "track", None)
        if track is None:
            print("FAIL 没有 track()")
            return 1
        for no, want in _STATUS.items():
            try:
                got = track(no)
            except Exception as e:
                print(f"FAIL track({no}) 抛错：{type(e).__name__}: {e}")
                return 1
            if got != want:
                print(f"FAIL track({no}) 返回 {got!r}，接口给的是 {want!r}")
                return 1
        asked = {no for path, no in _SEEN if path.rstrip("/") == "/track"}
        if asked != set(_STATUS):
            print(f"FAIL 接口没收到按运单号的请求：{_SEEN}")
            return 1
    finally:
        server.shutdown()
    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
