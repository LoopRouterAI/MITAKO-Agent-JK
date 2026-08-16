# -*- coding: utf-8 -*-
"""
甲方 IdP 模拟终端 — 独立进程，不 import MITAKO 业务代码
默认: http://127.0.0.1:9101

模拟 OIDC:
  GET  /oauth/authorize  -> 302 redirect_uri?code=lab_oidc_code&state=
  POST /oauth/token      -> access_token
  GET  /oauth/userinfo   -> sub + groups（供 MITAKO map 角色）
"""
from __future__ import annotations

import json
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer

HOST = "127.0.0.1"
PORT = 9101


class IdPHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"[MockIdP] {self.address_string()} {fmt % args}")

    def do_GET(self):
        path = urllib.parse.urlparse(self.path)
        if path.path == "/oauth/authorize":
            qs = urllib.parse.parse_qs(path.query)
            redirect_uri = (qs.get("redirect_uri") or [""])[0]
            state = (qs.get("state") or [""])[0]
            if not redirect_uri:
                self.send_error(400, "missing redirect_uri")
                return
            sep = "&" if "?" in redirect_uri else "?"
            loc = f"{redirect_uri}{sep}code=lab_oidc_code&state={urllib.parse.quote(state)}"
            self.send_response(302)
            self.send_header("Location", loc)
            self.end_headers()
            return
        if path.path == "/oauth/userinfo":
            auth = self.headers.get("Authorization", "")
            if not auth.startswith("Bearer "):
                self.send_error(401, "need bearer")
                return
            body = {
                "sub": "lab_sso_user",
                "email": "lab@partner.local",
                "name": "联调测试用户",
                "groups": ["mitako-desk", "mitako-admin"],
            }
            self._json(200, body)
            return
        if path.path in ("/", "/health"):
            self._json(200, {"ok": True, "service": "mock_idp", "port": PORT})
            return
        self.send_error(404)

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        if path == "/oauth/token":
            self._json(200, {
                "access_token": "lab_access_token_mock",
                "token_type": "Bearer",
                "expires_in": 3600,
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
    srv = HTTPServer((HOST, PORT), IdPHandler)
    print(f"[MockIdP] listening http://{HOST}:{PORT}")
    srv.serve_forever()


if __name__ == "__main__":
    main()
