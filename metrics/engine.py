"""
Metrics Engine — computes all objective metrics from an AgentRun.
No LLM calls, pure math + optional string matching.
"""
from __future__ import annotations

import re
import difflib
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from agenttrace.models import AgentRun, ToolCallRecord


# ── per-tool breakdown ─────────────────────────────────────────────────────

@dataclass
class ToolStats:
    tool_name: str
    call_count: int = 0
    success_count: int = 0
    total_latency_ms: float = 0.0
    latencies: List[float] = field(default_factory=list)

    @property
    def success_rate(self) -> float:
        return self.success_count / self.call_count if self.call_count else 0.0

    @property
    def avg_latency_ms(self) -> float:
        return self.total_latency_ms / self.call_count if self.call_count else 0.0

    @property
    def p95_latency_ms(self) -> float:
        if not self.latencies:
            return 0.0
        sorted_l = sorted(self.latencies)
        idx = int(len(sorted_l) * 0.95)
        return sorted_l[min(idx, len(sorted_l) - 1)]


# ── main result dataclass ──────────────────────────────────────────────────

@dataclass
class EvalResult:
    run_id: str
    agent_name: str
    task: str
    framework: str
    model: str

    # ── latency ────────────────────────────────────────
    total_latency_ms: float = 0.0
    avg_step_latency_ms: float = 0.0
    p95_step_latency_ms: float = 0.0
    slowest_step: str = ""

    # ── steps ──────────────────────────────────────────
    total_steps: int = 0
    redundant_steps: int = 0          # steps with no tool calls and no tokens
    step_efficiency_score: float = 1.0  # 1.0 = perfect, 0.0 = very inefficient

    # ── tool calls ─────────────────────────────────────
    total_tool_calls: int = 0
    failed_tool_calls: int = 0
    tool_call_success_rate: float = 1.0
    avg_tool_latency_ms: float = 0.0
    tool_stats: Dict[str, ToolStats] = field(default_factory=dict)
    most_called_tool: str = ""
    slowest_tool: str = ""

    # ── tokens & cost ──────────────────────────────────
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float = 0.0
    tokens_per_step: float = 0.0

    # ── correctness ────────────────────────────────────
    # Only populated if expected_output is provided
    correctness_score: Optional[float] = None   # 0.0–1.0 fuzzy match
    exact_match: Optional[bool] = None
    keyword_coverage: Optional[float] = None    # fraction of expected keywords found

    # ── overall score ──────────────────────────────────
    # Composite: weighted average of available objective metrics
    composite_score: float = 0.0

    # ── llm review ─────────────────────────────────────
    llm_review_summary: str = ""
    llm_review_findings: List[Dict[str, str]] = field(default_factory=list)
    llm_review_level: int = 2

    def summary(self) -> str:
        lines = [
            f"{'─'*50}",
            f"  AgentTrace Report — {self.agent_name}",
            f"{'─'*50}",
            f"  Task            : {self.task[:60]}",
            f"  Framework       : {self.framework}  |  Model: {self.model}",
            f"{'─'*50}",
            f"  ⏱  Total latency    : {self.total_latency_ms:,.0f} ms",
            f"  📶 Avg step latency : {self.avg_step_latency_ms:,.0f} ms",
            f"  📶 P95 step latency : {self.p95_step_latency_ms:,.0f} ms",
            f"{'─'*50}",
            f"  🔢 Steps            : {self.total_steps}  (redundant: {self.redundant_steps})",
            f"  ⚡ Step efficiency  : {self.step_efficiency_score:.2f}",
            f"{'─'*50}",
            f"  🔧 Tool calls       : {self.total_tool_calls}  (failed: {self.failed_tool_calls})",
            f"  ✅ Tool success rate: {self.tool_call_success_rate:.1%}",
            f"  ⏱  Avg tool latency : {self.avg_tool_latency_ms:,.0f} ms",
        ]
        if self.most_called_tool:
            lines.append(f"  🏆 Most called tool : {self.most_called_tool}")
        if self.slowest_tool:
            lines.append(f"  🐢 Slowest tool     : {self.slowest_tool}")
        lines += [
            f"{'─'*50}",
            f"  🪙 Tokens in/out   : {self.total_input_tokens:,} / {self.total_output_tokens:,}",
            f"  💰 Est. cost        : ${self.estimated_cost_usd:.5f}",
        ]
        if self.correctness_score is not None:
            lines += [
                f"{'─'*50}",
                f"  🎯 Correctness      : {self.correctness_score:.2f}",
                f"  🔑 Keyword coverage : {self.keyword_coverage:.2f}" if self.keyword_coverage is not None else "",
                f"  ✔  Exact match      : {self.exact_match}",
            ]
        lines += [
            f"{'─'*50}",
            f"  🏅 Composite score  : {self.composite_score:.2f} / 1.00",
        ]
        if self.llm_review_summary:
            lines += [
                f"{'─'*50}",
                f"  🧠 Review summary   : {self.llm_review_summary[:120]}",
            ]
            if self.llm_review_findings:
                lines.append(f"  🔎 Review findings  : {len(self.llm_review_findings)}")
        lines.append(f"{'─'*50}")
        return "\n".join(l for l in lines if l)


# ── engine ─────────────────────────────────────────────────────────────────

