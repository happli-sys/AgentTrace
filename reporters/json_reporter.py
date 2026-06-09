"""JSON reporter — serialize EvalResult to dict / JSON file."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from agenttrace.metrics.engine import EvalResult
from agenttrace.models import AgentRun


class JSONReporter:

    @staticmethod
    def to_dict(result: EvalResult) -> Dict[str, Any]:
        d: Dict[str, Any] = {}
        for k, v in result.__dict__.items():
            if k == "tool_stats":
                d["tool_stats"] = {
                    name: {
                        "call_count": ts.call_count,
                        "success_count": ts.success_count,
                        "success_rate": round(ts.success_rate, 4),
                        "avg_latency_ms": round(ts.avg_latency_ms, 2),
                        "p95_latency_ms": round(ts.p95_latency_ms, 2),
                    }
                    for name, ts in v.items()
                }
            else:
                d[k] = v
        return d

    @staticmethod
    def to_json(result: EvalResult, indent: int = 2) -> str:
        return json.dumps(JSONReporter.to_dict(result), indent=indent, default=str)

    @staticmethod
    def save(result: EvalResult, path: str) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w") as f:
            f.write(JSONReporter.to_json(result))
        print(f"📄 Report saved to {p}")
