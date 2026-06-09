"""
Core data models for AgentTrace.
All runtime measurements are stored in these dataclasses.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from agenttrace.state import ContextSnapshot, MemorySnapshot, PlanSnapshot, DecisionSnapshot, ResumeSnapshot


class ToolCallStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"
    INVALID_PARAMS = "invalid_params"
    TIMEOUT = "timeout"


class RunStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class ToolCallRecord:
    """Records a single tool call event."""
    tool_name: str
    status: ToolCallStatus
    latency_ms: float                      # wall-clock time in milliseconds
    input_params: Dict[str, Any] = field(default_factory=dict)
    output: Optional[Any] = None
    error: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.utcnow)
    call_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])

    # tracing metadata
    span_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    parent_span_id: Optional[str] = None
    group_id: Optional[str] = None
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None

    # recovery / reliability metadata
    retry_count: int = 0
    fallback_from: Optional[str] = None
    timeout: bool = False
    cancelled: bool = False

    # recovery / reliability metadata
    retry_count: int = 0
    fallback_from: Optional[str] = None
    timeout: bool = False
    cancelled: bool = False

    # rich state snapshots
    context_snapshot: Optional[ContextSnapshot] = None
    memory_snapshot: Optional[MemorySnapshot] = None
    plan_snapshot: Optional[PlanSnapshot] = None
    decision_snapshot: Optional[DecisionSnapshot] = None
    resume_snapshot: Optional[ResumeSnapshot] = None

    @property
    def succeeded(self) -> bool:
        return self.status == ToolCallStatus.SUCCESS


@dataclass
class StepRecord:
    """Records one reasoning/action step of the agent."""
    step_index: int
    description: str
    latency_ms: float
    input_tokens: int = 0
    output_tokens: int = 0
    tool_calls: List[ToolCallRecord] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.utcnow)

    # tracing metadata
    span_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    parent_span_id: Optional[str] = None
    group_id: Optional[str] = None
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None

    # recovery / reliability metadata
    retry_count: int = 0
    fallback_from: Optional[str] = None
    timeout: bool = False
    cancelled: bool = False

    # rich state snapshots
    context_snapshot: Optional[ContextSnapshot] = None
    memory_snapshot: Optional[MemorySnapshot] = None
    plan_snapshot: Optional[PlanSnapshot] = None
    decision_snapshot: Optional[DecisionSnapshot] = None
    resume_snapshot: Optional[ResumeSnapshot] = None

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def estimated_cost_usd(self) -> float:
        """Rough cost estimate using GPT-4o pricing as default."""
        return (self.input_tokens * 2.5 + self.output_tokens * 10) / 1_000_000


@dataclass
class AgentRun:
    """
    Complete record of one agent execution.
    This is the central object AgentTrace collects and evaluates.
    """
    run_id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    agent_name: str = "agent"
    task: str = ""
    framework: str = "unknown"             # langchain / crewai / openai_agents / custom
    model: str = "unknown"

    status: RunStatus = RunStatus.RUNNING
    steps: List[StepRecord] = field(default_factory=list)

    start_time: datetime = field(default_factory=datetime.utcnow)
    end_time: Optional[datetime] = None

    # Ground truth for correctness scoring (optional)
    expected_output: Optional[str] = None
    actual_output: Optional[str] = None

    # Extra metadata
    tags: Dict[str, str] = field(default_factory=dict)

    # ── derived properties ──────────────────────────────────────────────────

    @property
    def total_latency_ms(self) -> float:
        if self.end_time:
            return (self.end_time - self.start_time).total_seconds() * 1000
        return 0.0

    @property
    def total_steps(self) -> int:
        return len(self.steps)

    @property
    def total_tool_calls(self) -> int:
        return sum(len(s.tool_calls) for s in self.steps)

    @property
    def failed_tool_calls(self) -> int:
        return sum(
            1 for s in self.steps
            for tc in s.tool_calls
            if not tc.succeeded
        )

    @property
    def tool_call_success_rate(self) -> float:
        total = self.total_tool_calls
        if total == 0:
            return 1.0
        return (total - self.failed_tool_calls) / total

    @property
    def total_input_tokens(self) -> int:
        return sum(s.input_tokens for s in self.steps)

    @property
    def total_output_tokens(self) -> int:
        return sum(s.output_tokens for s in self.steps)

    @property
    def total_tokens(self) -> int:
        return self.total_input_tokens + self.total_output_tokens

    @property
    def estimated_cost_usd(self) -> float:
        return sum(s.estimated_cost_usd for s in self.steps)

    @property
    def all_tool_calls(self) -> List[ToolCallRecord]:
        return [tc for s in self.steps for tc in s.tool_calls]

    def finish(self, output: Optional[str] = None,
               status: RunStatus = RunStatus.COMPLETED) -> None:
        self.end_time = datetime.utcnow()
        self.status = status
        if output is not None:
            self.actual_output = output
