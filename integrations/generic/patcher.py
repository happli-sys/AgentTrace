"""
AgentTrace Patcher — 指定函数路径的零侵入动态注入。
"""
from __future__ import annotations

import asyncio
import functools
import importlib
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from agenttrace._context import get_collector, set_collector, reset_collector
from agenttrace._patch_registry import register as _reg, unregister as _unreg
from agenttrace.collectors.runtime import RuntimeCollector
from agenttrace.metrics.engine import EvalResult, MetricsEngine

engine = MetricsEngine()
_PATCH_MARKER = "__agentmeter_patched__"


def _resolve(dotted_path: str) -> Tuple[Any, str, Any]:
    parts = dotted_path.rsplit(".", 1)
    if len(parts) != 2:
        raise ValueError(f"Invalid path: {dotted_path!r}")
    parent_path, attr_name = parts
    try:
        owner = importlib.import_module(parent_path)
        return owner, attr_name, getattr(owner, attr_name)
    except (ImportError, AttributeError):
        pass
    module_path, class_name = parent_path.rsplit(".", 1)
    module = importlib.import_module(module_path)
    owner = getattr(module, class_name)
    return owner, attr_name, getattr(owner, attr_name)


def _make_wrapper(original: Callable, tool_name: str) -> Callable:
    if asyncio.iscoroutinefunction(original):
        @functools.wraps(original)
        async def async_wrapper(*args, **kwargs):
            col = get_collector()
            t0, error, status = time.perf_counter(), None, "success"
            try:
                return await original(*args, **kwargs)
            except Exception as e:
                error, status = str(e), "failed"
                raise
            finally:
                elapsed = (time.perf_counter() - t0) * 1000
                if col is not None:
                    col.record_tool_call(tool_name, status=status,
                                         latency_ms=elapsed, error=error)
        setattr(async_wrapper, _PATCH_MARKER, True)
        return async_wrapper

    @functools.wraps(original)
    def sync_wrapper(*args, **kwargs):
        col = get_collector()
        t0, error, status = time.perf_counter(), None, "success"
        try:
            return original(*args, **kwargs)
        except Exception as e:
            error, status = str(e), "failed"
            raise
        finally:
            elapsed = (time.perf_counter() - t0) * 1000
            if col is not None:
                col.record_tool_call(tool_name, status=status,
                                     latency_ms=elapsed, error=error)
    setattr(sync_wrapper, _PATCH_MARKER, True)
    return sync_wrapper


class Patcher:
    def __init__(self, tool_paths: List[str]):
        self._tool_paths = tool_paths
        self._patches: List[Tuple[Any, str, Callable]] = []
        self._applied = False

    def apply(self) -> None:
        if self._applied:
            return
        for path in self._tool_paths:
            try:
                owner, attr, original = _resolve(path)
            except Exception as e:
                raise RuntimeError(f"[AgentTrace] Cannot resolve '{path}': {e}") from e
            wrapper = _make_wrapper(original, path.rsplit(".", 1)[-1])
            _reg(owner, attr, original, wrapper)
            self._patches.append((owner, attr))
        self._applied = True

    def revert(self) -> None:
        for owner, attr in self._patches:
            _unreg(owner, attr)
        self._patches.clear()
        self._applied = False

    def __enter__(self) -> "Patcher":
        self.apply()
        return self

    def __exit__(self, *_) -> None:
        self.revert()


class PatchSession:
    def __init__(
        self,
        tools: List[str],
        task: str = "",
        agent_name: str = "agent",
        framework: str = "custom",
        model: str = "unknown",
        expected_output: Optional[str] = None,
        tags: Optional[Dict[str, str]] = None,
    ):
        self._patcher = Patcher(tools)
        self._col = RuntimeCollector(
            task=task, agent_name=agent_name, framework=framework,
            model=model, expected_output=expected_output, tags=tags or {},
        )
        self.result: Optional[EvalResult] = None
        self._token = None

    def __enter__(self) -> "PatchSession":
        self._patcher.apply()
        self._col.__enter__()
        self._token = set_collector(self._col)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        reset_collector(self._token)
        self._col.__exit__(exc_type, exc_val, exc_tb)
        self._patcher.revert()
        self.result = engine.evaluate(self._col.run)
        return False

    def set_output(self, output: str) -> None:
        self._col.set_output(output)

    def record_step(self, description: str = "", **kwargs) -> None:
        self._col.record_step(description, **kwargs)
