import asyncio
from typing import Callable, Optional
"""
AgentTrace — Objective performance evaluation for AI Agents.

Quick start (framework-agnostic):
    from agenttrace import RuntimeCollector, evaluate

    with RuntimeCollector(task="my task", agent_name="my_agent") as col:
        # ... run your agent here ...
        col.record_step("llm_call", input_tokens=100, output_tokens=50, latency_ms=320)
        col.record_tool_call("web_search", status="success", latency_ms=450)
        col.set_output("the answer")

    result = evaluate(col.run)
    print(result.summary())
"""

from agenttrace.collectors.runtime import RuntimeCollector
from agenttrace.metrics.engine import EvalResult, MetricsEngine
from agenttrace.metrics.regression import RegressionTracker, RegressionReport
from agenttrace.metrics.comparison import compare
from agenttrace.models import AgentRun, ToolCallStatus, RunStatus
from agenttrace.reporters.json_reporter import JSONReporter
from agenttrace.reporters.csv_reporter import CSVReporter

__version__ = "0.1.0"
__all__ = [
    "RuntimeCollector",
    "EvalResult",
    "MetricsEngine",
    "RegressionTracker",
    "RegressionReport",
    "compare",
    "evaluate",
    "AgentRun",
    "ToolCallStatus",
    "RunStatus",
    "JSONReporter",
    "CSVReporter",
    "start_ingest_server",
]

_engine = MetricsEngine()


def evaluate(run: AgentRun) -> EvalResult:
    """Evaluate a completed AgentRun and return an EvalResult."""
    return _engine.evaluate(run)


# ── pprof 风格的一行接入 ──────────────────────────────────────────────────────

from agenttrace.integrations.generic.auto_patch import AutoPatchSession as _APS
from agenttrace.integrations.generic.auto_patch import AutoPatcher as _APatcher
from agenttrace._context import get_collector as _get_col

def watch(
    *modules: str,
    task: str = "",
    agent_name: str = "agent",
    expected_output: Optional[str] = None,
    llm_modules:   Optional[list] = None,
    skill_modules: Optional[list] = None,
    exclude:       Optional[list] = None,
    review_level:  int = 2,
):
    """
    pprof 风格的装饰器——一行接入，零改源码。

    import agenttrace
    agenttrace.watch("myagent.tools", "myagent.llm")

    @agenttrace.watch("myagent.tools")
    def main():
        output = my_agent.run(task)
        return output

    result = main()
    print(agenttrace.last_result().summary())
    """
    import functools

    def decorator(fn: Callable) -> Callable:
        t = task or fn.__name__
        name = agent_name or fn.__name__
        # 自动把 llm_modules / skill_modules 合并进 modules，确保它们都被 patch
        all_modules = list(modules)
        for m in (llm_modules or []) + (skill_modules or []):
            if m not in all_modules:
                all_modules.append(m)

        if asyncio.iscoroutinefunction(fn):
            @functools.wraps(fn)
            async def async_wrapper(*args, **kwargs):
                with _APS(
                    modules=all_modules,
                    task=t, agent_name=name,
                    expected_output=expected_output,
                    llm_modules=llm_modules,
                    skill_modules=skill_modules,
                    exclude=exclude,
                    review_level=review_level,
                ) as sess:
                    result = await fn(*args, **kwargs)
                    sess.set_output(str(result) if result is not None else "")
                global _last_watch_result
                _last_watch_result = sess.result
                return result
            return async_wrapper

        @functools.wraps(fn)
        def sync_wrapper(*args, **kwargs):
            with _APS(
                modules=all_modules,
                task=t, agent_name=name,
                expected_output=expected_output,
                llm_modules=llm_modules,
                skill_modules=skill_modules,
                exclude=exclude,
                review_level=review_level,
            ) as sess:
                result = fn(*args, **kwargs)
                sess.set_output(str(result) if result is not None else "")
            global _last_watch_result
            _last_watch_result = sess.result
            return result
        return sync_wrapper

    return decorator


_last_watch_result = None

def last_result() -> Optional["EvalResult"]:
    """返回最近一次 @watch 装饰的函数的评测结果。"""
    return _last_watch_result


# ── pprof 风格：顶部一行永久开启，之后每次调用自动采集 ───────────────────────

from agenttrace.integrations.generic.auto_patch import AutoPatcher as _AutoPatcher
from agenttrace.integrations.generic.auto_patch import AutoPatchSession as _AutoPatchSession

_global_patcher: Optional[_AutoPatcher] = None
_global_llm_modules:   Optional[list] = None
_global_skill_modules: Optional[list] = None
_global_review_level: int = 2


