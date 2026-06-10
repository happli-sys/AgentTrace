"""
有源码的 Agent — 方式 A / B / C 接入。
"""
from __future__ import annotations

import functools
import time
import threading
from typing import Any, Callable, Optional, Tuple, TypeVar

from agenttrace._context import get_collector, set_collector, reset_collector
from agenttrace.collectors.runtime import RuntimeCollector
from agenttrace.metrics.engine import EvalResult, MetricsEngine

engine = MetricsEngine()
_last_result: Optional[EvalResult] = None
_lock = threading.Lock()
F = TypeVar("F", bound=Callable[..., Any])


# ── 方式 A：meter() ──────────────────────────────────────────────────────────

def meter(
    fn: Callable,
    *,
    task: str = "",
    agent_name: Optional[str] = None,
    framework: str = "custom",
    model: str = "unknown",
    expected_output: Optional[str] = None,
    tags: Optional[dict] = None,
    args: tuple = (),
    kwargs: Optional[dict] = None,
) -> Tuple[Any, EvalResult]:
    global _last_result
    name = agent_name or getattr(fn, "__name__", "agent")
    kwargs = kwargs or {}
    col = RuntimeCollector(
        task=task, agent_name=name, framework=framework,
        model=model, expected_output=expected_output, tags=tags or {},
    )
    with col:
        t0 = time.perf_counter()
        result = fn(*args, **kwargs)
        elapsed = (time.perf_counter() - t0) * 1000
        if not col.run.steps:
            col.record_step("agent_run", latency_ms=elapsed)
        col.set_output(str(result) if result is not None else "")
    eval_result = engine.evaluate(col.run)
    with _lock:
        _last_result = eval_result
    return result, eval_result


# ── 方式 B：@tool_meter ──────────────────────────────────────────────────────

def tool_meter(fn: F) -> F:
    """
    装饰在工具函数上，自动记录耗时和成功/失败。
    配合 MeterSession 使用，session 外调用时静默无开销。
    """
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        col = get_collector()
        t0, error, status, result = time.perf_counter(), None, "success", None
        try:
            result = fn(*args, **kwargs)
            return result
        except Exception as e:
            error, status = str(e), "failed"
            raise
        finally:
            elapsed = (time.perf_counter() - t0) * 1000
            if col is not None:
                col.record_tool_call(
                    tool_name=fn.__name__,
                    status=status,
                    latency_ms=elapsed,
                    input_params={"args": _safe_repr(args), "kwargs": _safe_repr(kwargs)},
                    output=_safe_repr(result)[:200] if result is not None else None,
                    error=error,
                )
    return wrapper  # type: ignore


class MeterSession:
    """配合 @tool_meter 使用的 session 上下文。"""

    def __init__(
        self,
        task: str = "",
        agent_name: str = "agent",
        framework: str = "custom",
        model: str = "unknown",
        expected_output: Optional[str] = None,
        tags: Optional[dict] = None,
    ):
        self.col = RuntimeCollector(
            task=task, agent_name=agent_name, framework=framework,
            model=model, expected_output=expected_output, tags=tags or {},
        )
        self.result: Optional[EvalResult] = None
        self._token = None

    def __enter__(self) -> "MeterSession":
        self.col.__enter__()
        self._token = set_collector(self.col)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        reset_collector(self._token)
        self.col.__exit__(exc_type, exc_val, exc_tb)
        self.result = engine.evaluate(self.col.run)
        global _last_result
        with _lock:
            _last_result = self.result
        return False

    def set_output(self, output: str) -> None:
        self.col.set_output(output)

    def record_step(self, description: str = "", **kwargs) -> None:
        self.col.record_step(description, **kwargs)


def get_last_report() -> Optional[EvalResult]:
    return _last_result


def _safe_repr(obj: Any) -> str:
    try:
        return repr(obj)[:200]
    except Exception:
        return "<unrepresentable>"
