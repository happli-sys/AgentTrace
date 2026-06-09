"""
OpenAI Agents SDK integration — wraps agent.run() and captures metrics.

Usage:
    from agenttrace.integrations.openai_agents import meter_agent
    from agenttrace import evaluate

    result_text, am_result = await meter_agent(
        agent, "What is the capital of France?",
        expected_output="Paris"
    )
    print(am_result.summary())
"""
from __future__ import annotations

import time
from typing import Any, Optional, Tuple

from agenttrace.collectors.runtime import RuntimeCollector
from agenttrace.metrics.engine import EvalResult, MetricsEngine

try:
    from agents import Agent, Runner
    _SDK_AVAILABLE = True
except ImportError:
    _SDK_AVAILABLE = False


engine = MetricsEngine()


async def meter_agent(
    agent: Any,
    task: str,
    expected_output: Optional[str] = None,
    agent_name: Optional[str] = None,
    model: str = "unknown",
    tags: Optional[dict] = None,
) -> Tuple[Any, EvalResult]:
    """
    Run an OpenAI Agent and return (raw_result, EvalResult).
    Captures: total latency, step latency, tool calls, token usage.
    """
    if not _SDK_AVAILABLE:
        raise ImportError("openai-agents is not installed. pip install openai-agents")

    name = agent_name or getattr(agent, "name", "openai_agent")
    collector = RuntimeCollector(
        task=task,
        agent_name=name,
        framework="openai_agents",
        model=model or getattr(agent, "model", "unknown"),
        expected_output=expected_output,
        tags=tags or {},
    )

    with collector:
        t0 = time.perf_counter()
        result = await Runner.run(agent, task)
        total_ms = (time.perf_counter() - t0) * 1000

        # extract steps from run result
        if hasattr(result, "new_items"):
            for item in result.new_items:
                itype = type(item).__name__
                if "ToolCall" in itype:
                    tool_name = getattr(item, "name", "tool") if hasattr(item, "name") \
                        else getattr(getattr(item, "raw_item", {}), "name", "tool")
                    collector.record_tool_call(
                        tool_name=str(tool_name),
                        status="success",
                        latency_ms=0,
                    )
                elif "Message" in itype or "Response" in itype:
                    usage = getattr(item, "usage", None)
                    in_tok = getattr(usage, "input_tokens", 0) if usage else 0
                    out_tok = getattr(usage, "output_tokens", 0) if usage else 0
                    collector.record_step(
                        description=itype,
                        latency_ms=total_ms / max(1, len(result.new_items)),
                        input_tokens=in_tok,
                        output_tokens=out_tok,
                    )

        # fallback: record at least one step with total time
        if not collector.run.steps:
            collector.record_step(description="agent_run", latency_ms=total_ms)

        output = getattr(result, "final_output", str(result))
        collector.set_output(str(output))

    eval_result = engine.evaluate(collector.run)
    return result, eval_result
