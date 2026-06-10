"""
把当前内部运行记录映射成公开 Trace Schema。
"""
from __future__ import annotations

from typing import Any, Dict, List

from agenttrace.metrics.engine import EvalResult
from agenttrace.models import AgentRun
from agenttrace.trace_schema import Trace, Span, SnapshotEnvelope




def _compute_critical_path(spans: List[Span]) -> dict:
    if not spans:
        return {"path": [], "total_latency_ms": 0}
    by_id = {s.id: s for s in spans}
    children = {}
    roots = []
    for s in spans:
        if s.parent_id and s.parent_id in by_id:
            children.setdefault(s.parent_id, []).append(s)
        else:
            roots.append(s)

    def dfs(span: Span):
        child_list = children.get(span.id, [])
        if not child_list:
            return ([span.name], span.latency_ms or 0)
        best_path, best_cost = [], -1
        for ch in child_list:
            p, c = dfs(ch)
            if c > best_cost:
                best_path, best_cost = p, c
        return ([span.name] + best_path, (span.latency_ms or 0) + best_cost)

    best = {"path": [], "total_latency_ms": 0}
    for r in roots:
        p, c = dfs(r)
        if c > best["total_latency_ms"]:
            best = {"path": p, "total_latency_ms": c}
    return best

def map_run_to_trace(run: AgentRun, result: EvalResult) -> Trace:
    trace_id = run.run_id
    spans: List[Span] = []

    # step spans
    for step in run.steps:
        desc = step.description or ''
        if desc.startswith('llm:'):
            kind = 'llm'
            name = desc.replace('llm:', '', 1)
            attrs = {
                'input_tokens': step.input_tokens,
                'output_tokens': step.output_tokens,
                'retry_count': step.retry_count,
                'fallback_from': step.fallback_from,
                'timeout': step.timeout,
                'cancelled': step.cancelled,
            }
        elif desc.startswith('skill:'):
            kind = 'skill'
            name = desc.replace('skill:', '', 1)
            attrs = {}
        else:
            kind = 'system'
            name = desc or f'step_{step.step_index}'
            attrs = {}

        snapshots = []
        for skind, src_attr, payload in [
            ('context', 'source', getattr(step, 'context_snapshot', None)),
            ('memory',  'source', getattr(step, 'memory_snapshot', None)),
            ('plan',    'source', getattr(step, 'plan_snapshot', None)),
            ('decision','source', getattr(step, 'decision_snapshot', None)),
            ('resume',  'source', getattr(step, 'resume_snapshot', None)),
        ]:
            if payload is not None:
                source = getattr(payload, 'source', 'observed')
                snapshots.append(SnapshotEnvelope(kind=skind, source=source, payload=payload.__dict__))

        if getattr(step, 'llm_prompt', None) is not None:
            attrs['llm_prompt'] = getattr(step, 'llm_prompt')
        if getattr(step, 'llm_response', None) is not None:
            attrs['llm_response'] = getattr(step, 'llm_response')

        spans.append(Span(
            id=step.span_id,
            parent_id=step.parent_span_id,
            trace_id=trace_id,
            kind=kind,
            name=name,
            start_time=step.started_at.isoformat() if step.started_at else None,
            end_time=step.ended_at.isoformat() if step.ended_at else None,
            latency_ms=step.latency_ms,
            group_id=step.group_id,
            attributes=attrs,
            snapshots=snapshots,
        ))

        # tool spans nested under step
        for tc in step.tool_calls:
            spans.append(Span(
                id=tc.span_id,
                parent_id=tc.parent_span_id or step.span_id,
                trace_id=trace_id,
                kind='tool',
                name=tc.tool_name,
                start_time=tc.started_at.isoformat() if tc.started_at else None,
                end_time=tc.ended_at.isoformat() if tc.ended_at else None,
                latency_ms=tc.latency_ms,
                status=tc.status.value,
                group_id=tc.group_id,
                attributes={
                    'input_params': tc.input_params,
                    'error': tc.error,
                    'retry_count': tc.retry_count,
                    'fallback_from': tc.fallback_from,
                    'timeout': tc.timeout,
                    'cancelled': tc.cancelled,
                },
                snapshots=[],
            ))

    # 组装 children / root_ids
    by_id = {s.id: s for s in spans}
    root_ids = []
    for s in spans:
        if s.parent_id and s.parent_id in by_id:
            by_id[s.parent_id].children.append(s)
        else:
            root_ids.append(s.id)

    critical = _compute_critical_path(spans)
    trace = Trace(
        trace_id=trace_id,
        run_id=run.run_id,
        agent_name=run.agent_name,
        task=run.task,
        model=run.model,
        status=run.status.value,
        start_time=run.start_time.isoformat() if run.start_time else None,
        end_time=run.end_time.isoformat() if run.end_time else None,
        spans=spans,
        root_ids=root_ids,
        summary={
            'total_latency_ms': result.total_latency_ms,
            'total_tokens': result.total_tokens,
            'tool_call_success_rate': result.tool_call_success_rate,
            'composite_score': result.composite_score,
            'critical_path': critical,
        },
    )
    return trace
