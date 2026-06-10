"""
规则推断版 Plan / Decision 生成器。
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

from agenttrace.state import PlanSnapshot, DecisionSnapshot, MemorySnapshot, ResumeSnapshot

KNOWN_CITIES = ["北京", "上海", "广州", "成都", "深圳", "杭州", "西安"]


def extract_task_entities(task: str) -> Dict[str, Any]:
    cities = [c for c in KNOWN_CITIES if c in task]
    expr_match = re.search(r"[\d\s\+\-\*\/\(\)\.]+", task)
    expr = expr_match.group(0).strip() if expr_match else None
    intents = []
    if any(k in task for k in ["天气", "气温", "温度", "播报"]):
        intents.append("weather")
    if any(k in task for k in ["计算", "算", "+", "-", "*", "/"]):
        intents.append("calculate")
    if any(k in task for k in ["研究", "分析", "了解", "介绍"]):
        intents.append("research")
    if any(k in task for k in ["搜索", "查找", "找"]):
        intents.append("search")
    return {"cities": cities, "expression": expr, "intents": intents}


def derive_plan_from_run(task: str, events: List[dict]) -> PlanSnapshot:
    ent = extract_task_entities(task)
    completed_steps: List[str] = []
    pending_steps: List[str] = []
    plan_tree: List[Dict[str, Any]] = []

    llms = [ev for ev in events if ev.get("type") == "llm"]
    tools = [ev for ev in events if ev.get("type") == "tool"]
    skills = [ev for ev in events if ev.get("type") == "skill"]

    # 高层阶段判断
    if llms and tools:
        phase = "summarize"
    elif llms and not tools:
        phase = "reasoning"
    elif tools and not llms:
        phase = "execution_only"
    else:
        phase = "unknown"

    # 1) skills 作为高层节点
    for ev in skills:
        name = _event_label(ev)
        completed_steps.append(name)
        plan_tree.append({"step": name, "kind": "skill", "status": "completed"})

    # 2) 并行工具组作为高层节点
    grouped = {}
    for ev in tools:
        gid = ev.get("group_id")
        if gid:
            grouped.setdefault(gid, []).append(ev)

    grouped_event_keys = set()
    for gid, items in grouped.items():
        children = []
        for ev in items:
            name = _event_label(ev)
            children.append({"step": name, "status": "completed"})
            completed_steps.append(name)
            grouped_event_keys.add((ev.get("name"), ev.get("started_at"), ev.get("group_id")))
        plan_tree.append({
            "step": gid,
            "kind": "parallel_group",
            "status": "completed",
            "children": children,
        })

    # 3) 非并行工具作为普通节点
    for ev in tools:
        key = (ev.get("name"), ev.get("started_at"), ev.get("group_id"))
        if key in grouped_event_keys:
            continue
        name = _event_label(ev)
        completed_steps.append(name)
        plan_tree.append({"step": name, "kind": "tool", "status": "completed"})

    # 4) 第一个/最后一个 LLM 的业务语义推断
    if llms:
        if len(llms) >= 1:
            plan_tree.insert(0, {"step": "route_or_plan", "kind": "llm", "status": "completed"})
            completed_steps.insert(0, "route_or_plan")
        if len(llms) >= 2:
            plan_tree.append({"step": "finalize_response", "kind": "llm", "status": "completed"})
            completed_steps.append("finalize_response")

    # 5) 从 task 推断可能遗漏的 pending
    if "weather" in ent["intents"]:
        if len(ent["cities"]) > 1:
            expected = {f"tools.get_weather({c})" for c in ent["cities"]}
            seen = {s for s in completed_steps if s.startswith("tools.get_weather(")}
            pending_steps.extend(sorted(expected - seen))
        elif ent["cities"]:
            expected = f"tools.get_weather({ent['cities'][0]})"
            if expected not in completed_steps:
                pending_steps.append(expected)
    if ent["expression"]:
        expected = f"tools.calculate({ent['expression']})"
        if expected not in completed_steps:
            pending_steps.append(expected)
    if "research" in ent["intents"] and not any('research_skill' in s for s in completed_steps):
        pending_steps.append('skills.research_skill')
    if llms and 'finalize_response' not in completed_steps:
        pending_steps.append('finalize_response')

    plan = PlanSnapshot(
        root_goal=task,
        plan_version="derived-v2",
        phase=phase,
        completed_steps=completed_steps,
        pending_steps=pending_steps,
        replanned_count=0,
        plan_tree=plan_tree,
    )
    plan.source = 'derived'
    return plan


def derive_decision_from_run(task: str, events: List[dict]) -> DecisionSnapshot:
    ent = extract_task_entities(task)
    action = "unknown"
    rationale = "Derived from observed execution trace."
    confidence = 0.55
    candidates: List[str] = []

    has_parallel_weather = any(ev.get("group_id") == "weather_queries" for ev in events)
    has_calc = any(ev.get("name") == "tools.calculate" for ev in events)
    has_research = any("research_skill" in (ev.get("name") or "") for ev in events)
    has_weather = any((ev.get("name") or "").startswith("tools.get_weather") for ev in events)
    llm_count = sum(1 for ev in events if ev.get("type") == "llm")

    if len(ent["cities"]) > 1 and has_parallel_weather and has_calc:
        action = "parallel_weather_query_then_calculate"
        rationale = "Detected two or more city entities, observed grouped weather queries, then a calculator tool before final summarization."
        confidence = 0.87
        candidates = [
            "serial_weather_query_then_calculate",
            "parallel_weather_query_then_calculate",
            "weather_only",
            "calculate_only",
        ]
    elif len(ent["cities"]) > 1 and has_parallel_weather:
        action = "parallel_weather_query"
        rationale = "Detected multiple city entities and observed grouped weather queries under the same parallel group."
        confidence = 0.82
        candidates = ["serial_weather_query", "parallel_weather_query"]
    elif has_weather and has_calc:
        action = "weather_then_calculate"
        rationale = "Observed weather tool execution and calculator execution for a mixed-intent task."
        confidence = 0.78
        candidates = ["weather_then_calculate", "calculate_then_weather"]
    elif has_calc:
        action = "calculator_tool_selected"
        rationale = "Detected arithmetic expression and observed calculator tool execution."
        confidence = 0.90
        candidates = ["calculator_tool_selected", "reason_without_tool"]
    elif has_research:
        action = "research_workflow_selected"
        rationale = "Task contains research intent and execution included research skill or search+synthesis pattern."
        confidence = 0.78
        candidates = ["research_workflow_selected", "simple_search_then_summarize"]
    elif llm_count >= 2:
        action = "llm_route_then_summarize"
        rationale = "Observed at least two LLM calls suggesting initial routing/planning followed by final synthesis."
        confidence = 0.68
        candidates = ["llm_route_then_summarize", "single_shot_llm"]

    d = DecisionSnapshot(
        action=action,
        rationale=rationale,
        confidence=confidence,
        candidates=candidates,
    )
    d.source = 'derived'
    return d


def _event_label(ev: dict) -> str:
    name = ev.get("name") or ev.get("description") or "event"
    if ev.get("type") == "tool":
        args = (ev.get("input_params") or {}).get("args") or ""
        city = _extract_single_arg(args)
        if city:
            return f"{name}({city})"
        return name
    return name


def _extract_single_arg(arg_repr: str) -> str | None:
    m = re.match(r"\('(.+?)',?\)", str(arg_repr))
    return m.group(1) if m else None



def derive_memory_from_run(task: str, events: List[dict]) -> MemorySnapshot:
    """
    第一层默认不依赖外部 memory 系统，因此 Memory 的 derived 版本比较保守：
    - 从 ContextSnapshot 里 injected memory / tool results 粗略判断“短期记忆命中”
    - 不伪造 LTM 命中
    - writes/evictions 只有在事件里出现明确 memory 行为时才记录
    """
    stm_hits: List[Any] = []
    ltm_hits: List[Any] = []
    writes: List[Any] = []
    evictions: List[Any] = []

    for ev in events:
        # 如果后续某些 adapter/事件带 memory_snapshot，优先吸收
        mem = ev.get('memory_snapshot') if isinstance(ev, dict) else None
        if mem:
            stm_hits.extend(mem.get('stm_hits', []) or [])
            ltm_hits.extend(mem.get('ltm_hits', []) or [])
            writes.extend(mem.get('writes', []) or [])
            evictions.extend(mem.get('evictions', []) or [])

        # 约定：工具名含 memory 的行为作为 memory 写/查提示
        name = (ev.get('name') or '') if isinstance(ev, dict) else ''
        if 'memory' in name.lower() and ev.get('type') == 'tool':
            if any(k in name.lower() for k in ['write', 'save', 'store', 'upsert']):
                writes.append({"tool": name})
            elif any(k in name.lower() for k in ['evict', 'delete', 'remove']):
                evictions.append({"tool": name})
            else:
                stm_hits.append({"tool": name})

    m = MemorySnapshot(
        stm_hits=stm_hits,
        ltm_hits=ltm_hits,
        writes=writes,
        evictions=evictions,
    )
    m.source = 'derived'
    return m



def derive_resume_from_run(task: str, events: List[dict]) -> ResumeSnapshot:
    """
    derived resume：默认只做保守判断。
    - 若事件里显式出现 checkpoint/resume 语义，则记录
    - 否则认为是非中断、非恢复运行
    """
    interrupted = False
    resumed = False
    checkpoint_id = None
    resumed_from = None
    recovered_context = []
    recovered_plan = None
    recovered_memory = []

    for ev in events:
        name = (ev.get('name') or '') if isinstance(ev, dict) else ''
        low = name.lower()
        if 'resume' in low or 'checkpoint' in low or 'restore' in low:
            resumed = True
            interrupted = True
            checkpoint_id = checkpoint_id or ev.get('checkpoint_id') or name
            resumed_from = resumed_from or ev.get('resumed_from') or name

        rs = ev.get('resume_snapshot') if isinstance(ev, dict) else None
        if rs:
            interrupted = interrupted or rs.get('interrupted', False)
            resumed = resumed or rs.get('resumed', False)
            checkpoint_id = checkpoint_id or rs.get('checkpoint_id')
            resumed_from = resumed_from or rs.get('resumed_from')
            recovered_context = recovered_context or rs.get('recovered_context', [])
            recovered_plan = recovered_plan or rs.get('recovered_plan')
            recovered_memory = recovered_memory or rs.get('recovered_memory', [])

    r = ResumeSnapshot(
        interrupted=interrupted,
        resumed=resumed,
        checkpoint_id=checkpoint_id,
        resumed_from=resumed_from,
        recovered_context=recovered_context,
        recovered_plan=recovered_plan,
        recovered_memory=recovered_memory,
    )
    r.source = 'derived'
    return r
