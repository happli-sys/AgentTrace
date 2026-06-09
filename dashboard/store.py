"""
Session 持久化存储。
每次 AgentTrace session 结束后，把完整数据写入本地文件。

存储结构：
  {store_dir}/
    sessions/
      {run_id}.json          ← 单条 session 完整数据
    sessions.jsonl           ← 所有 session 摘要，append-only，供前端列表
"""
from __future__ import annotations

import json
import os
from datetime import datetime
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from agenttrace.metrics.engine import EvalResult
from agenttrace.models import AgentRun, StepRecord, ToolCallRecord
from agenttrace.trace_mapper import map_run_to_trace
from agenttrace.diagnostics import build_diagnostics
from agenttrace.trace_schema import to_dict as trace_to_dict

def _serialize_snapshot(obj):
    if obj is None:
        return None
    if hasattr(obj, '__dict__'):
        out = {}
        for k, v in obj.__dict__.items():
            out[k] = v
        return out
    return obj

# 当前主进程（本次 agent 启动）的会话批次 ID
_CURRENT_BOOT_ID = None
_CURRENT_RUN_DIR = None

def set_boot_id(boot_id: str) -> None:
    global _CURRENT_BOOT_ID
    _CURRENT_BOOT_ID = boot_id

def set_run_dir(run_dir: str) -> None:
    global _CURRENT_RUN_DIR
    _CURRENT_RUN_DIR = run_dir

def get_run_dir() -> str | None:
    return _CURRENT_RUN_DIR

def get_boot_id() -> str | None:
    return _CURRENT_BOOT_ID


def _serialize_tool_call(tc: ToolCallRecord) -> Dict:
    return {
        "call_id":    tc.call_id,
        "tool_name":  tc.tool_name,
        "status":     tc.status.value,
        "latency_ms": round(tc.latency_ms, 2),
        "error":      tc.error,
        "timestamp":  tc.timestamp.isoformat(),
        "span_id":    tc.span_id,
        "parent_span_id": tc.parent_span_id,
        "group_id":   tc.group_id,
        "started_at": tc.started_at.isoformat() if tc.started_at else None,
        "ended_at":   tc.ended_at.isoformat() if tc.ended_at else None,
    }


def _serialize_step(step: StepRecord) -> Dict:
    # 从 description 判断类型
    desc = step.description or ""
    if desc.startswith("llm:"):
        call_type = "llm"
    elif desc.startswith("skill:"):
        call_type = "skill"
    elif desc.startswith("agent_turn"):
        call_type = "tool"
    else:
        call_type = "step"

    return {
        "step_index":    step.step_index,
        "description":   desc,
        "call_type":     call_type,
        "latency_ms":    round(step.latency_ms, 2),
        "input_tokens":  step.input_tokens,
        "output_tokens": step.output_tokens,
        "tool_calls":    [_serialize_tool_call(tc) for tc in step.tool_calls],
        "timestamp":     step.timestamp.isoformat(),
        "span_id":       step.span_id,
        "parent_span_id":step.parent_span_id,
        "group_id":      step.group_id,
        "started_at":    step.started_at.isoformat() if step.started_at else None,
        "ended_at":      step.ended_at.isoformat() if step.ended_at else None,
        "llm_prompt":    getattr(step, "llm_prompt", None),
        "llm_response":  getattr(step, "llm_response", None),
        "context_snapshot":  _serialize_snapshot(getattr(step, "context_snapshot", None)),
        "memory_snapshot":   _serialize_snapshot(getattr(step, "memory_snapshot", None)),
        "plan_snapshot":     _serialize_snapshot(getattr(step, "plan_snapshot", None)),
        "decision_snapshot": _serialize_snapshot(getattr(step, "decision_snapshot", None)),
        "resume_snapshot":   _serialize_snapshot(getattr(step, "resume_snapshot", None)),
        "execution_snapshot": _serialize_snapshot(getattr(step, "execution_snapshot", None)),
    }


