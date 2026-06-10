from __future__ import annotations

import json
import threading
from collections import defaultdict
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from agenttrace.dashboard.server import push_event

_RUN_EVENTS: dict[str, list[dict[str, Any]]] = defaultdict(list)
_RUN_LOCK = threading.Lock()


SNAPSHOT_EVENT_MAP = {
    'snapshot.context': 'context_snapshot',
    'snapshot.plan': 'plan_snapshot',
    'snapshot.decision': 'decision_snapshot',
    'snapshot.resume': 'resume_snapshot',
    'snapshot.execution': 'execution_snapshot',
}


def _iso_now() -> str:
    return datetime.utcnow().isoformat() + 'Z'


def _parse_ts(value: Optional[str]) -> str:
    return value or _iso_now()


def _span_kind_from_event(event_type: str) -> Optional[str]:
    if event_type.startswith('llm.'):
        return 'llm'
    if event_type.startswith('tool.'):
        return 'tool'
    if event_type.startswith('skill.'):
        return 'skill'
    return None


def _duration_ms(start: Optional[str], end: Optional[str]) -> float:
    if not start or not end:
        return 0.0
    try:
        s = datetime.fromisoformat(start.replace('Z', '+00:00'))
        e = datetime.fromisoformat(end.replace('Z', '+00:00'))
        return round((e - s).total_seconds() * 1000, 1)
    except Exception:
        return 0.0


