"""
Agent 运行状态快照模型。

这 6 类状态是工业级 Agent 评测里最核心的“可解释状态”：
  1. ContextSnapshot   上下文快照
  2. MemorySnapshot    记忆状态
  3. PlanSnapshot      计划状态
  4. DecisionSnapshot  决策理由
  5. ResumeSnapshot    中断/恢复状态
  6. ExecutionSnapshot 执行元状态
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ContextSnapshot:
    system_prompt: Optional[str] = None
    messages: List[Any] = field(default_factory=list)
    retrieved_docs: List[Any] = field(default_factory=list)
    memory_items: List[Any] = field(default_factory=list)
    tool_results: List[Any] = field(default_factory=list)
    token_count_before_send: Optional[int] = None
    context_trimmed: bool = False
    trimmed_items: List[Any] = field(default_factory=list)


@dataclass
class MemorySnapshot:
    stm_hits: List[Any] = field(default_factory=list)
    ltm_hits: List[Any] = field(default_factory=list)
    writes: List[Any] = field(default_factory=list)
    evictions: List[Any] = field(default_factory=list)


@dataclass
class PlanSnapshot:
    root_goal: Optional[str] = None
    plan_version: str = "v1"
    phase: Optional[str] = None
    completed_steps: List[str] = field(default_factory=list)
    pending_steps: List[str] = field(default_factory=list)
    replanned_count: int = 0
    plan_tree: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class DecisionSnapshot:
    action: Optional[str] = None
    rationale: Optional[str] = None
    confidence: Optional[float] = None
    candidates: List[str] = field(default_factory=list)


@dataclass
class ResumeSnapshot:
    interrupted: bool = False
    resumed: bool = False
    checkpoint_id: Optional[str] = None
    resumed_from: Optional[str] = None
    recovered_context: List[Any] = field(default_factory=list)
    recovered_plan: Optional[str] = None
    recovered_memory: List[Any] = field(default_factory=list)


@dataclass
class ExecutionSnapshot:
    interrupt_reason: Optional[str] = None
    resume_reason: Optional[str] = None
    retry_count: int = 0
    retry_reasons: List[Any] = field(default_factory=list)
    backoff_ms: List[float] = field(default_factory=list)
    tool_candidates: List[Any] = field(default_factory=list)
    tool_choice_reason: Optional[str] = None
    skill_candidates: List[Any] = field(default_factory=list)
    skill_choice_reason: Optional[str] = None
    tool_param_source: Optional[str] = None
    tool_param_notes: List[Any] = field(default_factory=list)
    context_trim_strategy: Optional[str] = None
    context_trim_reason: Optional[str] = None
    trimmed_messages: List[Any] = field(default_factory=list)
    recovery_action: Optional[str] = None
    recovery_reason: Optional[str] = None
    human_handoff_needed: bool = False
    handoff_reason: Optional[str] = None
    approval_needed: bool = False
    approval_reason: Optional[str] = None
    stop_reason: Optional[str] = None
    finished: bool = False
