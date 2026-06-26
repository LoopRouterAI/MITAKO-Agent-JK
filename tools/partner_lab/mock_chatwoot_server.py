# -*- coding: utf-8 -*-
"""
Chatwoot API 模拟终端 — 独立进程
默认: http://127.0.0.1:9102

MITAKO 设 CHATWOOT_MOCK=0 且 CHATWOOT_BASE_URL=http://127.0.0.1:9102 时走 Live 路径到此模拟器。
"""
from __future__ import annotations

import json
import re
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

HOST = "127.0.0.1"
PORT = 9102

_log_lock = threading.Lock()
_events: list[dict] = []
_conv_seq = 1000


class ChatwootHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"[MockChatwoot] {self.address_string()} {fmt % args}")

    def do_GET(self):
        m = re.match(r"^/api/v1/accounts/(\d+)$", self.path)
        if m:
            self._json(200, {"id": int(m.group(1)), "name": "Partner Lab Inbox"})
            return
        if self.path in ("/", "/health"):
            self._json(200, {"ok": True, "service": "mock_chatwoot", "events": len(_events)})
            return
        if self.path == "/events":
            with _log_lock:
                self._json(200, {"ok": True, "events": list(_events)})
            return
        self.send_error(404)

    def do_POST(self):
        global _conv_seq
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length).decode("utf-8") if length else "{}"
        try:
            data = json.loads(body) if body else {}
        except json.JSONDecodeError:
            data = {}

        m_conv = re.match(r"^/api/v1/accounts/(\d+)/conversations$", self.path)
        if m_conv:
            _conv_seq += 1
            ev = {"type": "conversation_created", "account_id": m_conv.group(1), "payload": data, "conversation_id": _conv_seq}
            with _log_lock:
                _events.append(ev)
            self._json(200, {"id": _conv_seq, "conversation_id": _conv_seq})
            return

        m_msg = re.match(r"^/api/v1/accounts/(\d+)/conversations/(\d+)/messages$", self.path)
        if m_msg:
            ev = {"type": "message", "account_id": m_msg.group(1), "conversation_id": m_msg.group(2), "payload": data}
            with _log_lock:
                _events.append(ev)
            self._json(200, {"id": len(_events), "content": data.get("content", "")})
            return

        self.send_error(404)

    def _json(self, code: int, obj: dict):
        raw = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def main():
    srv = HTTPServer((HOST, PORT), ChatwootHandler)
    print(f"[MockChatwoot] listening http://{HOST}:{PORT}")
    print(f"[MockChatwoot] event log: GET http://{HOST}:{PORT}/events")
    srv.serve_forever()


if __name__ == "__main__":
    main()