def _aggregate_span_events(protocol_events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    started = {}
    snapshots_by_span: dict[str, dict[str, Any]] = defaultdict(dict)
    signals_by_span: dict[str, dict[str, Any]] = defaultdict(dict)
    aggregated = []

    for event in protocol_events:
        et = event.get('event_type', '')
        span_id = event.get('span_id')
        payload = event.get('payload', {}) or {}
        ts = _parse_ts(event.get('timestamp'))
        kind = _span_kind_from_event(et)

        if et in SNAPSHOT_EVENT_MAP and span_id:
            snapshots_by_span[span_id][SNAPSHOT_EVENT_MAP[et]] = payload
            continue

        if et == 'retry.recorded' and span_id:
            signals_by_span[span_id].setdefault('retry_count', payload.get('retry_count', 0))
            signals_by_span[span_id].setdefault('retry_reasons', [])
            signals_by_span[span_id]['retry_reasons'].append(payload)
            signals_by_span[span_id].setdefault('backoff_ms', [])
            if payload.get('backoff_ms') is not None:
                signals_by_span[span_id]['backoff_ms'].append(payload.get('backoff_ms'))
            continue

        if et == 'fallback.recorded' and span_id:
            signals_by_span[span_id]['fallback'] = payload
            continue

        if et.endswith('.started') and kind and span_id:
            started[span_id] = event
            continue

        if (et.endswith('.finished') or et.endswith('.failed')) and kind and span_id:
            begin = started.get(span_id)
            begin_payload = (begin or {}).get('payload', {}) or {}
            merged = {
                'type': kind,
                'name': begin_payload.get('name') or payload.get('name') or et.rsplit('.', 1)[0],
                'status': payload.get('status') or ('failed' if et.endswith('.failed') else 'success'),
                'timestamp': (begin or event).get('timestamp') or ts,
                'started_at': (begin or event).get('timestamp') or ts,
                'ended_at': ts,
                'latency_ms': payload.get('latency_ms') or _duration_ms((begin or event).get('timestamp'), ts),
                'span_id': span_id,
                'parent_span_id': event.get('parent_span_id') or (begin or {}).get('parent_span_id'),
                'group_id': begin_payload.get('group_id') or payload.get('group_id'),
                'error': payload.get('error'),
            }
            if kind == 'tool':
                merged['input_params'] = begin_payload.get('input') or {}
                merged['output'] = payload.get('output')
            if kind == 'llm':
                merged['llm_prompt'] = begin_payload.get('messages')
                merged['llm_response'] = payload.get('response')
                merged['input_tokens'] = payload.get('input_tokens')
                merged['output_tokens'] = payload.get('output_tokens')
            if kind == 'skill':
                merged['input_params'] = begin_payload.get('input') or {}
                merged['output'] = payload.get('output')

            merged.update(snapshots_by_span.get(span_id, {}))
            if span_id in signals_by_span:
                execution_snapshot = merged.get('execution_snapshot') or {}
                signal = signals_by_span[span_id]
                execution_snapshot.update({
                    'retry_count': signal.get('retry_count', execution_snapshot.get('retry_count', 0)),
                    'retry_reasons': signal.get('retry_reasons', execution_snapshot.get('retry_reasons', [])),
                    'backoff_ms': signal.get('backoff_ms', execution_snapshot.get('backoff_ms', [])),
                })
                if signal.get('fallback'):
                    execution_snapshot['recovery_action'] = f"fallback_to_{signal['fallback'].get('to')}"
                    execution_snapshot['recovery_reason'] = signal['fallback'].get('reason')
                    merged['fallback_from'] = signal['fallback'].get('from')
                merged['execution_snapshot'] = execution_snapshot
            aggregated.append(merged)

    aggregated.sort(key=lambda x: x.get('timestamp') or '')
    return aggregated


def build_protocol_session_doc(protocol_events: List[Dict[str, Any]]) -> Dict[str, Any]:
    protocol_events = sorted(protocol_events, key=lambda x: x.get('timestamp') or '')
    run_started = next((e for e in protocol_events if e.get('event_type') == 'run.started'), None)
    run_finished = next((e for e in reversed(protocol_events) if e.get('event_type') in ('run.finished', 'run.failed')), None)
    run_id = (run_started or protocol_events[0]).get('run_id')
    run_payload = (run_started or {}).get('payload', {}) or {}
    run_agent = (run_started or {}).get('agent', {}) or {}

    ui_events = _aggregate_span_events(protocol_events)
    llm_review = next((e.get('payload') for e in protocol_events if e.get('event_type') == 'review.recorded'), None)

    metrics = {
        'total_latency_ms': _duration_ms((run_started or {}).get('timestamp'), (run_finished or {}).get('timestamp')),
        'total_steps': len([e for e in ui_events if e.get('type') in ('llm', 'skill')]),
        'total_tool_calls': len([e for e in ui_events if e.get('type') == 'tool']),
        'failed_tool_calls': len([e for e in ui_events if e.get('type') == 'tool' and e.get('status') == 'failed']),
        'tool_call_success_rate': round(
            (
                len([e for e in ui_events if e.get('type') == 'tool' and e.get('status') == 'success']) /
                max(1, len([e for e in ui_events if e.get('type') == 'tool']))
            ), 3
        ) if any(e.get('type') == 'tool' for e in ui_events) else 1.0,
        'total_tokens': sum((e.get('input_tokens') or 0) + (e.get('output_tokens') or 0) for e in ui_events if e.get('type') == 'llm'),
        'llm_review_summary': (llm_review or {}).get('summary'),
        'llm_review_findings': (llm_review or {}).get('findings', []),
        'llm_review_level': (llm_review or {}).get('review_level', 2),
        'composite_score': 0,
    }

    trace = {
        'trace_id': run_id,
        'run_id': run_id,
        'agent_name': run_agent.get('name') or 'agent',
        'task': run_payload.get('task') or '',
        'model': run_payload.get('model_hint') or run_agent.get('model') or 'unknown',
        'status': (run_finished or {}).get('payload', {}).get('status', 'completed'),
        'start_time': (run_started or {}).get('timestamp'),
        'end_time': (run_finished or {}).get('timestamp'),
        'root_ids': [],
        'summary': {
            'critical_path': {
                'path': [e.get('name') for e in ui_events[:4]],
                'total_latency_ms': metrics['total_latency_ms'],
            }
        },
        'spans': [],
    }

    doc = {
        'run_id': run_id,
        'boot_id': None,
        'agent_name': run_agent.get('name') or 'agent',
        'task': run_payload.get('task') or '',
        'framework': run_payload.get('framework') or 'protocol',
        'model': run_payload.get('model_hint') or run_agent.get('model') or 'unknown',
        'status': (run_finished or {}).get('payload', {}).get('status', 'completed'),
        'start_time': (run_started or {}).get('timestamp'),
        'end_time': (run_finished or {}).get('timestamp'),
        'input': run_payload.get('task') or '',
        'output': (run_finished or {}).get('payload', {}).get('output', ''),
        'protocol_events': protocol_events,
        'steps': [],
        'tool_calls': [],
        'events': ui_events,
        'llm_review': llm_review,
        'trace': trace,
        'metrics': metrics,
    }

    from agenttrace.diagnostics import build_diagnostics
    doc['diagnostics'] = build_diagnostics(doc)
    return doc


class _IngestHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip('/') or '/'
        length = int(self.headers.get('Content-Length', '0'))
        raw = self.rfile.read(length) if length else b'{}'
        try:
            body = json.loads(raw.decode('utf-8'))
        except Exception:
            self._json(400, {'error': 'invalid json'})
            return

        if path == '/api/v1/events':
            events = [body]
        elif path == '/api/v1/events/batch':
            events = body.get('events', [])
        else:
            self._json(404, {'error': 'not found'})
            return

        saved = []
        with _RUN_LOCK:
            for event in events:
                run_id = event.get('run_id')
                if not run_id:
                    continue
                _RUN_EVENTS[run_id].append(event)
                if event.get('event_type') in ('run.finished', 'run.failed'):
                    doc = build_protocol_session_doc(_RUN_EVENTS.pop(run_id))
                    _save_protocol_doc(doc)
                    push_event(doc)
                    saved.append(doc.get('run_id'))

        self._json(200, {'accepted': len(events), 'saved_runs': saved})

    def _json(self, code: int, payload: Dict[str, Any]):
        body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass


def _save_protocol_doc(doc: Dict[str, Any], store_dir: str = 'listen') -> None:
    from datetime import datetime
    run_dir = Path(store_dir) / datetime.now().strftime('%Y%m%d-%H%M')
    run_dir.mkdir(parents=True, exist_ok=True)
    detail_path = run_dir / f"{doc['run_id']}.json"
    detail_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding='utf-8')
    index_file = run_dir / 'sessions.jsonl'
    summary = {
        'run_id': doc['run_id'],
        'boot_id': doc.get('boot_id'),
        'task': (doc.get('task') or '')[:80],
        'model': doc.get('model'),
        'start_time': doc.get('start_time'),
        'total_latency_ms': doc.get('metrics', {}).get('total_latency_ms', 0),
        'total_tokens': doc.get('metrics', {}).get('total_tokens', 0),
        'composite_score': doc.get('metrics', {}).get('composite_score', 0),
        'status': doc.get('status'),
        'total_tool_calls': doc.get('metrics', {}).get('total_tool_calls', 0),
        'step_count': len(doc.get('steps', [])),
    }
    with index_file.open('a', encoding='utf-8') as f:
        f.write(json.dumps(summary, ensure_ascii=False) + '\n')


def start_ingest_server(port: int = 7760):
    server = ThreadingHTTPServer(('0.0.0.0', port), _IngestHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f'🛰️ AgentTrace ingest server: http://localhost:{port}/api/v1/events')
    return server
