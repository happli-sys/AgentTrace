"""
LangChain integration — drop-in CallbackHandler.

Usage:
    from agenttrace.integrations.langchain import AgentMeterCallback
    from agenttrace import evaluate

    cb = AgentMeterCallback(task="Summarise the report", expected_output="...")
    agent.invoke({"input": "..."}, config={"callbacks": [cb]})
    result = evaluate(cb.run)
    print(result.summary())
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Union
from uuid import UUID

from agenttrace.collectors.runtime import RuntimeCollector
from agenttrace.models import ToolCallStatus, ToolCallRecord, StepRecord

try:
    from langchain_core.callbacks.base import BaseCallbackHandler
    from langchain_core.outputs import LLMResult
    _LANGCHAIN_AVAILABLE = True
except ImportError:
    _LANGCHAIN_AVAILABLE = False
    BaseCallbackHandler = object   # type: ignore


class AgentMeterCallback(BaseCallbackHandler if _LANGCHAIN_AVAILABLE else object):
    """
    LangChain callback that feeds into AgentMeter's RuntimeCollector.
    Captures: LLM latency, token usage, tool calls, errors.
    """

    def __init__(
        self,
        task: str = "",
        agent_name: str = "langchain_agent",
        expected_output: Optional[str] = None,
        tags: Optional[Dict[str, str]] = None,
    ):
        if not _LANGCHAIN_AVAILABLE:
            raise ImportError("langchain-core is not installed. pip install langchain-core")
        super().__init__()
        self.collector = RuntimeCollector(
            task=task,
            agent_name=agent_name,
            framework="langchain",
            expected_output=expected_output,
            tags=tags or {},
        )
        self.collector.__enter__()
        self._llm_start_times: Dict[str, float] = {}
        self._tool_start_times: Dict[str, float] = {}

    @property
    def run(self):
        return self.collector.run

    # ── LLM events ─────────────────────────────────────────────────────────

    def on_llm_start(self, serialized: Dict, prompts: List[str],
                     run_id: UUID, **kwargs) -> None:
        self._llm_start_times[str(run_id)] = time.perf_counter()

    def on_llm_end(self, response: "LLMResult", run_id: UUID, **kwargs) -> None:
        elapsed = (time.perf_counter() -
                   self._llm_start_times.pop(str(run_id), time.perf_counter())) * 1000

        input_tokens = output_tokens = 0
        if response.llm_output and "token_usage" in response.llm_output:
            usage = response.llm_output["token_usage"]
            input_tokens = usage.get("prompt_tokens", 0)
            output_tokens = usage.get("completion_tokens", 0)

        text = ""
        if response.generations:
            flat = response.generations[0]
            if flat:
                text = getattr(flat[0], "text", "")

        self.collector.record_step(
            description="llm_call",
            latency_ms=elapsed,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    def on_llm_error(self, error: Exception, run_id: UUID, **kwargs) -> None:
        self._llm_start_times.pop(str(run_id), None)

    # ── Tool events ────────────────────────────────────────────────────────

    def on_tool_start(self, serialized: Dict, input_str: str,
                      run_id: UUID, **kwargs) -> None:
        self._tool_start_times[str(run_id)] = time.perf_counter()

    def on_tool_end(self, output: str, run_id: UUID, **kwargs) -> None:
        elapsed = (time.perf_counter() -
                   self._tool_start_times.pop(str(run_id), time.perf_counter())) * 1000
        tool_name = kwargs.get("name", "unknown_tool")
        self.collector.record_tool_call(
            tool_name=tool_name,
            status="success",
            latency_ms=elapsed,
            output=str(output)[:200],
        )

    def on_tool_error(self, error: Exception, run_id: UUID, **kwargs) -> None:
        elapsed = (time.perf_counter() -
                   self._tool_start_times.pop(str(run_id), time.perf_counter())) * 1000
        tool_name = kwargs.get("name", "unknown_tool")
        self.collector.record_tool_call(
            tool_name=tool_name,
            status="failed",
            latency_ms=elapsed,
            error=str(error),
        )

    # ── Agent finish ───────────────────────────────────────────────────────

    def on_agent_finish(self, finish: Any, **kwargs) -> None:
        output = getattr(finish, "return_values", {}).get("output", "")
        self.collector.run.actual_output = str(output)
        self.collector.__exit__(None, None, None)
