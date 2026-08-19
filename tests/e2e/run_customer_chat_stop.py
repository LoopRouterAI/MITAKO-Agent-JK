# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from urllib.request import urlopen

from websockets.sync.client import connect

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_until(predicate, timeout: float = 3.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("等待条件超时")


def main() -> int:
    if not (ROOT / "dist" / "index.html").exists():
        raise AssertionError("请先运行 npm run build")

    with tempfile.TemporaryDirectory(prefix="mitako-chat-stop-") as temp_dir:
        os.environ.update({
            "MITAKO_HANDOFF_DB_PATH": str(Path(temp_dir) / "handoff.db"),
            "MITAKO_AUTH_REQUIRED": "0",
            "MITAKO_PROTECTED_API_AUTH_REQUIRED": "0",
            "MITAKO_DEV_AUTH_BYPASS": "1",
            "MITAKO_JWT_SECRET": "task9-browser-e2e-secret-20260818",
            "HANDOFF_BACKEND": "sqlite",
        })

        import handoff_store
        import main as app_main
        import uvicorn
        condition = threading.Condition()
        counters = {"started": 0, "cancelled": 0}

        async def blocking_agent(state: dict, config: dict) -> dict:
            with condition:
                counters["started"] += 1
                condition.notify_all()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                queue = config.get("configurable", {}).get("event_queue")
                if queue:
                    await queue.put({"type": "text_chunk", "content": "旧流污染"})
                with condition:
                    counters["cancelled"] += 1
                    condition.notify_all()
                raise

        app_main.agent_app.ainvoke = blocking_agent
        app_main.CHAT_TURN_TIMEOUT_SECONDS = 10.0
        port = _free_port()
        server = uvicorn.Server(uvicorn.Config(
            app_main.app,
            host="127.0.0.1",
            port=port,
            log_level="error",
        ))
        server_thread = threading.Thread(target=server.run, daemon=True)
        server_thread.start()
        base = f"http://127.0.0.1:{port}"
        _wait_until(lambda: _server_ready(base), timeout=10.0)

        try:
            _run_edge_suite(base, condition, counters, handoff_store)
        finally:
            server.should_exit = True
            server_thread.join(timeout=5.0)

    print("客服聊天停止浏览器 E2E 通过：桌面与 390px 均完成 Abort、服务端取消、立即重发和旧流隔离")
    return 0


def _server_ready(base: str) -> bool:
    try:
        with urlopen(f"{base}/", timeout=0.5) as response:
            return response.status == 200
    except Exception:
        return False


def _wait_counter(
    condition: threading.Condition,
    counters: dict[str, int],
    key: str,
    expected: int,
    timeout: float = 2.0,
) -> None:
    deadline = time.time() + timeout
    with condition:
        while counters[key] < expected:
            remaining = deadline - time.time()
            if remaining <= 0:
                raise AssertionError(f"{key} 未达到 {expected}，当前 {counters[key]}")
            condition.wait(remaining)


class _Cdp:
    def __init__(self, websocket_url: str) -> None:
        self.connection = connect(websocket_url.replace("localhost", "127.0.0.1"), max_size=None)
        self.next_id = 0
        self.errors: list[str] = []

    def send(self, method: str, params: dict | None = None) -> dict:
        self.next_id += 1
        request_id = self.next_id
        self.connection.send(json.dumps({"id": request_id, "method": method, "params": params or {}}))
        while True:
            message = json.loads(self.connection.recv())
            event = message.get("method")
            if event == "Runtime.exceptionThrown":
                self.errors.append(str((message.get("params") or {}).get("exceptionDetails") or message))
            elif event == "Runtime.consoleAPICalled" and (message.get("params") or {}).get("type") == "error":
                self.errors.append(str(message.get("params") or message))
            if message.get("id") == request_id:
                if "error" in message:
                    raise AssertionError(f"CDP {method} 失败：{message['error']}")
                return message.get("result") or {}

    def evaluate(self, expression: str):
        result = self.send("Runtime.evaluate", {
            "expression": expression,
            "awaitPromise": True,
            "returnByValue": True,
        })
        return ((result.get("result") or {}).get("value"))

    def close(self) -> None:
        self.connection.close()


def _run_edge_suite(base: str, condition, counters: dict[str, int], handoff_store) -> None:
    edge = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
    if not edge.exists():
        raise AssertionError(f"未找到 Edge：{edge}")
    debug_port = _free_port()
    with tempfile.TemporaryDirectory(prefix="mitako-edge-") as profile_dir:
        process = subprocess.Popen(
            [
                str(edge),
                "--headless=new",
                "--disable-gpu",
                "--no-first-run",
                "--no-default-browser-check",
                f"--remote-debugging-port={debug_port}",
                f"--user-data-dir={profile_dir}",
                "about:blank",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        try:
            target = _wait_for_edge_target(debug_port)
            cdp = _Cdp(target["webSocketDebuggerUrl"])
            try:
                cdp.send("Page.enable")
                cdp.send("Runtime.enable")
                for name, width, height in (("desktop", 1280, 800), ("mobile", 390, 844)):
                    cdp.send("Emulation.setDeviceMetricsOverride", {
                        "width": width,
                        "height": height,
                        "deviceScaleFactor": 1,
                        "mobile": width <= 390,
                    })
                    cdp.send("Page.navigate", {"url": f"{base}/?e2e=1"})
                    _wait_until(lambda: cdp.evaluate("document.readyState") == "complete", timeout=10.0)
                    _wait_until(
                        lambda: cdp.evaluate("Boolean(document.querySelector('input[name=chat_message]'))") is True,
                        timeout=10.0,
                    )
                    time.sleep(2.6)

                    started_before = counters["started"]
                    cancelled_before = counters["cancelled"]
                    _fill_and_send(cdp, f"{name} 停止测试")
                    _wait_counter(condition, counters, "started", started_before + 1)
                    _wait_until(
                        lambda: cdp.evaluate("Boolean(document.querySelector('button[aria-label=\\\"停止生成\\\"]'))") is True
                    )
                    box = cdp.evaluate("""
                        (() => {
                          const el = document.querySelector('button[aria-label="停止生成"]');
                          const rect = el.getBoundingClientRect();
                          return { width: rect.width, height: rect.height, title: el.title };
                        })()
                    """)
                    assert box["width"] >= 44 and box["height"] >= 44, (name, box)
                    assert box["title"] == "停止生成"
                    cdp.evaluate("document.querySelector('button[aria-label=\"停止生成\"]').click()")
                    _wait_counter(condition, counters, "cancelled", cancelled_before + 1)
                    _assert_stopped(cdp, name)

                    _fill_and_send(cdp, f"{name} 立即重发")
                    _wait_counter(condition, counters, "started", started_before + 2)
                    _wait_until(
                        lambda: cdp.evaluate("Boolean(document.querySelector('button[aria-label=\\\"停止生成\\\"]'))") is True
                    )
                    cdp.evaluate("document.querySelector('button[aria-label=\"停止生成\"]').click()")
                    _wait_counter(condition, counters, "cancelled", cancelled_before + 2)
                    _assert_stopped(cdp, name)
                    try:
                        _wait_until(
                            lambda: handoff_store.recent_chat_history("session_usr_001", limit=20) == [],
                            timeout=5.0,
                        )
                    except AssertionError as exc:
                        history = handoff_store.recent_chat_history("session_usr_001", limit=20)
                        raise AssertionError(f"{name} 取消后仍有服务端历史：{history}") from exc
                assert cdp.errors == [], cdp.errors
            finally:
                cdp.close()
        finally:
            process.terminate()
            process.wait(timeout=5.0)


def _wait_for_edge_target(port: int) -> dict:
    target: dict = {}

    def load() -> bool:
        nonlocal target
        try:
            with urlopen(f"http://127.0.0.1:{port}/json/list", timeout=0.5) as response:
                pages = json.loads(response.read().decode("utf-8"))
            target = next(item for item in pages if item.get("type") == "page")
            return True
        except Exception:
            return False

    _wait_until(load, timeout=10.0)
    return target


def _fill_and_send(cdp: _Cdp, text: str) -> None:
    payload = json.dumps(text, ensure_ascii=False)
    ok = cdp.evaluate(f"""
        (() => {{
          const input = document.querySelector('input[name=chat_message]');
          const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
          setter.call(input, {payload});
          input.dispatchEvent(new Event('input', {{ bubbles: true }}));
          const send = document.querySelector('button[aria-label="发送"]');
          if (!send) return false;
          send.click();
          return true;
        }})()
    """)
    assert ok is True, text


def _assert_stopped(cdp: _Cdp, viewport_name: str) -> None:
    _wait_until(lambda: cdp.evaluate("!document.querySelector('input[name=chat_message]').disabled"))
    state = cdp.evaluate("""
        ({
          stopVisible: Boolean(document.querySelector('button[aria-label="停止生成"]')),
          staleText: document.body.innerText.includes('旧流污染'),
          queryStatus: document.body.innerText.includes('正在帮您查询中')
            || document.body.innerText.includes('AI客服正在赶来')
        })
    """)
    assert state == {"stopVisible": False, "staleText": False, "queryStatus": False}, (
        viewport_name,
        state,
    )


if __name__ == "__main__":
    raise SystemExit(main())
