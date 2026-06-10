# agenttrace-go API sketch

## Bootstrap

```go
package main

import (
    "lang/agent"
    "github.com/happli-sys/agenttrace-go"
)

func main() {
    agenttracego.Attach(agenttracego.Config{
        Endpoint:    "http://127.0.0.1:7760/api/v1/events",
        AgentName:   "onecode",
        Language:    "go",
        ReviewLevel: 2,
    })

    agent.Run("v2.9.2")
}
```

## Minimal lifecycle API

```go
type Config struct {
    Endpoint    string
    AgentName   string
    Language    string
    ReviewLevel int
}

func Attach(cfg Config)
func Enabled() bool
```

## Run scope API

```go
type RunScope interface {
    ID() string
    StartLLM(name, model string, messages any) string
    FinishLLM(spanID string, response any, promptTokens, completionTokens int, latencyMs float64)
    FailLLM(spanID string, err error, latencyMs float64)

    StartTool(parentSpanID, name string, input map[string]any, groupID string) string
    FinishTool(spanID string, output any, latencyMs float64)
    FailTool(spanID string, err error, latencyMs float64)

    StartSkill(name string, input map[string]any) string
    FinishSkill(spanID string, output any, latencyMs float64)
    FailSkill(spanID string, err error, latencyMs float64)

    SnapshotPlan(spanID string, plan map[string]any)
    SnapshotDecision(spanID string, decision map[string]any)
    SnapshotExecution(spanID string, execution map[string]any)

    Retry(spanID string, retryCount int, reason string, backoffMs float64)
    Fallback(spanID, from, to, reason string)

    Finish(output string)
    Fail(err error)
}

func StartRun(task string, opts ...RunOption) RunScope
```

## Integration patterns

### Pattern 1: wrap centralized agent loop
- create one `RunScope` per user task
- finish/fail on exit

### Pattern 2: wrap centralized LLM client
- call `StartLLM / FinishLLM / FailLLM`

### Pattern 3: wrap centralized tool dispatcher
- call `StartTool / FinishTool / FailTool`

### Pattern 4: wrap centralized skill runner
- call `StartSkill / FinishSkill / FailSkill`

## Adapter guidance

The adapter should prefer wrapping:
- agent entrypoint
- llm transport/client
- tool dispatcher loop
- skill runner

and avoid per-function instrumentation.
