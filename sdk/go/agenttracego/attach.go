package agenttracego

var defaultEmitter *emitter

func Attach(cfg Config) {
	defaultEmitter = newEmitter(cfg)
}

func Enabled() bool {
	return defaultEmitter != nil && defaultEmitter.cfg.Endpoint != ""
}

func StartRun(task string) RunScope {
	runID := uniqueID("run")
	if defaultEmitter != nil {
		_ = defaultEmitter.send(protocolEvent{EventType: "run.started", RunID: runID, Payload: map[string]any{"task": task, "framework": "custom", "model_hint": defaultEmitter.cfg.Model}})
	}
	return &runScope{runID: runID, emitter: defaultEmitter}
}
