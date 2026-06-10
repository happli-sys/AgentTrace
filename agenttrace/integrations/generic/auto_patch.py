"""
AgentTrace AutoPatch — pprof 风格，追踪整个模块，无需指定单个函数。
"""
from __future__ import annotations

import asyncio
import fnmatch
import functools
import importlib
import inspect
import time
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from agenttrace._context import get_collector, set_collector, reset_collector
from agenttrace._patch_registry import register as _reg, unregister as _unreg
from agenttrace.classify import CallType, classify, extract_llm_prompt, extract_llm_response
from agenttrace.collectors.runtime import RuntimeCollector
from agenttrace.metrics.engine import EvalResult, MetricsEngine
from agenttrace.state_builder import build_context_snapshot, build_memory_snapshot, build_plan_snapshot, build_decision_snapshot, build_resume_snapshot, build_execution_snapshot

engine  = MetricsEngine()
_MARKER = "__agentmeter_auto_patched__"


# ── wrapper ───────────────────────────────────────────────────────────────────

def _make_wrapper(fn: Callable, tool_name: str, module_path: str,
                  forced_type: Optional[CallType] = None,
                  llm_mods: Optional[Set[str]] = None,
                  skill_mods: Optional[Set[str]] = None,
                  llm_extractors: Optional[dict] = None) -> Callable:
    _llm_mods   = llm_mods
    _skill_mods = skill_mods
    _llm_extractors = llm_extractors or {}

    if asyncio.iscoroutinefunction(fn):
        @functools.wraps(fn)
        async def async_wrapper(*args, **kwargs):
            col = get_collector()
            started = datetime.utcnow()
            t0, error, status, result = time.perf_counter(), None, "success", None
            try:
                result = await fn(*args, **kwargs)
                return result
            except Exception as e:
                error, status = str(e), "failed"
                raise
            finally:
                elapsed = (time.perf_counter() - t0) * 1000
                ended = datetime.utcnow()
                if col is not None:
                    extractor = _llm_extractors.get(module_path, {})
                    prompt_payload = extractor.get("prompt", lambda a, k: extract_llm_prompt(a, k))(args, kwargs)
                    response_payload = extractor.get("response", lambda r: extract_llm_response(r))(result)
                    _record(col, tool_name, module_path, forced_type,
                            elapsed, status, error, result,
                            llm_modules=_llm_mods, skill_modules=_skill_mods,
                            started_at=started, ended_at=ended,
                            input_params={"args": repr(args)[:200], "kwargs": repr(kwargs)[:200]},
                            llm_prompt=prompt_payload,
                            llm_response=response_payload)
        setattr(async_wrapper, _MARKER, True)
        return async_wrapper

    @functools.wraps(fn)
    def sync_wrapper(*args, **kwargs):
        col = get_collector()
        started = datetime.utcnow()
        t0, error, status, result = time.perf_counter(), None, "success", None
        try:
            result = fn(*args, **kwargs)
            return result
        except Exception as e:
            error, status = str(e), "failed"
            raise
        finally:
            elapsed = (time.perf_counter() - t0) * 1000
            ended = datetime.utcnow()
            if col is not None:
                extractor = _llm_extractors.get(module_path, {})
                prompt_payload = extractor.get("prompt", lambda a, k: extract_llm_prompt(a, k))(args, kwargs)
                response_payload = extractor.get("response", lambda r: extract_llm_response(r))(result)
                _record(col, tool_name, module_path, forced_type,
                        elapsed, status, error, result,
                        llm_modules=_llm_mods, skill_modules=_skill_mods,
                        started_at=started, ended_at=ended,
                        input_params={"args": repr(args)[:200], "kwargs": repr(kwargs)[:200]},
                        llm_prompt=prompt_payload,
                        llm_response=response_payload)
    setattr(sync_wrapper, _MARKER, True)
    return sync_wrapper


