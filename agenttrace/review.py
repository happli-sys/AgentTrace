from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

REVIEW_LEVEL_HINTS = {
    1: "level=1 开放模式：只有明确错误、明显重复、明显失败恢复缺失、明显违背用户意图时才报问题。对为了完成任务而做的少量辅助读取/辅助命令，通常视为合理，不要轻易报多余调用。",
    2: "level=2 平衡模式：只报告明确问题和明显优化项。不要把简短解释性文本、简单任务中的常规 LLM 延迟、少量合理辅助读取、轻微风格问题当成 finding。只有在额外调用带来明显成本、延迟、风险，或明显偏离用户意图时，才报告 optimization。",
    3: "level=3 保守模式：严格审查范围漂移、额外工具/技能调用、额外上下文读取、额外 shell 操作；可以报告轻量解释性文本、简单任务中的延迟偏高、辅助调用必要性不足等 softer 的 optimization / note。",
}

from agenttrace.metrics.engine import EvalResult
from agenttrace.models import AgentRun


@dataclass
class ReviewResult:
    summary: str
    findings: list[dict[str, Any]]
    raw: dict[str, Any]
    model: str = ""


def _build_review_payload(run: AgentRun, result: EvalResult) -> dict[str, Any]:
    events = []
    for step in run.steps:
        desc = step.description or ""
        if desc.startswith("llm:"):
            events.append({
                "type": "llm",
                "name": desc.replace("llm:", "", 1),
                "latency_ms": round(step.latency_ms, 2),
                "input_tokens": step.input_tokens,
                "output_tokens": step.output_tokens,
                "prompt": getattr(step, "llm_prompt", None),
                "response": getattr(step, "llm_response", None),
            })
        elif desc.startswith("skill:"):
            events.append({
                "type": "skill",
                "name": desc.replace("skill:", "", 1),
                "latency_ms": round(step.latency_ms, 2),
            })
        for tc in step.tool_calls:
            events.append({
                "type": "tool",
                "name": tc.tool_name,
                "status": tc.status.value,
                "latency_ms": round(tc.latency_ms, 2),
                "input_params": tc.input_params,
                "error": tc.error,
                "output": tc.output,
                "fallback_from": tc.fallback_from,
                "retry_count": tc.retry_count,
            })
    return {
        "task": run.task,
        "output": run.actual_output or "",
        "metrics": {
            "total_latency_ms": round(result.total_latency_ms, 1),
            "total_steps": result.total_steps,
            "redundant_steps": result.redundant_steps,
            "total_tool_calls": result.total_tool_calls,
            "failed_tool_calls": result.failed_tool_calls,
            "tool_call_success_rate": round(result.tool_call_success_rate, 3),
            "composite_score": round(result.composite_score, 3),
        },
        "events": events,
    }


def review_run(
    run: AgentRun,
    result: EvalResult,
    llm_chat: Optional[Callable[..., Any]] = None,
    review_level: int = 2,
) -> Optional[ReviewResult]:
    if llm_chat is None:
        return None

    review_level = review_level if review_level in (1, 2, 3) else 2
    payload = _build_review_payload(run, result)
    messages = [
        {
            "role": "system",
            "content": (
                "你是 Agent 执行流评审器。请只根据给定运行记录，分析是否存在："
                "多余工具调用、错误工具调用、失败工具调用、可疑 fallback、"
                "多余 skill 调用、错误 skill 调用、明显漏掉的调用步骤。"
                "请按接入方设置的 review level 调整严格度。"
                "特别注意：level=2 默认应偏稳健，避免误报风格型、轻量型、边缘型问题；"
                "像简短前置解释、正常范围内的简单任务延迟、为完成任务而做的少量辅助读取，通常不应在 level=2 里输出 finding。"
                "对于“LLM 虚构执行结果”这类判断，必须非常谨慎："
                "只有当首次 LLM 在真实工具执行前，明确断言了具体执行结果，且这些结果并非来自用户输入/已有上下文，并且与后续真实工具结果明显冲突时，才能报告。"
                "如果只是表达将要调用工具、输出工具调用协议文本、规划步骤、或文本内容后来被真实工具结果验证，则不要报告为虚构执行结果。"
                "输出必须是 JSON，对象格式为："
                "{\"summary\": string, \"findings\": [{\"severity\": \"high|medium|low|optimization|note\", "
                "\"type\": string, \"target\": string, \"reason\": string, \"suggestion\": string}]}。"
                "不要输出 markdown，不要输出代码块。"
            ),
        },
        {
            "role": "user",
            "content": json.dumps({"review_level": review_level, "review_guidance": REVIEW_LEVEL_HINTS[review_level], "payload": payload}, ensure_ascii=False),
        },
    ]

    response = llm_chat(messages, temperature=0.1)
    content = getattr(response, "content", "") or ""
    parsed = _parse_review_json(content)
    if not parsed:
        parsed = {
            "summary": content.strip() or "LLM review returned empty content.",
            "findings": [],
        }
    return ReviewResult(
        summary=str(parsed.get("summary", "")).strip(),
        findings=list(parsed.get("findings", []) or []),
        raw=parsed,
        model=getattr(response, "model", "") or "",
    )


def _parse_review_json(content: str) -> Optional[Dict[str, Any]]:
    text = content.strip()
    if not text:
        return None
    candidates = [text]
    if "```json" in text:
        candidates.append(text.split("```json", 1)[1].split("```", 1)[0].strip())
    elif "```" in text:
        candidates.append(text.split("```", 1)[1].split("```", 1)[0].strip())
    for candidate in candidates:
        try:
            obj = json.loads(candidate)
            if isinstance(obj, dict):
                return obj
        except Exception:
            continue
    return None
