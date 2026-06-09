"""
Claude Code — Hook Server 接入

Claude Code 在每次工具调用前后、以及会话结束时，
会向注册的 HTTP URL 发送事件。AgentTrace 启动一个轻量
HTTP server 接收这些事件，实时采集指标。

━━ 快速上手 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. 注入 hook 配置（只需做一次）：
       agenttrace inject-hooks

2. 启动 AgentTrace hook server：
       agenttrace hook-server

3. 正常使用 Claude Code，无需任何改动：
       claude "帮我重构这个文件"

   会话结束后报告自动保存到 .agenttrace/last_session.json

4. 查看报告：
       agenttrace report .agenttrace/last_session.json

━━ 扩展到其他 CLI Agent ━━━━━━━━━━━━━━━━━━━━━━━━

任何支持 HTTP hook 的 CLI Agent 都可以对接同一个 server，
只要 hook payload 里包含 hook_event / tool_use / session_id 字段即可。
参考 claude_code hook payload 格式即可适配。
"""
from __future__ import annotations

import json
import os
import time
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Dict, Optional

from agenttrace.collectors.runtime import RuntimeCollector
from agenttrace.metrics.engine import MetricsEngine, EvalResult
from agenttrace.reporters.json_reporter import JSONReporter

engine = MetricsEngine()

# session_id → RuntimeCollector
_sessions: Dict[str, RuntimeCollector] = {}
# tool_use_id → start timestamp
_tool_timers: Dict[str, float] = {}
# tool_use_id → tool name
_tool_names: Dict[str, str] = {}


def _get_or_create(session_id: str) -> RuntimeCollector:
    if session_id not in _sessions:
        col = RuntimeCollector(
            task="(claude code session)",
            agent_name="claude_code",
            framework="claude_code",
        )
        col.__enter__()
        _sessions[session_id] = col
    return _sessions[session_id]


def _finalize(session_id: str, store_dir: str) -> Optional[EvalResult]:
    col = _sessions.pop(session_id, None)
    if col is None:
        return None
    col.__exit__(None, None, None)
    result = engine.evaluate(col.run)

    Path(store_dir).mkdir(exist_ok=True)
    short = session_id[:8]
    JSONReporter.save(result, os.path.join(store_dir, f"session_{short}.json"))
    JSONReporter.save(result, os.path.join(store_dir, "last_session.json"))

    print(f"\n{'═'*52}")
    print(result.summary())
    return result


class _HookHandler(BaseHTTPRequestHandler):

    store_dir: str = ".agenttrace"

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        self.send_response(200)
        self.end_headers()

        try:
            event = json.loads(body)
        except json.JSONDecodeError:
            return

        hook_event = event.get("hook_event", "")
        session_id = event.get("session_id", "default")

        if hook_event == "PreToolUse":
            tid = event.get("tool_use", {}).get("id", "")
            _tool_timers[tid] = time.perf_counter()
            _tool_names[tid] = event.get("tool_use", {}).get("name", "unknown_tool")

        elif hook_event == "PostToolUse":
            col = _get_or_create(session_id)
            tid = event.get("tool_use", {}).get("id", "")
            tname = _tool_names.pop(tid, event.get("tool_use", {}).get("name", "unknown_tool"))
            is_err = event.get("tool_response", {}).get("is_error", False)
            elapsed = (time.perf_counter() - _tool_timers.pop(tid, time.perf_counter())) * 1000

            col.record_tool_call(
                tool_name=tname,
                status="failed" if is_err else "success",
                latency_ms=elapsed,
                error=str(event.get("tool_response", {}).get("content", ""))[:200] if is_err else None,
            )
            # 每轮工具调用补一个 agent_turn 步骤
            if not col.run.steps or col.run.steps[-1].description != "agent_turn":
                col.record_step("agent_turn", latency_ms=elapsed)

        elif hook_event == "Stop":
            _finalize(session_id, self.store_dir)

    def log_message(self, *_):
        pass  # 静默 HTTP 日志


class HookServer:
    """
    AgentTrace Hook Server。

    两种用法：

    # 1. context manager（推荐）
    with HookServer(port=7755) as srv:
        srv.wait()   # 阻塞直到 Ctrl-C

    # 2. 后台运行
    srv = HookServer(port=7755)
    srv.start_background()
    # ... 做其他事 ...
    srv.stop()
    """

    def __init__(self, port: int = 7755, store_dir: str = ".agenttrace"):
        self.port = port
        self.store_dir = store_dir
        _HookHandler.store_dir = store_dir
        self._server: Optional[HTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    def __enter__(self):
        self.start_background()
        return self

    def __exit__(self, *_):
        self.stop()

    def start_background(self):
        self._server = HTTPServer(("127.0.0.1", self.port), _HookHandler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        print(f"🎯 AgentTrace hook server listening on http://127.0.0.1:{self.port}/hook")
        print(f"   Reports → {self.store_dir}/")

    def stop(self):
        if self._server:
            self._server.shutdown()
            print("🛑 AgentTrace hook server stopped.")

    def wait(self):
        """阻塞直到 Ctrl-C。"""
        try:
            print("   Press Ctrl-C to stop.\n")
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            self.stop()


def inject_hooks(port: int = 7755, settings_path: Optional[str] = None) -> None:
    """
    向 ~/.claude/settings.json 注入 AgentTrace hook 配置。
    已存在的配置不会重复写入。
    """
    path = Path(settings_path or os.path.expanduser("~/.claude/settings.json"))
    settings = json.loads(path.read_text()) if path.exists() else {}

    url = f"http://127.0.0.1:{port}/hook"
    entry = {"matcher": "*", "hooks": [{"type": "http", "url": url, "timeout": 10, "async": True}]}
    hooks = settings.setdefault("hooks", {})
    allowed = settings.setdefault("allowedHttpHookUrls", [])

    changed = False
    for event in ("PreToolUse", "PostToolUse", "Stop"):
        bucket = hooks.setdefault(event, [])
        if not any(h.get("hooks", [{}])[0].get("url") == url for h in bucket):
            bucket.append(entry)
            changed = True

    wildcard = f"http://127.0.0.1:{port}/*"
    if wildcard not in allowed:
        allowed.append(wildcard)
        changed = True

    if changed:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(settings, indent=2))
        print(f"✅ AgentTrace hooks injected → {path}")
        print(f"   Listening events: PreToolUse, PostToolUse, Stop")
    else:
        print(f"ℹ️  AgentTrace hooks already present in {path}")