def _record(col: RuntimeCollector, tool_name: str, module_path: str,
            forced_type: Optional[CallType], elapsed: float,
            status: str, error: Optional[str], result: Any,
            llm_modules: Optional[Set[str]] = None,
            skill_modules: Optional[Set[str]] = None,
            started_at: Optional[datetime] = None,
            ended_at: Optional[datetime] = None,
            input_params: Optional[dict] = None,
            llm_prompt: Any = None,
            llm_response: Any = None) -> None:
    call_type, token_info = classify(
        module_path, result, force=forced_type,
        llm_modules=llm_modules, skill_modules=skill_modules,
    )
    if call_type == CallType.LLM:
        in_tok  = (token_info or {}).get("input_tokens", 0)
        out_tok = (token_info or {}).get("output_tokens", 0)
        model   = (token_info or {}).get("model", "unknown")
        if col.run.model == "unknown" and model != "unknown":
            col.run.model = model
        step = col.record_step(
            description=f"llm:{tool_name}",
            latency_ms=elapsed,
            input_tokens=in_tok,
            output_tokens=out_tok,
            started_at=started_at,
            ended_at=ended_at,
        )
        # 动态挂载 LLM 详情与状态快照，供存储层/前端读取
        step.llm_prompt = llm_prompt
        step.llm_response = llm_response
        step.context_snapshot = build_context_snapshot(
            llm_prompt=llm_prompt,
            tool_results=[tc.tool_name for tc in col.run.all_tool_calls[-5:]],
            token_count_before_send=in_tok,
        )
        # 先构造一份当前 run 的简化事件流，供 derived plan/decision/memory/resume 推断
        current_events = []
        for s in col.run.steps:
            desc = s.description or ''
            if desc.startswith('llm:'):
                current_events.append({
                    'type': 'llm', 'name': desc.replace('llm:', '', 1),
                    'started_at': s.started_at.isoformat() if s.started_at else None,
                    'ended_at': s.ended_at.isoformat() if s.ended_at else None,
                    'latency_ms': s.latency_ms,
                })
            for tc in s.tool_calls:
                current_events.append({
                    'type': 'tool', 'name': tc.tool_name,
                    'group_id': tc.group_id,
                    'status': tc.status.value,
                    'input_params': tc.input_params,
                    'started_at': tc.started_at.isoformat() if tc.started_at else None,
                    'ended_at': tc.ended_at.isoformat() if tc.ended_at else None,
                    'latency_ms': tc.latency_ms,
                })
        step.memory_snapshot = build_memory_snapshot(
            task=col.run.task,
            events=current_events,
        )
        step.plan_snapshot = build_plan_snapshot(
            action=tool_name,
            completed_steps=[tc.tool_name for tc in col.run.all_tool_calls],
            task=col.run.task,
            events=current_events,
        )
        step.decision_snapshot = build_decision_snapshot(
            action=tool_name,
            rationale="Auto-detected LLM invocation",
            task=col.run.task,
            events=current_events,
        )
        step.resume_snapshot = build_resume_snapshot(
            task=col.run.task,
            events=current_events,
        )
        step.execution_snapshot = build_execution_snapshot()
    elif call_type == CallType.SKILL:
        col.record_step(
            description=f"skill:{tool_name}",
            latency_ms=elapsed,
            started_at=started_at,
            ended_at=ended_at,
        )
    else:
        col.record_tool_call(tool_name, status=status,
                             latency_ms=elapsed, error=error,
                             input_params=input_params or {},
                             started_at=started_at, ended_at=ended_at)


# ── 模块遍历 ──────────────────────────────────────────────────────────────────

def _should_include(name: str, exclude: Set[str],
                    include_pattern: Optional[str]) -> bool:
    if name.startswith("_"):
        return False
    if name in exclude:
        return False
    if include_pattern:
        return fnmatch.fnmatch(name, include_pattern)
    return True


def _patch_module(module: Any, module_path: str, exclude: Set[str],
                  include_pattern: Optional[str],
                  llm_modules: Set[str],
                  skill_modules: Set[str],
                  llm_extractors: Optional[dict]) -> List[Tuple[Any, str, Callable]]:
    patches: List[Tuple[Any, str, Callable]] = []
    short  = module_path.rsplit(".", 1)[-1]
    if module_path in skill_modules:
        forced = CallType.SKILL
    elif module_path in llm_modules:
        forced = CallType.LLM
    else:
        forced = None

    for name, obj in list(inspect.getmembers(module)):
        if not _should_include(name, exclude, include_pattern):
            continue
        if inspect.ismodule(obj):
            continue

        if inspect.isclass(obj):
            for mname, mobj in list(inspect.getmembers(obj)):
                if not _should_include(mname, exclude, include_pattern):
                    continue
                if not callable(mobj) or mname in vars(object):
                    continue
                wrapper = _make_wrapper(mobj, f"{short}.{name}.{mname}",
                                        module_path, forced,
                                        llm_mods=llm_modules,
                                        skill_mods=skill_modules,
                                        llm_extractors=llm_extractors)
                try:
                    _reg(obj, mname, mobj, wrapper)
                    patches.append((obj, mname))   # 引用计数已加，必须记录以便 unregister
                except (AttributeError, TypeError):
                    pass

        elif callable(obj):
            wrapper = _make_wrapper(obj, f"{short}.{name}", module_path, forced,
                                    llm_mods=llm_modules,
                                    skill_mods=skill_modules,
                                    llm_extractors=llm_extractors)
            _reg(module, name, obj, wrapper)
            patches.append((module, name))   # 引用计数已加，必须记录以便 unregister

    return patches


