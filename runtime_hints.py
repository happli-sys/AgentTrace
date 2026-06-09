"""
运行时语义提示（Runtime Hints）。

让业务 agent 在不强耦合 AgentTrace 内部模型的前提下，
把更有语义的计划/决策信息写进当前上下文。
"""
from __future__ import annotations

import contextvars
from contextlib import contextmanager
from typing import Any, Dict, List, Optional

_plan_var: contextvars.ContextVar[Optional[dict]] = contextvars.ContextVar('agentmeter_plan', default=None)
_decision_var: contextvars.ContextVar[Optional[dict]] = contextvars.ContextVar('agentmeter_decision', default=None)
_context_extra_var: contextvars.ContextVar[Optional[dict]] = contextvars.ContextVar('agentmeter_context_extra', default=None)
_execution_var: contextvars.ContextVar[Optional[dict]] = contextvars.ContextVar('agentmeter_execution', default=None)


def set_plan(plan: dict | None):
    return _plan_var.set(plan)

def get_plan() -> Optional[dict]:
    return _plan_var.get()

def reset_plan(token):
    _plan_var.reset(token)


def set_decision(decision: dict | None):
    return _decision_var.set(decision)

def get_decision() -> Optional[dict]:
    return _decision_var.get()

def reset_decision(token):
    _decision_var.reset(token)


def set_context_extra(extra: dict | None):
    return _context_extra_var.set(extra)

def get_context_extra() -> Optional[dict]:
    return _context_extra_var.get()

def reset_context_extra(token):
    _context_extra_var.reset(token)


def set_execution(execution: dict | None):
    return _execution_var.set(execution)

def get_execution() -> Optional[dict]:
    return _execution_var.get()

def reset_execution(token):
    _execution_var.reset(token)


@contextmanager
def planning(plan: dict):
    t = set_plan(plan)
    try:
        yield
    finally:
        reset_plan(t)


@contextmanager
def decisioning(decision: dict):
    t = set_decision(decision)
    try:
        yield
    finally:
        reset_decision(t)


@contextmanager
def context_extra(extra: dict):
    t = set_context_extra(extra)
    try:
        yield
    finally:
        reset_context_extra(t)


@contextmanager
def executioning(execution: dict):
    t = set_execution(execution)
    try:
        yield
    finally:
        reset_execution(t)