class MetricsEngine:
    """
    Pure-math metrics engine. Takes an AgentRun, returns EvalResult.
    No external calls, no LLM judges.
    """

    def evaluate(self, run: AgentRun) -> EvalResult:
        result = EvalResult(
            run_id=run.run_id,
            agent_name=run.agent_name,
            task=run.task,
            framework=run.framework,
            model=run.model,
        )

        self._compute_latency(run, result)
        self._compute_steps(run, result)
        self._compute_tool_calls(run, result)
        self._compute_tokens(run, result)
        self._compute_correctness(run, result)
        self._compute_composite(result)

        return result

    # ── latency ────────────────────────────────────────────────────────────

    def _compute_latency(self, run: AgentRun, r: EvalResult) -> None:
        r.total_latency_ms = run.total_latency_ms
        step_latencies = [s.latency_ms for s in run.steps if s.latency_ms > 0]
        if step_latencies:
            r.avg_step_latency_ms = sum(step_latencies) / len(step_latencies)
            sorted_l = sorted(step_latencies)
            idx = int(len(sorted_l) * 0.95)
            r.p95_step_latency_ms = sorted_l[min(idx, len(sorted_l) - 1)]
            # find slowest step
            max_idx = step_latencies.index(max(step_latencies))
            if max_idx < len(run.steps):
                r.slowest_step = run.steps[max_idx].description or f"step_{max_idx}"

    # ── steps ──────────────────────────────────────────────────────────────

    def _compute_steps(self, run: AgentRun, r: EvalResult) -> None:
        r.total_steps = run.total_steps
        # redundant = step with no tool calls AND no tokens (likely a no-op)
        r.redundant_steps = sum(
            1 for s in run.steps
            if not s.tool_calls and s.total_tokens == 0
        )
        useful = r.total_steps - r.redundant_steps
        r.step_efficiency_score = useful / r.total_steps if r.total_steps > 0 else 1.0

    # ── tool calls ─────────────────────────────────────────────────────────

    def _compute_tool_calls(self, run: AgentRun, r: EvalResult) -> None:
        r.total_tool_calls = run.total_tool_calls
        r.failed_tool_calls = run.failed_tool_calls
        r.tool_call_success_rate = run.tool_call_success_rate

        tool_map: Dict[str, ToolStats] = {}
        all_tool_latencies = []

        for tc in run.all_tool_calls:
            if tc.tool_name not in tool_map:
                tool_map[tc.tool_name] = ToolStats(tool_name=tc.tool_name)
            ts = tool_map[tc.tool_name]
            ts.call_count += 1
            ts.total_latency_ms += tc.latency_ms
            ts.latencies.append(tc.latency_ms)
            if tc.succeeded:
                ts.success_count += 1
            all_tool_latencies.append(tc.latency_ms)

        r.tool_stats = tool_map

        if all_tool_latencies:
            r.avg_tool_latency_ms = sum(all_tool_latencies) / len(all_tool_latencies)

        if tool_map:
            r.most_called_tool = max(tool_map, key=lambda k: tool_map[k].call_count)
            r.slowest_tool = max(tool_map, key=lambda k: tool_map[k].avg_latency_ms)

    # ── tokens & cost ──────────────────────────────────────────────────────

    def _compute_tokens(self, run: AgentRun, r: EvalResult) -> None:
        r.total_input_tokens = run.total_input_tokens
        r.total_output_tokens = run.total_output_tokens
        r.total_tokens = run.total_tokens
        r.estimated_cost_usd = run.estimated_cost_usd
        r.tokens_per_step = r.total_tokens / r.total_steps if r.total_steps > 0 else 0.0

    # ── correctness (no LLM) ───────────────────────────────────────────────

    def _compute_correctness(self, run: AgentRun, r: EvalResult) -> None:
        if not run.expected_output or not run.actual_output:
            return

        expected = run.expected_output.strip().lower()
        actual = run.actual_output.strip().lower()

        # 1. exact match
        r.exact_match = expected == actual

        # 2. fuzzy similarity (SequenceMatcher)
        r.correctness_score = difflib.SequenceMatcher(
            None, expected, actual
        ).ratio()

        # 3. keyword coverage — what fraction of "important" words in expected
        #    appear in actual output
        stop_words = {"the", "a", "an", "is", "are", "was", "were", "be",
                      "been", "and", "or", "in", "on", "at", "to", "of",
                      "for", "with", "by", "from", "as", "it", "its"}
        expected_tokens = {
            w for w in re.findall(r"\b\w+\b", expected)
            if w not in stop_words and len(w) > 2
        }
        if expected_tokens:
            found = sum(1 for w in expected_tokens if w in actual)
            r.keyword_coverage = found / len(expected_tokens)
        else:
            r.keyword_coverage = 1.0

    # ── composite score ────────────────────────────────────────────────────

    def _compute_composite(self, r: EvalResult) -> None:
        """
        Weighted composite across objective dimensions.
        Weights are adjustable; defaults reflect typical production priorities.
        """
        scores: List[Tuple[float, float]] = []  # (score, weight)

        # tool success rate (weight 0.35)
        scores.append((r.tool_call_success_rate, 0.35))

        # step efficiency (weight 0.20)
        scores.append((r.step_efficiency_score, 0.20))

        # latency score: penalise runs > 30 s (weight 0.20)
        if r.total_latency_ms > 0:
            latency_score = max(0.0, 1.0 - r.total_latency_ms / 30_000)
            scores.append((latency_score, 0.20))

        # cost score: penalise runs > $0.10 (weight 0.10)
        if r.estimated_cost_usd >= 0:
            cost_score = max(0.0, 1.0 - r.estimated_cost_usd / 0.10)
            scores.append((cost_score, 0.10))

        # correctness (weight 0.15, only if available)
        if r.correctness_score is not None:
            scores.append((r.correctness_score, 0.15))

        if scores:
            total_weight = sum(w for _, w in scores)
            r.composite_score = sum(s * w for s, w in scores) / total_weight
        else:
            r.composite_score = 0.0
