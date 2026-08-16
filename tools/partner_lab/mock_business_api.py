# -*- coding: utf-8 -*-
"""
虾淘业务 API 模拟终端（订单/退款状态）— 供后续 SOP 联调，与 MITAKO 解耦
默认: http://127.0.0.1:9103

当前 MITAKO 主站仍用内置 mock_api；本服务供甲方对接演练与契约测试。
"""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

HOST = "127.0.0.1"
PORT = 9103

# 联调样例订单
_ORDERS = {
    "PT20240601001": {
        "order_id": "PT20240601001",
        "status": "shipped",
        "refund_eligible": False,
        "refund_status": "none",
        "logistics_status": "in_transit",
        "items": [{"name": "排球少年 吧唧", "qty": 1}],
    },
    "PT20240602002": {
        "order_id": "PT20240602002",
        "status": "pending_refund",
        "refund_eligible": True,
        "refund_status": "processing",
        "logistics_status": "not_shipped",
        "items": [{"name": "原神 手办", "qty": 1}],
    },
}


class BusinessHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"[MockBiz] {self.address_string()} {fmt % args}")

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self._json(200, {"ok": True, "service": "mock_business_api"})
            return
        if parsed.path.startswith("/api/v1/orders/"):
            oid = parsed.path.split("/")[-1]
            order = _ORDERS.get(oid)
            if not order:
                self._json(404, {"ok": False, "error": "order_not_found"})
                return
            self._json(200, {"ok": True, "order": order})
            return
        if parsed.path == "/api/v1/orders":
            qs = parse_qs(parsed.query)
            uid = (qs.get("user_id") or ["demo"])[0]
            self._json(200, {"ok": True, "user_id": uid, "orders": list(_ORDERS.values())})
            return
        self.send_error(404)

    def do_POST(self):
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length).decode("utf-8") if length else "{}"
        try:
            data = json.loads(body) if body else {}
        except json.JSONDecodeError:
            data = {}

        if parsed.path == "/api/v1/refund/card":
            oid = data.get("order_id", "")
            order = _ORDERS.get(oid, {})
            eligible = order.get("refund_eligible", False)
            self._json(200, {
                "ok": True,
                "order_id": oid,
                "card_available": eligible,
                "amount": 28.0 if eligible else 0,
                "message": "系统可发起退款卡片" if eligible else "不符合退款条件",
            })
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
    srv = HTTPServer((HOST, PORT), BusinessHandler)
    print(f"[MockBiz] listening http://{HOST}:{PORT}")
    srv.serve_forever()


if __name__ == "__main__":
    main()
