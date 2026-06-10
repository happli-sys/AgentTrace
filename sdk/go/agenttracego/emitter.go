package agenttracego

import (
	"bytes"
	"encoding/json"
	"net/http"
	"time"
)

type protocolAgent struct {
	Name     string `json:"name,omitempty"`
	Language string `json:"language,omitempty"`
	Version  string `json:"version,omitempty"`
	Model    string `json:"model,omitempty"`
}

type protocolEvent struct {
	SpecVersion  string         `json:"spec_version"`
	EventType    string         `json:"event_type"`
	Timestamp    string         `json:"timestamp"`
	RunID        string         `json:"run_id"`
	SpanID       string         `json:"span_id,omitempty"`
	ParentSpanID string         `json:"parent_span_id,omitempty"`
	Agent        protocolAgent  `json:"agent,omitempty"`
	Payload      map[string]any `json:"payload,omitempty"`
}

type emitter struct {
	cfg    Config
	client *http.Client
}

func newEmitter(cfg Config) *emitter {
	if cfg.Language == "" {
		cfg.Language = "go"
	}
	return &emitter{
		cfg: cfg,
		client: &http.Client{Timeout: 2 * time.Second},
	}
}

func (e *emitter) send(evt protocolEvent) error {
	evt.SpecVersion = "0.1"
	evt.Timestamp = time.Now().UTC().Format(time.RFC3339Nano)
	evt.Agent = protocolAgent{
		Name:     e.cfg.AgentName,
		Language: e.cfg.Language,
		Version:  e.cfg.AgentVersion,
		Model:    e.cfg.Model,
	}
	body, err := json.Marshal(evt)
	if err != nil {
		return err
	}
	req, err := http.NewRequest(http.MethodPost, e.cfg.Endpoint, bytes.NewReader(body))
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/json")
	resp, err := e.client.Do(req)
	if resp != nil {
		defer resp.Body.Close()
	}
	return err
}
