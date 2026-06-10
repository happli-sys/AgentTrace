"""
把一次调用的已有数据（prompt/response/tool results等）组装成状态快照。
当前先做最小可用自动构建：
- Context: 基于 LLM prompt、近期工具结果
- Memory: 默认空（等待用户/框架接入）
- Plan: 基于 action / candidates / completed tools 粗略推断
- Decision: 基于当前动作和候选项
- Resume: 默认无恢复
"""
from __future__ import annotations

from typing import Any, List, Optional

from agenttrace.runtime_hints import get_plan, get_decision, get_context_extra, get_execution
from agenttrace.derive import derive_plan_from_run, derive_decision_from_run, derive_memory_from_run, derive_resume_from_run
from agenttrace.state import (
    ContextSnapshot, MemorySnapshot, PlanSnapshot,
    DecisionSnapshot, ResumeSnapshot, ExecutionSnapshot,
)


def build_context_snapshot(
    llm_prompt: Any = None,
    tool_results: Optional[list] = None,
    token_count_before_send: Optional[int] = None,
) -> ContextSnapshot:
    system_prompt = None
    messages = []
    if isinstance(llm_prompt, list):
        messages = llm_prompt
        for m in llm_prompt:
            if isinstance(m, dict) and m.get('role') == 'system':
                system_prompt = m.get('content')
                break
    elif llm_prompt is not None:
        messages = [llm_prompt]
    extra = get_context_extra() or {}
    return ContextSnapshot(
        system_prompt=system_prompt,
        messages=messages,
        retrieved_docs=extra.get('retrieved_docs', []),
        memory_items=extra.get('memory_items', []),
        tool_results=tool_results or extra.get('tool_results', []),
        token_count_before_send=token_count_before_send,
        context_trimmed=extra.get('context_trimmed', False),
        trimmed_items=extra.get('trimmed_items', []),
    )


def build_memory_snapshot(task: Optional[str] = None, events: Optional[list] = None) -> MemorySnapshot:
    if task is not None and events is not None:
        return derive_memory_from_run(task, events)
    return MemorySnapshot()


def build_plan_snapshot(
    action: Optional[str] = None,
    completed_steps: Optional[list] = None,
    pending_steps: Optional[list] = None,
    task: Optional[str] = None,
    events: Optional[list] = None,
) -> PlanSnapshot:
    hint = get_plan() or {}
    if hint:
        plan = PlanSnapshot(
            root_goal=hint.get('root_goal') or action,
            plan_version=hint.get('plan_version', 'v1'),
            phase=hint.get('phase'),
            completed_steps=hint.get('completed_steps', completed_steps or []),
            pending_steps=hint.get('pending_steps', pending_steps or []),
            replanned_count=hint.get('replanned_count', 0),
            plan_tree=hint.get('plan_tree', []),
        )
        plan.source = 'runtime_hint'
        return plan
    if task is not None and events is not None:
        plan = derive_plan_from_run(task, events)
        plan.source = 'derived'
        return plan
    return PlanSnapshot(
        root_goal=action,
        completed_steps=completed_steps or [],
        pending_steps=pending_steps or [],
        plan_tree=[
            {"step": s, "status": "completed"} for s in (completed_steps or [])
        ] + [
            {"step": s, "status": "pending"} for s in (pending_steps or [])
        ]
    )


def build_decision_snapshot(
    action: Optional[str] = None,
    rationale: Optional[str] = None,
    confidence: Optional[float] = None,
    candidates: Optional[list] = None,
    task: Optional[str] = None,
    events: Optional[list] = None,
) -> DecisionSnapshot:
    hint = get_decision() or {}
    if hint:
        d = DecisionSnapshot(
            action=hint.get('action') or action,
            rationale=hint.get('rationale') or rationale,
            confidence=hint.get('confidence', confidence),
            candidates=hint.get('candidates', candidates or []),
        )
        d.source = 'runtime_hint'
        return d
    if task is not None and events is not None:
        d = derive_decision_from_run(task, events)
        d.source = 'derived'
        return d
    return DecisionSnapshot(
        action=action,
        rationale=rationale,
        confidence=confidence,
        candidates=candidates or [],
    )


def build_resume_snapshot(task: Optional[str] = None, events: Optional[list] = None) -> ResumeSnapshot:
    if task is not None and events is not None:
        return derive_resume_from_run(task, events)
    return ResumeSnapshot()


def build_execution_snapshot() -> ExecutionSnapshot:
    hint = get_execution() or {}
    return ExecutionSnapshot(
        interrupt_reason=hint.get('interrupt_reason'),
        resume_reason=hint.get('resume_reason'),
        retry_count=hint.get('retry_count', 0),
        retry_reasons=hint.get('retry_reasons', []),
        backoff_ms=hint.get('backoff_ms', []),
        tool_candidates=hint.get('tool_candidates', []),
        tool_choice_reason=hint.get('tool_choice_reason'),
        skill_candidates=hint.get('skill_candidates', []),
        skill_choice_reason=hint.get('skill_choice_reason'),
        tool_param_source=hint.get('tool_param_source'),
        tool_param_notes=hint.get('tool_param_notes', []),
        context_trim_strategy=hint.get('context_trim_strategy'),
        context_trim_reason=hint.get('context_trim_reason'),
        trimmed_messages=hint.get('trimmed_messages', []),
        recovery_action=hint.get('recovery_action'),
        recovery_reason=hint.get('recovery_reason'),
        human_handoff_needed=hint.get('human_handoff_needed', False),
        handoff_reason=hint.get('handoff_reason'),
        approval_needed=hint.get('approval_needed', False),
        approval_reason=hint.get('approval_reason'),
        stop_reason=hint.get('stop_reason'),
        finished=hint.get('finished', False),
    )