def _build_events(run: AgentRun) -> list[dict]:
    """把 steps + tool_calls 展平成真实发生顺序的事件流。"""
    events = []
    for step in run.steps:
        desc = step.description or ""
        if desc.startswith("llm:"):
            events.append({
                "type": "llm",
                "name": desc.replace("llm:", "", 1),
                "latency_ms": round(step.latency_ms, 2),
                "input_tokens": step.input_tokens,
                "output_tokens": step.output_tokens,
                "timestamp": step.timestamp.isoformat(),
                "span_id": step.span_id,
                "parent_span_id": step.parent_span_id,
                "group_id": step.group_id,
                "started_at": step.started_at.isoformat() if step.started_at else None,
                "ended_at": step.ended_at.isoformat() if step.ended_at else None,
                "llm_prompt": getattr(step, "llm_prompt", None),
                "llm_response": getattr(step, "llm_response", None),
                "context_snapshot": _serialize_snapshot(getattr(step, "context_snapshot", None)),
                "memory_snapshot": _serialize_snapshot(getattr(step, "memory_snapshot", None)),
                "plan_snapshot": _serialize_snapshot(getattr(step, "plan_snapshot", None)),
                "decision_snapshot": _serialize_snapshot(getattr(step, "decision_snapshot", None)),
                "resume_snapshot": _serialize_snapshot(getattr(step, "resume_snapshot", None)),
                "execution_snapshot": _serialize_snapshot(getattr(step, "execution_snapshot", None)),
            })
        elif desc.startswith("skill:"):
            events.append({
                "type": "skill",
                "name": desc.replace("skill:", "", 1),
                "latency_ms": round(step.latency_ms, 2),
                "timestamp": step.timestamp.isoformat(),
                "span_id": step.span_id,
                "parent_span_id": step.parent_span_id,
                "group_id": step.group_id,
                "started_at": step.started_at.isoformat() if step.started_at else None,
                "ended_at": step.ended_at.isoformat() if step.ended_at else None,
                "llm_prompt": getattr(step, "llm_prompt", None),
                "llm_response": getattr(step, "llm_response", None),
                "context_snapshot": _serialize_snapshot(getattr(step, "context_snapshot", None)),
                "memory_snapshot": _serialize_snapshot(getattr(step, "memory_snapshot", None)),
                "plan_snapshot": _serialize_snapshot(getattr(step, "plan_snapshot", None)),
                "decision_snapshot": _serialize_snapshot(getattr(step, "decision_snapshot", None)),
                "resume_snapshot": _serialize_snapshot(getattr(step, "resume_snapshot", None)),
                "execution_snapshot": _serialize_snapshot(getattr(step, "execution_snapshot", None)),
            })
        elif desc.startswith("agent_turn"):
            # agent_turn 只是兜底 step，本身不展示，真正展示 tool_calls
            pass
        else:
            events.append({
                "type": "step",
                "name": desc or f"step_{step.step_index}",
                "latency_ms": round(step.latency_ms, 2),
                "timestamp": step.timestamp.isoformat(),
            })

        for tc in step.tool_calls:
            events.append({
                "type": "tool",
                "name": tc.tool_name,
                "status": tc.status.value,
                "latency_ms": round(tc.latency_ms, 2),
                "error": tc.error,
                "timestamp": tc.timestamp.isoformat(),
                "span_id": tc.span_id,
                "parent_span_id": tc.parent_span_id,
                "group_id": tc.group_id,
                "started_at": tc.started_at.isoformat() if tc.started_at else None,
                "ended_at": tc.ended_at.isoformat() if tc.ended_at else None,
                "input_params": tc.input_params,
            })

    # 按 timestamp 排序，确保真实顺序
    events.sort(key=lambda e: e.get("timestamp") or "")
    return events


