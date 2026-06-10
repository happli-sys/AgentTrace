# AgentTrace

**Open-source runtime tracing and diagnostics for AI agent execution flows.**

AgentTrace helps you see **what your agent actually did** at runtime — not just whether the final answer looks good.

It captures and visualizes:

- `LLM` calls
- `Tool` calls
- `Skill` execution
- parallel branches
- retries / fallback chains
- prompt / response payloads
- execution-state snapshots
- post-run review and diagnostics

If you want something closer to **pprof + tracing + agent diagnostics**, AgentTrace is built for that.

---

## Why AgentTrace

Most agent tooling focuses on one of two things:

- **output evaluation** — “was the answer good?”
- **framework abstraction** — “how do I build the agent?”

AgentTrace focuses on a different question:

> **What exactly happened during execution, and why did the agent behave that way?**

That means AgentTrace is optimized for:

- debugging execution flow
- diagnosing redundancy and failure recovery
- understanding tool usage patterns
- inspecting LLM prompts / responses in context
- observing runtime state changes across a run

---

## Core capabilities

- Trace `LLM / Tool / Skill` execution flows
- Capture parallel, retry, fallback, and repeated-call patterns
- Record `Prompt / Response / Context / Plan / Execution` snapshots
- Persist runs locally and inspect them in a built-in dashboard
- Review runs with an LLM after execution
- Generate structured diagnostics: critical path, recovery chains, redundant calls, suspicious decisions

---

## What you get

### Execution tracing

AgentTrace records a runtime trace for each session, including:

- span type
- start / end time
- latency
- status
- input parameters
- grouping / parent-child relationships

### Structured state snapshots

For LLM spans, AgentTrace can capture:

- `ContextSnapshot`
- `MemorySnapshot`
- `PlanSnapshot`
- `DecisionSnapshot`
- `ResumeSnapshot`
- `ExecutionSnapshot`

### Diagnostics

AgentTrace builds a diagnostics view on top of the trace:

- critical path
- failed tool calls
- recovery chains
- redundant tool clusters
- suspicious decisions
- filtered review findings

### LLM review

After each run, AgentTrace can ask an LLM to review the recorded execution flow and flag:

- redundant tool calls
- wrong tool choices
- suspicious fallback behavior
- unnecessary skill execution
- likely execution-flow issues

Review strictness is configurable:

- `review_level=1` → tolerant
- `review_level=2` → balanced (default)
- `review_level=3` → strict

---

## Dashboard

AgentTrace includes a local dashboard at:

- `http://localhost:3500`

Current UI features include:

- session list
- execution timeline
- parallel-lane view
- collapsed repeated-tool clusters
- prompt / response modal for LLM spans
- execution-state tabs
- diagnostics panel
- LLM review panel
- collapsible final agent output

---

## Quick start

### 1. Install from source

```bash
git clone https://github.com/happli-sys/AgentTrace.git
cd AgentTrace
pip install -e .
```

### 2. Patch once, trace every run

```python
import agenttrace
from my_agent import run

agenttrace.patch(
    "my_agent.tools",
    "my_agent.skills",
    "my_agent.llm",
    llm_modules=["my_agent.llm"],
    skill_modules=["my_agent.skills"],
    review_level=2,
)

output = agenttrace.session("查北京天气并计算 1+2")(run)("查北京天气并计算 1+2")
print(output)
print(agenttrace.last_result().summary())
```

### 3. Start the dashboard

```python
from agenttrace.dashboard.server import start_server

start_server(port=3500)
```

Open:

- `http://localhost:3500`

---

## Demo agent

This repo includes a demo agent that intentionally exercises multiple tracing scenarios:

- `bash`
- `read`
- `grep`
- `calculate`
- `get_weather`
- `flaky_weather`
- `weather_report_skill`
- parallel weather queries
- fallback to stable tools

Run it:

```bash
python examples/demo_agent/main.py
```

Try this stress prompt:

```text
分析当前目录下的项目；bash pwd；read examples/demo_agent/tools.py；grep calculate examples/demo_agent；查北京和西安的天气，并计算1123123123+1283123；生成北京天气播报；最后总结。
```

---

## Integration model

AgentTrace works best for:

- custom Python agents with source code
- local development environments
- CLI / hook-based agents
- runtime debugging and diagnostics workflows

The primary integration pattern is intentionally lightweight:

- patch modules once
- wrap runs with `session(...)`
- inspect results locally

---

## Project scope

AgentTrace is currently optimized as:

- a **runtime tracing tool**
- a **local-first diagnostics tool**
- a **developer-facing execution inspector**

It is **not** currently focused on being:

- a hosted eval platform
- a benchmark leaderboard
- a dataset management system
- a full SaaS observability suite

---

## Still useful for objective metrics

Although AgentTrace now centers on tracing and diagnostics, it still retains objective runtime metrics such as:

- total latency
- avg / p95 step latency
- tool success rate
- token usage
- estimated cost
- step efficiency
- correctness (if `expected_output` is provided)
- regression tracking
- comparison helpers

---

## Development

```bash
git clone https://github.com/happli-sys/AgentTrace.git
cd AgentTrace
pip install -e ".[dev]"
pytest tests/
```

---

## License

MIT