# ── AutoPatcher ───────────────────────────────────────────────────────────────

class AutoPatcher:
    def __init__(
        self,
        module_paths:    List[str],
        llm_modules:     Optional[List[str]] = None,
        skill_modules:   Optional[List[str]] = None,
        llm_extractors:  Optional[dict]      = None,
        exclude:         Optional[List[str]] = None,
        include_pattern: Optional[str]       = None,
        review_level:     int                = 2,
    ):
        self._module_paths    = module_paths
        self._llm_modules     = set(llm_modules or [])
        self._skill_modules   = set(skill_modules or [])
        self._llm_extractors = llm_extractors or {}
        self._exclude         = set(exclude or [])
        self._include_pattern = include_pattern
        self._patches: List[Tuple[Any, str, Callable]] = []
        self._applied = False

    def apply(self) -> List[str]:
        if self._applied:
            return []
        patched_names: List[str] = []
        for path in self._module_paths:
            try:
                module = importlib.import_module(path)
            except ImportError as e:
                raise ImportError(f"[AgentTrace] Cannot import '{path}': {e}") from e
            new_patches = _patch_module(
                module, path, self._exclude, self._include_pattern,
                self._llm_modules, self._skill_modules, self._llm_extractors,
            )
            self._patches.extend(new_patches)
            patched_names.extend(f"{path}.{attr}" for _, attr in new_patches)
        self._applied = True
        return patched_names

    def revert(self) -> None:
        for owner, attr in self._patches:
            _unreg(owner, attr)
        self._patches.clear()
        self._applied = False

    def __enter__(self) -> "AutoPatcher":
        self.apply()
        return self

    def __exit__(self, *_) -> None:
        self.revert()


# ── AutoPatchSession ──────────────────────────────────────────────────────────

class AutoPatchSession:
    """
    零侵入评测会话。追踪整个模块，自动区分 LLM/工具调用。

    with AutoPatchSession(
        modules=["myagent.tools", "myagent.llm"],
        task="...",
    ) as sess:
        output = my_agent.run(task)
        sess.set_output(output)

    print(sess.result.summary())
    """

    def __init__(
        self,
        modules:         List[str],
        task:            str                      = "",
        agent_name:      str                      = "agent",
        framework:       str                      = "custom",
        model:           str                      = "unknown",
        expected_output: Optional[str]            = None,
        tags:            Optional[Dict[str, str]] = None,
        llm_modules:     Optional[List[str]]      = None,
        skill_modules:   Optional[List[str]]      = None,
        llm_extractors:  Optional[dict]           = None,
        exclude:         Optional[List[str]]      = None,
        include_pattern: Optional[str]            = None,
    ):
        self._patcher = AutoPatcher(
            modules, llm_modules=llm_modules,
            skill_modules=skill_modules,
            llm_extractors=llm_extractors,
            exclude=exclude, include_pattern=include_pattern,
        )
        self._col = RuntimeCollector(
            task=task, agent_name=agent_name, framework=framework,
            model=model, expected_output=expected_output, tags=tags or {},
        )
        self.result: Optional[EvalResult] = None
        self.patched_functions: List[str] = []
        self._token = None

    def __enter__(self) -> "AutoPatchSession":
        self.patched_functions = self._patcher.apply()
        self._col.__enter__()
        self._token = set_collector(self._col)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        reset_collector(self._token)
        self._col.__exit__(exc_type, exc_val, exc_tb)
        self._patcher.revert()
        self.result = engine.evaluate(self._col.run)
        return False

    def set_output(self, output: str) -> None:
        self._col.set_output(output)


def auto_patch(*module_paths: str, **kwargs) -> None:
    pass  # 保持向后兼容
