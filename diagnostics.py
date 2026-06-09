from __future__ import annotations

from typing import Any, Dict, List


def build_diagnostics(doc: Dict[str, Any]) -> Dict[str, Any]:
    events = doc.get('events', []) or []
    metrics = doc.get('metrics', {}) or {}
    trace = doc.get('trace', {}) or {}
    review = doc.get('llm_review') or {}

    failed_tools = [e for e in events if e.get('type') == 'tool' and e.get('status') == 'failed']
    tool_events = [e for e in events if e.get('type') == 'tool']
    llm_events = [e for e in events if e.get('type') == 'llm']
    skill_events = [e for e in events if e.get('type') == 'skill']

    redundant_tools = _find_redundant_tool_patterns(tool_events)
    recovery_chains = _find_recovery_chains(tool_events)
    suspicious_decisions = _find_suspicious_decisions(llm_events)
    critical_path = (trace.get('summary') or {}).get('critical_path') or {"path": [], "total_latency_ms": 0}

    findings = review.get('findings') or metrics.get('llm_review_findings') or []
    severity_counts = {
        'high': sum(1 for item in findings if item.get('severity') == 'high'),
        'medium': sum(1 for item in findings if item.get('severity') == 'medium'),
        'low': sum(1 for item in findings if item.get('severity') == 'low'),
        'optimization': sum(1 for item in findings if item.get('severity') == 'optimization'),
        'note': sum(1 for item in findings if item.get('severity') == 'note'),
    }

    return {
        'overview': {
            'failed_tool_calls': len(failed_tools),
            'recovery_count': len(recovery_chains),
            'redundant_cluster_count': len(redundant_tools),
            'suspicious_decision_count': len(suspicious_decisions),
            'llm_call_count': len(llm_events),
            'tool_call_count': len(tool_events),
            'skill_call_count': len(skill_events),
            'severity_counts': severity_counts,
        },
        'critical_path': critical_path,
        'failed_tools': [
            {
                'name': e.get('name'),
                'error': e.get('error'),
                'latency_ms': e.get('latency_ms'),
            }
            for e in failed_tools
        ],
        'recovery_chains': recovery_chains,
        'redundant_tools': redundant_tools,
        'suspicious_decisions': suspicious_decisions,
        'review_findings': findings,
    }


def _find_redundant_tool_patterns(tool_events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    clusters = []
    i = 0
    while i < len(tool_events):
        current = tool_events[i]
        j = i + 1
        while j < len(tool_events) and tool_events[j].get('name') == current.get('name'):
            j += 1
        if j - i > 1:
            items = tool_events[i:j]
            clusters.append({
                'tool': current.get('name'),
                'count': len(items),
                'pattern': 'sequential_same_tool',
                'statuses': [item.get('status') for item in items],
            })
        i = j

    by_group = {}
    for event in tool_events:
        gid = event.get('group_id')
        if gid:
            by_group.setdefault(gid, []).append(event)
    for gid, items in by_group.items():
        same_name = {}
        for item in items:
            same_name.setdefault(item.get('name'), []).append(item)
        for name, grouped in same_name.items():
            if len(grouped) > 1:
                clusters.append({
                    'tool': name,
                    'count': len(grouped),
                    'pattern': 'parallel_same_tool',
                    'group_id': gid,
                    'statuses': [item.get('status') for item in grouped],
                })
    return clusters


def _find_recovery_chains(tool_events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    chains = []
    for idx, event in enumerate(tool_events):
        if event.get('status') != 'failed':
            continue
        next_success = None
        for later in tool_events[idx + 1: idx + 4]:
            if later.get('status') == 'success':
                next_success = later
                break
        if next_success:
            chains.append({
                'failed_tool': event.get('name'),
                'failed_error': event.get('error'),
                'recovered_by': next_success.get('name'),
                'recovered_latency_ms': next_success.get('latency_ms'),
            })
    return chains


def _find_suspicious_decisions(llm_events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for event in llm_events:
        decision = event.get('decision_snapshot') or {}
        execution = event.get('execution_snapshot') or {}
        if decision.get('candidates') and decision.get('action') and execution.get('tool_candidates'):
            out.append({
                'action': decision.get('action'),
                'confidence': decision.get('confidence'),
                'candidate_count': len(decision.get('candidates') or []),
                'tool_candidate_count': len(execution.get('tool_candidates') or []),
                'reason': decision.get('rationale') or execution.get('tool_choice_reason'),
            })
    return out
