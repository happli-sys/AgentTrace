"""
AgentTrace 上下文管理。
支持：
  - 当前 collector
  - 当前 span 栈（用于 parent/child 关系）
  - 当前并行组 group_id（用于 fan-out/fan-in 展示）
"""
from __future__ import annotations

import contextvars
from contextlib import contextmanager
from typing import TYPE_CHECKING, Optional, List

if TYPE_CHECKING:
    from agenttrace.collectors.runtime import RuntimeCollector

_collector_var: contextvars.ContextVar[Optional["RuntimeCollector"]] = \
    contextvars.ContextVar("agentmeter_collector", default=None)
_span_stack_var: contextvars.ContextVar[list[str]] = \
    contextvars.ContextVar("agentmeter_span_stack", default=[])
_group_var: contextvars.ContextVar[Optional[str]] = \
    contextvars.ContextVar("agentmeter_group_id", default=None)


def get_collector() -> Optional["RuntimeCollector"]:
    return _collector_var.get()


def set_collector(col: Optional["RuntimeCollector"]) -> contextvars.Token:
    return _collector_var.set(col)


def reset_collector(token: contextvars.Token) -> None:
    _collector_var.reset(token)


def current_parent_span() -> Optional[str]:
    stack = _span_stack_var.get()
    return stack[-1] if stack else None


def current_group_id() -> Optional[str]:
    return _group_var.get()


@contextmanager
def push_span(span_id: str):
    stack = list(_span_stack_var.get())
    stack.append(span_id)
    token = _span_stack_var.set(stack)
    try:
        yield
    finally:
        _span_stack_var.reset(token)


@contextmanager
def set_group(group_id: str):
    token = _group_var.set(group_id)
    try:
        yield
    finally:
        _group_var.reset(token)
