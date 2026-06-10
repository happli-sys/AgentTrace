"""
AgentTrace 调用类型分类器与 LLM 详情提取器。
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, FrozenSet, Optional, Set, Tuple


class CallType(str, Enum):
    LLM   = "llm"
    TOOL  = "tool"
    SKILL = "skill"


KNOWN_LLM_MODULES: FrozenSet[str] = frozenset({
    "openai", "anthropic", "litellm", "ollama", "cohere", "mistralai",
    "groq", "together", "ai21", "huggingface_hub", "google.generativeai",
    "google.genai", "vertexai", "boto3", "botocore",
    "langchain_openai", "langchain_anthropic", "langchain_groq",
    "langchain_mistralai", "langchain_community.llms",
    "langchain_community.chat_models", "langchain_core.language_models",
})


def is_known_llm_module(module_path: str) -> bool:
    return any(module_path == m or module_path.startswith(m + ".") for m in KNOWN_LLM_MODULES)


# ── token usage ──────────────────────────────────────────────────────────────

def extract_token_usage(result: Any) -> Optional[Dict[str, Any]]:
    if result is None:
        return None
    usage = getattr(result, "usage", None)
    if usage is not None:
        prompt = getattr(usage, "prompt_tokens", None)
        completion = getattr(usage, "completion_tokens", None)
        if prompt is not None and completion is not None:
            info: Dict[str, Any] = {
                "input_tokens": int(prompt),
                "output_tokens": int(completion),
                "model": getattr(result, "model", "unknown"),
            }
            details = getattr(usage, "prompt_tokens_details", None)
            if details:
                cached = getattr(details, "cached_tokens", 0)
                if cached:
                    info["cached_tokens"] = int(cached)
            return info
        in_tok = getattr(usage, "input_tokens", None)
        out_tok = getattr(usage, "output_tokens", None)
        if in_tok is not None and out_tok is not None:
            return {
                "input_tokens": int(in_tok),
                "output_tokens": int(out_tok),
                "model": getattr(result, "model", "unknown"),
            }
    in_tok = getattr(result, "input_tokens", None)
    out_tok = getattr(result, "output_tokens", None)
    if in_tok is not None and out_tok is not None:
        return {
            "input_tokens": int(in_tok),
            "output_tokens": int(out_tok),
            "model": getattr(result, "model", "unknown"),
        }
    if isinstance(result, dict) and "usage" in result:
        u = result["usage"]
        if isinstance(u, dict):
            in_t = u.get("prompt_tokens") or u.get("input_tokens")
            out_t = u.get("completion_tokens") or u.get("output_tokens")
            if in_t is not None and out_t is not None:
                return {
                    "input_tokens": int(in_t),
                    "output_tokens": int(out_t),
                    "model": result.get("model", "unknown"),
                }
    return None


# ── prompt / response 提取（通用自动识别）─────────────────────────────────────

def extract_llm_prompt(args: tuple, kwargs: dict) -> Optional[Any]:
    """
    尽量从调用参数中提取 prompt/messages。
    返回原始对象（str/list/dict），由前端决定展示方式。
    """
    # 常见关键字优先
    for key in ("messages", "prompt", "input", "query", "text"):
        if key in kwargs:
            return kwargs[key]

    # OpenAI 风格：第一个位置参数就是 messages
    if args:
        first = args[0]
        if isinstance(first, list):
            return first
        if isinstance(first, (str, dict)):
            return first
    return None


def extract_llm_response(result: Any) -> Optional[Any]:
    """
    尽量从返回值中提取模型输出文本/结构。
    返回原始对象，由前端决定展示方式。
    """
    if result is None:
        return None

    # OpenAI 风格：choices[0].message.content
    choices = getattr(result, "choices", None)
    if choices and isinstance(choices, list) and len(choices) > 0:
        c0 = choices[0]
        msg = getattr(c0, "message", None)
        if msg is not None:
            content = getattr(msg, "content", None)
            if content is not None:
                return content
        # dict-like fallback
        if isinstance(c0, dict):
            msg = c0.get("message")
            if isinstance(msg, dict) and "content" in msg:
                return msg["content"]

    # 常见字段
    for key in ("content", "output_text", "text", "answer", "response"):
        if hasattr(result, key):
            return getattr(result, key)
        if isinstance(result, dict) and key in result:
            return result[key]

    return None


def classify(
    module_path: str,
    result: Any = None,
    *,
    llm_modules: Optional[Set[str]] = None,
    skill_modules: Optional[Set[str]] = None,
    force: Optional[CallType] = None,
) -> Tuple[CallType, Optional[Dict[str, Any]]]:
    if force is not None:
        token_info = extract_token_usage(result) if force == CallType.LLM else None
        return force, token_info
    if skill_modules and _module_in_set(module_path, skill_modules):
        return CallType.SKILL, None
    if llm_modules and _module_in_set(module_path, llm_modules):
        return CallType.LLM, extract_token_usage(result)
    if is_known_llm_module(module_path):
        return CallType.LLM, extract_token_usage(result)
    token_info = extract_token_usage(result)
    if token_info is not None:
        return CallType.LLM, token_info
    return CallType.TOOL, None


def _module_in_set(module_path: str, module_set: Set[str]) -> bool:
    return any(module_path == m or module_path.startswith(m + ".") for m in module_set)
