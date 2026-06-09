"""
RuntimeCollector — 采集运行时信息。
增加 tracing 元数据：span_id / parent_span_id / group_id / started_at / ended_at
"""
from __future__ import annotations

import functools
import time
import uuid
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Callable, Dict, Optional

from agenttrace._context import current_group_id, current_parent_span, push_span
from agenttrace.models import (
    AgentRun, RunStatus, StepRecord, ToolCallRecord, ToolCallStatus
)


class RuntimeCollector:
    def __init__(
        self,
        task: str = "",
        agent_name: str = "agent",
        framework: str = "custom",
        model: str = "unknown",
        expected_output: Optional[str] = None,
        tags: Optional[Dict[str, str]] = None,
    ):
        self.run = AgentRun(
            task=task,
            agent_name=agent_name,
            framework=framework,
            model=model,
            expected_output=expected_output,
            tags=tags or {},
        )
        self._step_counter = 0

    def __enter__(self) -> "RuntimeCollector":
        self.run.start_time = datetime.utcnow()
        self.run.status = RunStatus.RUNNING
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        if exc_type is not None:
            self.run.finish(status=RunStatus.FAILED)
        else:
            self.run.finish(status=RunStatus.COMPLETED)
        return False

    def record_step(
        self,
        description: str = "",
        input_tokens: int = 0,
        output_tokens: int = 0,
        latency_ms: Optional[float] = None,
        *,
        span_id: Optional[str] = None,
        parent_span_id: Optional[str] = None,
        group_id: Optional[str] = None,
        started_at: Optional[datetime] = None,
        ended_at: Optional[datetime] = None,
    ) -> StepRecord:
        if latency_ms is None:
            latency_ms = 0.0
        step = StepRecord(
            step_index=self._step_counter,
            description=description,
            latency_ms=latency_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            span_id=span_id or str(uuid.uuid4())[:8],
            parent_span_id=parent_span_id if parent_span_id is not None else current_parent_span(),
            group_id=group_id if group_id is not None else current_group_id(),
            started_at=started_at,
            ended_at=ended_at,
        )
        self.run.steps.append(step)
        self._step_counter += 1
        return step

    def record_tool_call(
        self,
        tool_name: str,
        status: str = "success",
        latency_ms: float = 0.0,
        input_params: Optional[Dict[str, Any]] = None,
        output: Optional[Any] = None,
        error: Optional[str] = None,
        step_index: Optional[int] = None,
        *,
        span_id: Optional[str] = None,
        parent_span_id: Optional[str] = None,
        group_id: Optional[str] = None,
        started_at: Optional[datetime] = None,
        ended_at: Optional[datetime] = None,
    ) -> ToolCallRecord:
        tc = ToolCallRecord(
            tool_name=tool_name,
            status=ToolCallStatus(status),
            latency_ms=latency_ms,
            input_params=input_params or {},
            output=output,
            error=error,
            span_id=span_id or str(uuid.uuid4())[:8],
            parent_span_id=parent_span_id if parent_span_id is not None else current_parent_span(),
            group_id=group_id if group_id is not None else current_group_id(),
            started_at=started_at,
            ended_at=ended_at,
        )
        idx = step_index if step_index is not None else len(self.run.steps) - 1
        if not self.run.steps:
            self.record_step("agent_turn", latency_ms=latency_ms)
            idx = 0
        if idx >= 0 and idx < len(self.run.steps):
            self.run.steps[idx].tool_calls.append(tc)
        return tc

    def set_output(self, output: str) -> None:
        self.run.actual_output = output

    @contextmanager
    def time_step(self, description: str = "", **token_kwargs):
        span_id = str(uuid.uuid4())[:8]
        started = datetime.utcnow()
        t0 = time.perf_counter()
        with push_span(span_id):
            yield
        elapsed_ms = (time.perf_counter() - t0) * 1000
        ended = datetime.utcnow()
        self.record_step(
            description=description,
            latency_ms=elapsed_ms,
            started_at=started,
            ended_at=ended,
            span_id=span_id,
            **token_kwargs,
        )

    @contextmanager
    def time_tool(self, tool_name: str, input_params: Optional[Dict] = None):
        span_id = str(uuid.uuid4())[:8]
        started = datetime.utcnow()
        t0 = time.perf_counter()
        error = None
        status = "success"
        try:
            with push_span(span_id):
                yield
        except Exception as e:
            error = str(e)
            status = "failed"
            raise
        finally:
            elapsed_ms = (time.perf_counter() - t0) * 1000
            ended = datetime.utcnow()
            self.record_tool_call(
                tool_name=tool_name,
                status=status,
                latency_ms=elapsed_ms,
                input_params=input_params or {},
                error=error,
                span_id=span_id,
                started_at=started,
                ended_at=ended,
            )

    def track_tool(self, tool_name: Optional[str] = None):
        def decorator(fn: Callable) -> Callable:
            name = tool_name or fn.__name__
            @functools.wraps(fn)
            def wrapper(*args, **kwargs):
                span_id = str(uuid.uuid4())[:8]
                started = datetime.utcnow()
                t0 = time.perf_counter()
                error = None
                status = "success"
                result = None
                try:
                    with push_span(span_id):
                        result = fn(*args, **kwargs)
                    return result
                except Exception as e:
                    error = str(e)
                    status = "failed"
                    raise
                finally:
                    elapsed_ms = (time.perf_counter() - t0) * 1000
                    ended = datetime.utcnow()
                    self.record_tool_call(
                        tool_name=name,
                        status=status,
                        latency_ms=elapsed_ms,
                        input_params={"args": str(args), "kwargs": str(kwargs)},
                        output=str(result) if result is not None else None,
                        error=error,
                        span_id=span_id,
                        started_at=started,
                        ended_at=ended,
                    )
            return wrapper
        return decorator
