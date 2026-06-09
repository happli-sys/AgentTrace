"""
AgentTrace Dashboard HTTP Server。

提供：
  GET  /                    → Dashboard HTML 页面
  GET  /api/sessions        → 所有 session 摘要列表（JSON）
  GET  /api/session/{id}    → 单条 session 完整数据（JSON）
  GET  /api/stream          → SSE，实时推送新 session 事件

使用：
  from agenttrace.dashboard import start_server
  start_server(port=3500)                  # 后台线程启动
"""
from __future__ import annotations

import json
import os
import queue
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer, HTTPServer
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from agenttrace.dashboard.store import SessionStore, get_store

# SSE 订阅者队列
_sse_queues: list[queue.Queue] = []
_sse_lock = threading.Lock()


def push_event(data: dict) -> None:
    """向所有 SSE 订阅者推送新事件。"""
    payload = json.dumps(data, ensure_ascii=False)
    with _sse_lock:
        dead = []
        for q in _sse_queues:
            try:
                q.put_nowait(payload)
            except queue.Full:
                dead.append(q)
        for q in dead:
            _sse_queues.remove(q)


class _Handler(BaseHTTPRequestHandler):

    store: SessionStore = None   # 由 start_server 注入

    def handle(self):
        try:
            super().handle()
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        parsed = urlparse(self.path)
        path   = parsed.path.rstrip("/") or "/"

        if path == "/":
            self._serve_html()
        elif path == "/api/sessions":
            self._serve_json(self.store.list_sessions())
        elif path.startswith("/api/session/"):
            run_id = path[len("/api/session/"):]
            doc    = self.store.get_session(run_id)
            if doc:
                self._serve_json(doc)
            else:
                self._send(404, "application/json", b'{"error":"not found"}')
        elif path == "/api/stream":
            self._serve_sse()
        else:
            self._send(404, "text/plain", b"Not found")

    # ── helpers ──────────────────────────────────────────────────────────────

    def _serve_html(self):
        html_path = Path(__file__).parent / "index.html"
        content   = html_path.read_bytes()
        self._send(200, "text/html; charset=utf-8", content)

    def _serve_json(self, data):
        body = json.dumps(data, ensure_ascii=False, default=str).encode()
        self._send(200, "application/json; charset=utf-8", body)

    def _send(self, code: int, content_type: str, body: bytes):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _serve_sse(self):
        self.send_response(200)
        self.send_header("Content-Type",  "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection",    "keep-alive")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        q: queue.Queue = queue.Queue(maxsize=50)
        with _sse_lock:
            _sse_queues.append(q)

        try:
            # 先推一下心跳，让浏览器确认连接
            self.wfile.write(b": heartbeat\n\n")
            self.wfile.flush()
            while True:
                try:
                    payload = q.get(timeout=15)
                    self.wfile.write(f"data: {payload}\n\n".encode())
                    self.wfile.flush()
                except queue.Empty:
                    # 定时心跳，防止连接超时
                    self.wfile.write(b": heartbeat\n\n")
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            with _sse_lock:
                if q in _sse_queues:
                    _sse_queues.remove(q)

    def log_message(self, *_):
        pass   # 静默日志


def start_server(
    port:      int          = 3500,
    store_dir: str          = "listen",
    daemon:    bool         = True,
) -> HTTPServer:
    """
    在后台线程启动 Dashboard HTTP Server。
    返回 HTTPServer 实例（可调用 .shutdown() 停止）。
    """
    store = get_store(store_dir)
    _Handler.store = store

    server = ThreadingHTTPServer(("0.0.0.0", port), _Handler)

    t = threading.Thread(target=server.serve_forever, daemon=daemon)
    t.start()

    print(f"🌐 AgentTrace Dashboard: http://localhost:{port}")
    return server