def build_session_doc(run: AgentRun, result: EvalResult) -> Dict[str, Any]:
    """把 AgentRun + EvalResult 合并成一份完整的 session 文档。"""
    trace = map_run_to_trace(run, result)
    doc = {
        "trace":       trace_to_dict(trace),
        # ── 基础信息 ────────────────────────────────────────────────────────
        "run_id":       run.run_id,
        "boot_id":      _CURRENT_BOOT_ID,
        "agent_name":   run.agent_name,
        "task":         run.task,
        "framework":    run.framework,
        "model":        run.model,
        "status":       run.status.value,
        "start_time":   run.start_time.isoformat() if run.start_time else None,
        "end_time":     run.end_time.isoformat()   if run.end_time   else None,

        # ── 对话内容 ────────────────────────────────────────────────────────
        "input":        run.task,
        "output":       run.actual_output or "",

        # ── 调用链（按时间顺序）──────────────────────────────────────────────
        "steps":        [_serialize_step(s) for s in run.steps],
        "tool_calls":   [_serialize_tool_call(tc) for tc in run.all_tool_calls],
        "events":       _build_events(run),
        "llm_review":  getattr(run, "llm_review", None),

        # ── 评测指标 ────────────────────────────────────────────────────────
        "metrics": {
            "total_latency_ms":      round(result.total_latency_ms, 1),
            "avg_step_latency_ms":   round(result.avg_step_latency_ms, 1),
            "p95_step_latency_ms":   round(result.p95_step_latency_ms, 1),
            "total_steps":           result.total_steps,
            "redundant_steps":       result.redundant_steps,
            "step_efficiency_score": round(result.step_efficiency_score, 3),
            "total_tool_calls":      result.total_tool_calls,
            "failed_tool_calls":     result.failed_tool_calls,
            "tool_call_success_rate":round(result.tool_call_success_rate, 3),
            "avg_tool_latency_ms":   round(result.avg_tool_latency_ms, 1),
            "total_input_tokens":    result.total_input_tokens,
            "total_output_tokens":   result.total_output_tokens,
            "total_tokens":          result.total_tokens,
            "estimated_cost_usd":    round(result.estimated_cost_usd, 6),
            "composite_score":       round(result.composite_score, 3),
            "correctness_score":     round(result.correctness_score, 3) if result.correctness_score else None,
            "llm_review_summary":    result.llm_review_summary or None,
            "llm_review_findings":   result.llm_review_findings,
            "llm_review_level":      getattr(result, "llm_review_level", 2),
            "tool_stats": {
                name: {
                    "call_count":    ts.call_count,
                    "success_rate":  round(ts.success_rate, 3),
                    "avg_latency_ms":round(ts.avg_latency_ms, 1),
                    "p95_latency_ms":round(ts.p95_latency_ms, 1),
                }
                for name, ts in result.tool_stats.items()
            },
        },
    }
    doc["diagnostics"] = build_diagnostics(doc)
    return doc


class SessionStore:
    """
    把每次 session 写入本地文件。
    线程安全（写文件用追加模式 + os.fsync）。
    """

    def __init__(self, store_dir: str = "listen"):
        self.store_dir    = Path(store_dir)
        run_dir = _CURRENT_RUN_DIR or datetime.now().strftime("%Y%m%d-%H%M")
        self.run_root     = self.store_dir / run_dir
        self.sessions_dir = self.run_root
        self.index_file   = self.run_root / "sessions.jsonl"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

    def save(self, run: AgentRun, result: EvalResult) -> Dict[str, Any]:
        """保存一条 session，返回文档 dict。"""
        doc = build_session_doc(run, result)

        # 写完整文档
        detail_path = self.sessions_dir / f"{run.run_id}.json"
        detail_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2))

        # 追加摘要到 sessions.jsonl（前端列表用）
        summary = {
            "run_id":          doc["run_id"],
            "boot_id":         doc.get("boot_id"),
            "task":            doc["task"][:80],
            "model":           doc["model"],
            "start_time":      doc["start_time"],
            "total_latency_ms":doc["metrics"]["total_latency_ms"],
            "total_tokens":    doc["metrics"]["total_tokens"],
            "composite_score": doc["metrics"]["composite_score"],
            "status":          doc["status"],
            "total_tool_calls":doc["metrics"]["total_tool_calls"],
            "step_count":      len(doc["steps"]),
        }
        with open(self.index_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(summary, ensure_ascii=False) + "\n")

        return doc

    def list_sessions(self, limit: int = 100) -> List[Dict]:
        """返回当前 boot_id 的最新 N 条 session 摘要（最新在前）。"""
        if not self.index_file.exists():
            return []
        text = self.index_file.read_text(encoding="utf-8").strip()
        if not text:
            return []
        lines = text.splitlines()
        summaries = []
        current_boot = _CURRENT_BOOT_ID
        for line in reversed(lines[-1000:]):
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if current_boot is not None and item.get("boot_id") != current_boot:
                continue
            summaries.append(item)
            if len(summaries) >= limit:
                break
        return summaries

    def get_session(self, run_id: str) -> Optional[Dict]:
        """返回单条 session 完整数据。"""
        path = self.sessions_dir / f"{run_id}.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))


# 全局单例
_default_store: Optional[SessionStore] = None


def get_store(store_dir: str = "listen") -> SessionStore:
    global _default_store
    if _default_store is None:
        _default_store = SessionStore(store_dir)
    return _default_store
