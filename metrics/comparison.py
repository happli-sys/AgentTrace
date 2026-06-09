"""
Multi-run Comparison — compare two or more AgentRun results side-by-side.
Use case: "Is CrewAI or LangGraph faster for this task?"
          "Does GPT-4o or Claude-3.5 use fewer tokens?"
"""
from __future__ import annotations

from typing import List, Tuple
from agenttrace.metrics.engine import EvalResult


COMPARE_METRICS = [
    ("total_latency_ms",         "Total latency (ms)",        "lower"),
    ("avg_step_latency_ms",      "Avg step latency (ms)",     "lower"),
    ("total_steps",              "Steps",                     "lower"),
    ("redundant_steps",          "Redundant steps",           "lower"),
    ("step_efficiency_score",    "Step efficiency",           "higher"),
    ("total_tool_calls",         "Tool calls",                "lower"),
    ("tool_call_success_rate",   "Tool success rate",         "higher"),
    ("avg_tool_latency_ms",      "Avg tool latency (ms)",     "lower"),
    ("total_tokens",             "Total tokens",              "lower"),
    ("estimated_cost_usd",       "Est. cost (USD)",           "lower"),
    ("correctness_score",        "Correctness score",         "higher"),
    ("composite_score",          "🏅 Composite score",        "higher"),
]


def compare(results: List[EvalResult]) -> str:
    """
    Render a side-by-side comparison table of multiple EvalResults.
    Highlights the best value for each metric with a ★.
    """
    if not results:
        return "No results to compare."

    names = [f"{r.agent_name}\n({r.framework}/{r.model})" for r in results]
    col_w = max(20, max(len(n.split('\n')[0]) for n in names) + 2)
    metric_w = 28

    # header
    header = f"{'Metric':<{metric_w}}" + "".join(
        f"{r.agent_name[:col_w-2]:<{col_w}}" for r in results
    )
    sep = "─" * (metric_w + col_w * len(results))

    rows = [sep, header, sep]

    for key, label, direction in COMPARE_METRICS:
        values = [getattr(r, key, None) for r in results]
        # skip if all None
        if all(v is None for v in values):
            continue

        # find best index
        valid = [(i, v) for i, v in enumerate(values) if v is not None]
        if direction == "higher":
            best_i = max(valid, key=lambda x: x[1])[0]
        else:
            best_i = min(valid, key=lambda x: x[1])[0]

        row = f"{label:<{metric_w}}"
        for i, v in enumerate(values):
            if v is None:
                cell = "N/A"
            elif isinstance(v, float):
                if "usd" in key:
                    cell = f"${v:.5f}"
                elif "rate" in key or "score" in key or "efficiency" in key:
                    cell = f"{v:.3f}"
                else:
                    cell = f"{v:,.1f}"
            else:
                cell = str(v)

            star = " ★" if i == best_i else "  "
            row += f"{cell + star:<{col_w}}"
        rows.append(row)

    rows.append(sep)
    rows.append(f"  ★ = best value for that metric")
    rows.append(sep)
    return "\n".join(rows)
