package agenttracego

import (
	"fmt"
	"time"
)

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

type runScope struct {
	runID   string
	emitter *emitter
}

func (r *runScope) ID() string { return r.runID }

func uniqueID(prefix string) string {
	return fmt.Sprintf("%s-%d", prefix, time.Now().UnixNano())
}

func (r *runScope) StartLLM(name, model string, messages any) string {
	spanID := uniqueID("llm")
	_ = r.emitter.send(protocolEvent{EventType: "llm.started", RunID: r.runID, SpanID: spanID, Payload: map[string]any{"name": name, "model": model, "messages": messages}})
	return spanID
}

func (r *runScope) FinishLLM(spanID string, response any, promptTokens, completionTokens int, latencyMs float64) {
	_ = r.emitter.send(protocolEvent{EventType: "llm.finished", RunID: r.runID, SpanID: spanID, Payload: map[string]any{"status": "success", "response": response, "input_tokens": promptTokens, "output_tokens": completionTokens, "latency_ms": latencyMs}})
}

func (r *runScope) FailLLM(spanID string, err error, latencyMs float64) {
	_ = r.emitter.send(protocolEvent{EventType: "llm.failed", RunID: r.runID, SpanID: spanID, Payload: map[string]any{"status": "failed", "error": err.Error(), "latency_ms": latencyMs}})
}

func (r *runScope) StartTool(parentSpanID, name string, input map[string]any, groupID string) string {
	spanID := uniqueID("tool")
	payload := map[string]any{"name": name, "input": input}
	if groupID != "" { payload["group_id"] = groupID }
	_ = r.emitter.send(protocolEvent{EventType: "tool.started", RunID: r.runID, SpanID: spanID, ParentSpanID: parentSpanID, Payload: payload})
	return spanID
}

func (r *runScope) FinishTool(spanID string, output any, latencyMs float64) {
	_ = r.emitter.send(protocolEvent{EventType: "tool.finished", RunID: r.runID, SpanID: spanID, Payload: map[string]any{"status": "success", "output": output, "latency_ms": latencyMs}})
}

func (r *runScope) FailTool(spanID string, err error, latencyMs float64) {
	_ = r.emitter.send(protocolEvent{EventType: "tool.failed", RunID: r.runID, SpanID: spanID, Payload: map[string]any{"status": "failed", "error": err.Error(), "latency_ms": latencyMs}})
}

func (r *runScope) StartSkill(name string, input map[string]any) string {
	spanID := uniqueID("skill")
	_ = r.emitter.send(protocolEvent{EventType: "skill.started", RunID: r.runID, SpanID: spanID, Payload: map[string]any{"name": name, "input": input}})
	return spanID
}

func (r *runScope) FinishSkill(spanID string, output any, latencyMs float64) {
	_ = r.emitter.send(protocolEvent{EventType: "skill.finished", RunID: r.runID, SpanID: spanID, Payload: map[string]any{"status": "success", "output": output, "latency_ms": latencyMs}})
}

func (r *runScope) FailSkill(spanID string, err error, latencyMs float64) {
	_ = r.emitter.send(protocolEvent{EventType: "skill.failed", RunID: r.runID, SpanID: spanID, Payload: map[string]any{"status": "failed", "error": err.Error(), "latency_ms": latencyMs}})
}

func (r *runScope) SnapshotPlan(spanID string, plan map[string]any) {
	_ = r.emitter.send(protocolEvent{EventType: "snapshot.plan", RunID: r.runID, SpanID: spanID, Payload: plan})
}

func (r *runScope) SnapshotDecision(spanID string, decision map[string]any) {
	_ = r.emitter.send(protocolEvent{EventType: "snapshot.decision", RunID: r.runID, SpanID: spanID, Payload: decision})
}

func (r *runScope) SnapshotExecution(spanID string, execution map[string]any) {
	_ = r.emitter.send(protocolEvent{EventType: "snapshot.execution", RunID: r.runID, SpanID: spanID, Payload: execution})
}

func (r *runScope) Retry(spanID string, retryCount int, reason string, backoffMs float64) {
	_ = r.emitter.send(protocolEvent{EventType: "retry.recorded", RunID: r.runID, SpanID: spanID, Payload: map[string]any{"retry_count": retryCount, "reason": reason, "backoff_ms": backoffMs}})
}

func (r *runScope) Fallback(spanID, from, to, reason string) {
	_ = r.emitter.send(protocolEvent{EventType: "fallback.recorded", RunID: r.runID, SpanID: spanID, Payload: map[string]any{"from": from, "to": to, "reason": reason}})
}

func (r *runScope) Finish(output string) {
	_ = r.emitter.send(protocolEvent{EventType: "run.finished", RunID: r.runID, Payload: map[string]any{"status": "completed", "output": output}})
}

func (r *runScope) Fail(err error) {
	_ = r.emitter.send(protocolEvent{EventType: "run.failed", RunID: r.runID, Payload: map[string]any{"status": "failed", "error": err.Error()}})
}
