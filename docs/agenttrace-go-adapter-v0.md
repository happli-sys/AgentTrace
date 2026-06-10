# AgentTrace Go Adapter v0

## Goal

Provide a Go-side adapter that feels close to:

```go
agenttracego.Attach(agenttracego.Config{Endpoint: "http://127.0.0.1:7760/api/v1/events"})
```

while keeping business-code changes minimal.

## Design constraints

- cannot infer LLM / Tool / Skill semantics from raw Go runtime alone
- should avoid requiring instrumentation on every function
- should work by wrapping known semantic boundaries
- should emit AgentTrace Protocol v0.1 events

## One-line user experience

### main.go

```go
func main() {
    agenttracego.Attach(agenttracego.Config{
        Endpoint: "http://127.0.0.1:7760/api/v1/events",
        AgentName: "onecode",
        Language: "go",
    })

    agent.Run("v2.9.2")
}
```

## What Attach() really does

Attach() is not magic. Internally it wires a few known boundaries:

1. run lifecycle wrapper
2. llm client wrapper
3. tool dispatcher wrapper
4. skill runner wrapper

## Automatic capture (expected)

### Run lifecycle

- `run.started`
- `run.finished`
- `run.failed`

### LLM

If the agent uses a centralized LLM client or transport:

- `llm.started`
- `llm.finished`
- `llm.failed`
- prompt / response
- token counts
- latency

### Tool

If the agent uses a centralized tool-dispatch path:

- `tool.started`
- `tool.finished`
- `tool.failed`
- input args
- output summary
- latency

### Skill

If the agent uses a centralized skill runner:

- `skill.started`
- `skill.finished`
- `skill.failed`

## Optional higher-level signals

These usually require either a central policy layer or explicit adapter calls:

- `retry.recorded`
- `fallback.recorded`
- `snapshot.plan`
- `snapshot.decision`
- `snapshot.execution`

## onecode integration boundaries discovered in PoC

### Run lifecycle

- `agent.(*Agent).ProcessInput`

### LLM boundaries

- `agent.(*Agent).ProcessInput` main `GenerateContent(...)`
- `agent/tools/subagent.go` sub-agent `GenerateContent(...)`
- `internal/llmhttp/client.go` transport layer (optional lower-level wrapper)

### Tool boundary

- `agent/tools/subagent.go` unified tool execution loop

### Skill boundary

- `agent/tools/skill.go`
- `HandleRunSkill(...)`
- `RunSkillSubAgent(...)`

## Recommended implementation model

### Layer A — protocol emitter (thin)

Responsible only for emitting AgentTrace Protocol events.

### Layer B — wrappers for semantic boundaries

- LLM wrapper
- tool wrapper
- skill wrapper
- run wrapper

### Layer C — adapter package

Public API surface:

```go
package agenttracego

type Config struct {
    Endpoint string
    AgentName string
    Language string
    ReviewLevel int
}

func Attach(cfg Config)
func StartRun(task string) string
func FinishRun(runID, output string)
func FailRun(runID string, err error)
```

## What is truly automatic vs not

### automatic

- span timing
- llm/tool/skill lifecycle if routed through wrapped boundaries
- protocol event emission

### not automatic

- arbitrary business function semantics
- plan / decision / context meaning without adapter help
- any path that bypasses wrapped llm/tool/skill boundaries

## Product implication

AgentTrace can be language-agnostic, but not semantics-agnostic.

The product promise should be:

- minimal integration
- one-line bootstrap where possible
- wrappers around semantic boundaries

not:

- magically understand every function in every language runtime