def patch(
    *modules: str,
    llm_modules:   Optional[list] = None,
    skill_modules: Optional[list] = None,
    exclude:       Optional[list] = None,
    review_level:  int = 2,
) -> None:
    """
    pprof 风格：在 main.py 顶部调用一次，永久 patch 目标模块。
    之后每次用 session() 包住 agent 调用，自动采集指标。

    # main.py
    import agenttrace
    agenttrace.patch(
        "myagent.tools",
        "myagent.llm",
        llm_modules=["myagent.llm"],
    )

    result = agenttrace.session("task")(my_agent.run)("task text")
    print(agenttrace.last_result().summary())
    """
    global _global_patcher, _global_llm_modules, _global_skill_modules, _global_review_level
    all_modules = list(modules)
    for m in (llm_modules or []) + (skill_modules or []):
        if m not in all_modules:
            all_modules.append(m)
    _global_patcher       = _AutoPatcher(all_modules,
                                         llm_modules=llm_modules,
                                         skill_modules=skill_modules,
                                         exclude=exclude)
    _global_patcher.apply()
    _global_llm_modules   = llm_modules
    _global_skill_modules = skill_modules
    _global_review_level  = review_level if review_level in (1,2,3) else 2


def session(
    task:            str = "",
    agent_name:      str = "agent",
    expected_output: Optional[str] = None,
    review_level:    Optional[int] = None,
) -> "Callable":
    """
    包住单次 agent 调用，采集本次运行的指标。
    必须在 patch() 之后使用。

    # 用法一：直接包函数调用
    output = agenttrace.session("查天气")(agent.run)("查天气")

    # 用法二：with 块
    with agenttrace.session("查天气") as s:
        output = agent.run("查天气")
        s.set_output(output)
    print(agenttrace.last_result().summary())
    """
    from agenttrace._context import set_collector, reset_collector
    from agenttrace.collectors.runtime import RuntimeCollector
    from agenttrace.metrics.engine import MetricsEngine

    eng = MetricsEngine()

    class _Session:
        def __init__(self):
            self._col   = RuntimeCollector(
                task=task, agent_name=agent_name,
                expected_output=expected_output,
            )
            self._token = None
            self._review_level = review_level if review_level in (1,2,3) else _global_review_level

        # ── with 块用法 ──────────────────────────────────────────────────
        def __enter__(self):
            self._col.__enter__()
            self._token = set_collector(self._col)
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            reset_collector(self._token)
            self._col.__exit__(exc_type, exc_val, exc_tb)
            global _last_watch_result
            _last_watch_result = eng.evaluate(self._col.run)
            try:
                from agenttrace.review import review_run
                _demo_llm = __import__("examples.demo_agent.llm", fromlist=["chat"])
                review = review_run(self._col.run, _last_watch_result, llm_chat=_demo_llm.chat, review_level=self._review_level)
                if review is not None:
                    _last_watch_result.llm_review_summary = review.summary
                    _last_watch_result.llm_review_findings = review.findings
                    setattr(self._col.run, "llm_review", {
                        "summary": review.summary,
                        "findings": review.findings,
                        "model": review.model,
                        "review_level": self._review_level,
                        "raw": review.raw,
                    })
                    setattr(_last_watch_result, "llm_review_level", self._review_level)
            except Exception as review_error:
                setattr(self._col.run, "llm_review", {"error": str(review_error)})
            try:
                from agenttrace.dashboard.store import get_store
                from agenttrace.dashboard.server import push_event
                doc = get_store().save(self._col.run, _last_watch_result)
                push_event(doc)
            except Exception:
                pass
            return False

        def set_output(self, output: str) -> None:
            self._col.set_output(output)

        # ── 函数包装用法 ─────────────────────────────────────────────────
        def __call__(self, fn: "Callable") -> "Callable":
            import functools
            sess = self

            if asyncio.iscoroutinefunction(fn):
                @functools.wraps(fn)
                async def async_wrap(*args, **kwargs):
                    async with sess:
                        result = await fn(*args, **kwargs)
                        sess.set_output(str(result) if result is not None else "")
                    return result
                return async_wrap

            @functools.wraps(fn)
            def sync_wrap(*args, **kwargs):
                with sess:
                    result = fn(*args, **kwargs)
                    sess.set_output(str(result) if result is not None else "")
                return result
            return sync_wrap

        # ── async with 支持 ──────────────────────────────────────────────
        async def __aenter__(self):
            return self.__enter__()

        async def __aexit__(self, *args):
            return self.__exit__(*args)

    return _Session()


from contextlib import contextmanager
import uuid as _uuid
from agenttrace._context import set_group as _set_group_ctx

@contextmanager
def parallel_group(name: str | None = None):
    """
    显式标记一个并行 fan-out 分组。

    with agenttrace.parallel_group("weather_queries"):
        ... 并行发多个工具请求 ...
    """
    gid = name or f"parallel-{str(_uuid.uuid4())[:8]}"
    with _set_group_ctx(gid):
        yield gid

from agenttrace.ingest import start_ingest_server
