"""CSV reporter — append EvalResult rows to a CSV for trend analysis."""
from __future__ import annotations

import csv
import os
from pathlib import Path
from typing import List

from agenttrace.metrics.engine import EvalResult

FIELDS = [
    "run_id", "agent_name", "framework", "model", "task",
    "total_latency_ms", "avg_step_latency_ms", "p95_step_latency_ms",
    "total_steps", "redundant_steps", "step_efficiency_score",
    "total_tool_calls", "failed_tool_calls", "tool_call_success_rate",
    "avg_tool_latency_ms", "total_tokens", "estimated_cost_usd",
    "correctness_score", "keyword_coverage", "composite_score",
]


class CSVReporter:

    @staticmethod
    def append(result: EvalResult, path: str) -> None:
        p = Path(path)
        write_header = not p.exists()
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
            if write_header:
                writer.writeheader()
            row = {k: getattr(result, k, None) for k in FIELDS}
            writer.writerow(row)
        print(f"📊 Row appended to {p}")
