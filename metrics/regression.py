"""
Regression Tracker — compare current run against a stored baseline.
Answers: "Did this agent get worse after I changed the model/prompt?"
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Optional

from agenttrace.metrics.engine import EvalResult


@dataclass
class RegressionDiff:
    metric: str
    baseline_value: float
    current_value: float
    delta: float          # current - baseline
    delta_pct: float      # percentage change
    regressed: bool       # True if this metric got worse

    def __str__(self) -> str:
        arrow = "⬇️ REGRESSED" if self.regressed else "✅ ok"
        return (
            f"  {self.metric:<30} "
            f"baseline={self.baseline_value:.4f}  "
            f"current={self.current_value:.4f}  "
            f"Δ={self.delta:+.4f} ({self.delta_pct:+.1f}%)  {arrow}"
        )


@dataclass
class RegressionReport:
    run_id: str
    baseline_run_id: str
    diffs: List[RegressionDiff]

    @property
    def regressions(self) -> List[RegressionDiff]:
        return [d for d in self.diffs if d.regressed]

    @property
    def passed(self) -> bool:
        return len(self.regressions) == 0

    def summary(self) -> str:
        lines = [
            f"{'─'*55}",
            f"  Regression Report",
            f"  Baseline: {self.baseline_run_id}  →  Current: {self.run_id}",
            f"{'─'*55}",
        ]
        for d in self.diffs:
            lines.append(str(d))
        lines.append(f"{'─'*55}")
        if self.passed:
            lines.append("  🎉 No regressions detected.")
        else:
            lines.append(f"  ❌ {len(self.regressions)} regression(s) found!")
        lines.append(f"{'─'*55}")
        return "\n".join(lines)


# ── thresholds for regression detection ───────────────────────────────────
# "higher is better" metrics: regression = current < baseline - threshold
# "lower is better"  metrics: regression = current > baseline + threshold

HIGHER_IS_BETTER = {
    "tool_call_success_rate": 0.02,
    "step_efficiency_score": 0.05,
    "correctness_score": 0.05,
    "keyword_coverage": 0.05,
    "composite_score": 0.03,
}

LOWER_IS_BETTER = {
    "total_latency_ms": 0.10,        # 10% increase = regression
    "avg_step_latency_ms": 0.10,
    "estimated_cost_usd": 0.10,
    "total_tokens": 0.10,
    "redundant_steps": 1,            # absolute threshold
    "failed_tool_calls": 1,
}


class RegressionTracker:
    """
    Saves EvalResult baselines to disk (JSON) and compares future runs.
    Zero-dependency: uses the stdlib only.
    """

    def __init__(self, store_dir: str = ".agenttrace"):
        self.store_dir = Path(store_dir)
        self.store_dir.mkdir(exist_ok=True)

    def _baseline_path(self, name: str) -> Path:
        return self.store_dir / f"{name}.json"

    def save_baseline(self, result: EvalResult, name: str) -> None:
        """Save an EvalResult as the named baseline."""
        data = self._result_to_dict(result)
        with open(self._baseline_path(name), "w") as f:
            json.dump(data, f, indent=2, default=str)
        print(f"✅ Baseline '{name}' saved to {self._baseline_path(name)}")

    def load_baseline(self, name: str) -> Optional[Dict]:
        path = self._baseline_path(name)
        if not path.exists():
            return None
        with open(path) as f:
            return json.load(f)

    def compare(self, current: EvalResult, baseline_name: str) -> RegressionReport:
        """Compare current result against a stored baseline."""
        baseline_data = self.load_baseline(baseline_name)
        if baseline_data is None:
            raise FileNotFoundError(
                f"No baseline '{baseline_name}' found in {self.store_dir}. "
                f"Run save_baseline() first."
            )
        diffs = []

        for metric, threshold in HIGHER_IS_BETTER.items():
            bval = baseline_data.get(metric)
            cval = getattr(current, metric, None)
            if bval is None or cval is None:
                continue
            bval, cval = float(bval), float(cval)
            delta = cval - bval
            delta_pct = (delta / bval * 100) if bval != 0 else 0.0
            regressed = (cval < bval - threshold)
            diffs.append(RegressionDiff(metric, bval, cval, delta, delta_pct, regressed))

        for metric, threshold in LOWER_IS_BETTER.items():
            bval = baseline_data.get(metric)
            cval = getattr(current, metric, None)
            if bval is None or cval is None:
                continue
            bval, cval = float(bval), float(cval)
            delta = cval - bval
            delta_pct = (delta / bval * 100) if bval != 0 else 0.0
            regressed = (cval > bval + threshold) if isinstance(threshold, float) \
                else (cval > bval + threshold)
            diffs.append(RegressionDiff(metric, bval, cval, delta, delta_pct, regressed))

        return RegressionReport(
            run_id=current.run_id,
            baseline_run_id=baseline_data.get("run_id", "unknown"),
            diffs=diffs,
        )

    @staticmethod
    def _result_to_dict(result: EvalResult) -> Dict:
        d = {}
        for k, v in result.__dict__.items():
            if isinstance(v, dict):
                continue    # skip nested tool_stats dict for simplicity
            d[k] = v
        return d
