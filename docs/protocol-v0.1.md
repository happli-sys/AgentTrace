# AgentTrace Protocol v0.1

AgentTrace Protocol v0.1 is a language-agnostic event protocol for AI agent runtime tracing.

## Goals

- support Python / Go / Node / Java style agents
- capture LLM / Tool / Skill execution
- capture retries / fallback / stop reasons
- attach optional state snapshots
- stream events into AgentTrace for storage, dashboard, diagnostics, and review

## Event envelope

Every event is a JSON object:

```json
{
  "spec_version": "0.1",
  "event_type": "tool.finished",
  "timestamp": "2026-06-10T10:30:15.123Z",
  "run_id": "run_123",
  "span_id": "span_456",
  "parent_span_id": "span_root",
  "agent": {
    "name": "demo-agent",
    "language": "go",
    "version": "0.1.0"
  },
  "payload": {}
}
```

## Core event types

### Run lifecycle

- `run.started`
- `run.finished`
- `run.failed`

### LLM span

- `llm.started`
- `llm.finished`
- `llm.failed`

### Tool span

- `tool.started`
- `tool.finished`
- `tool.failed`

### Skill span

- `skill.started`
- `skill.finished`
- `skill.failed`

### Snapshots

- `snapshot.context`
- `snapshot.plan`
- `snapshot.decision`
- `snapshot.resume`
- `snapshot.execution`

### Signals

- `retry.recorded`
- `fallback.recorded`
- `approval.required`
- `handoff.required`
- `interrupt.recorded`
- `stop.recorded`

## Transport

### Single event

`POST /api/v1/events`

### Batch events

`POST /api/v1/events/batch`

## v0.1 minimum recommended payloads

### run.started

```json
{
  "task": "查北京天气",
  "session_id": "sess_001",
  "framework": "custom",
  "model_hint": "glm-5.1"
}
```

### llm.started

```json
{
  "name": "llm.chat",
  "provider": "openai-compatible",
  "model": "glm-5.1",
  "messages": [],
  "system_prompt": "..."
}
```

### llm.finished

```json
{
  "status": "success",
  "response": {},
  "input_tokens": 120,
  "output_tokens": 45,
  "latency_ms": 2300
}
```

### tool.started

```json
{
  "name": "tools.get_weather",
  "input": {"city": "北京"},
  "group_id": "weather_queries"
}
```

### tool.finished

```json
{
  "status": "success",
  "output": {"city": "北京", "temp": 23},
  "latency_ms": 150
}
```

### retry.recorded

```json
{
  "retry_count": 1,
  "reason": "tool failed",
  "backoff_ms": 0
}
```

### fallback.recorded

```json
{
  "from": "tools.flaky_weather",
  "to": "tools.get_weather",
  "reason": "upstream unavailable"
}
```
