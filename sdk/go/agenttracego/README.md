# agenttrace-go (prototype)

A minimal Go-side prototype for AgentTrace Protocol v0.1.

## Intended usage

```go
agenttracego.Attach(agenttracego.Config{
    Endpoint:  "http://127.0.0.1:7760/api/v1/events",
    AgentName: "onecode",
    Language:  "go",
})

run := agenttracego.StartRun("查北京天气")
llmSpan := run.StartLLM("llm.chat", "glm-5.1", messages)
run.FinishLLM(llmSpan, response, 120, 45, 2300)
run.Finish("最终输出")
```
