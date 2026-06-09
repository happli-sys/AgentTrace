"""
AgentTrace 公开 Trace Schema。

目标：
- 把当前零散的 step/tool/event/snapshot 统一成稳定的公开模型
- 前端 / 存储 / 导出都只依赖这个模型
- runtime_hint / derived / adapter 只是数据来源，不改变结构
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


@dataclass
class SnapshotEnvelope:
    kind: str                  # context / memory / plan / decision / resume
    source: str                # observed / runtime_hint / derived / adapter
    payload: Dict[str, Any]


@dataclass
class Span:
    id: str
    parent_id: Optional[str]
    trace_id: str
    kind: str                  # llm / tool / skill / system
    name: str
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    latency_ms: Optional[float] = None
    status: Optional[str] = None
    group_id: Optional[str] = None
    attributes: Dict[str, Any] = field(default_factory=dict)
    snapshots: List[SnapshotEnvelope] = field(default_factory=list)
    children: List["Span"] = field(default_factory=list)


@dataclass
class Trace:
    trace_id: str
    run_id: str
    agent_name: str
    task: str
    model: str
    status: str
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    spans: List[Span] = field(default_factory=list)
    root_ids: List[str] = field(default_factory=list)
    summary: Dict[str, Any] = field(default_factory=dict)


def to_dict(obj: Any) -> Any:
    if isinstance(obj, SnapshotEnvelope):
        return {"kind": obj.kind, "source": obj.source, "payload": obj.payload}
    if isinstance(obj, Span):
        return {
            "id": obj.id,
            "parent_id": obj.parent_id,
            "trace_id": obj.trace_id,
            "kind": obj.kind,
            "name": obj.name,
            "start_time": obj.start_time,
            "end_time": obj.end_time,
            "latency_ms": obj.latency_ms,
            "status": obj.status,
            "group_id": obj.group_id,
            "attributes": obj.attributes,
            "snapshots": [to_dict(s) for s in obj.snapshots],
            "children": [to_dict(c) for c in obj.children],
        }
    if isinstance(obj, Trace):
        return {
            "trace_id": obj.trace_id,
            "run_id": obj.run_id,
            "agent_name": obj.agent_name,
            "task": obj.task,
            "model": obj.model,
            "status": obj.status,
            "start_time": obj.start_time,
            "end_time": obj.end_time,
            "root_ids": obj.root_ids,
            "summary": obj.summary,
            "spans": [to_dict(s) for s in obj.spans],
        }
    return obj
