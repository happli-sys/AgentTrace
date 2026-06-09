# AgentTrace

AgentTrace 是一个面向 **AI Agent 执行流监听、追踪与诊断** 的开源工具。

它不是单纯的输出评测框架，也不是 benchmark 平台。
它更接近一个给 Agent 用的 `pprof / tracing / runtime diagnostics` 工具：

- 监听 `LLM` 调用
- 监听 `Tool` 调用
- 监听 `Skill` 执行
- 记录并行、重试、fallback、重复调用
- 记录 `Prompt / Response / Context / Plan / Execution` 等状态快照
- 在执行结束后做一次 **LLM 复盘**
- 在本地启动一个前端页面查看完整执行链路

---

## 适合什么场景

AgentTrace 适合这些场景：

- 你有一个 **有源码的 agent**，想知道它运行时到底做了什么
- 你想排查：
  - 为什么它慢
  - 为什么它重复调用工具
  - 为什么它 fallback
  - 为什么它输出不稳定
- 你想把 agent 的执行流落盘到本地，做回放和诊断
- 你想给 CLI Agent / 自定义 Agent / Demo Agent 加一个轻量的运行时观察层

---

## 当前核心能力

### 1. 执行流监听

可监听的核心调用类型：

- `LLM`
- `Tool`
- `Skill`
- `System step`

每次运行会形成完整调用链，包括：

- 调用开始/结束时间
- 耗时
- 输入参数
- 调用状态
- 并行分组
- 重试与 fallback

### 2. 结构化状态快照

对 LLM span，当前支持采集这些状态：

- `ContextSnapshot`
- `MemorySnapshot`
- `PlanSnapshot`
- `DecisionSnapshot`
- `ResumeSnapshot`
- `ExecutionSnapshot`

其中 `ExecutionSnapshot` 重点覆盖：

- 中断/恢复原因
- 重试次数 / 重试原因 / backoff
- 工具候选集 / 技能候选集
- 参数来源
- 上下文裁剪策略
- 恢复动作
- 是否需要人工接管
- 是否需要审批
- 终止原因

### 3. 本地落盘

每次运行会落盘到：

```text
listen/
  YYYYMMDD-HHMM/
    <run_id>.json
    sessions.jsonl
```

每条 session 文档包含：

- `trace`
- `steps`
- `tool_calls`
- `events`
- `metrics`
- `llm_review`
- `diagnostics`

### 4. Dashboard

本地前端地址：

- `http://localhost:3500`

当前页面支持：

- 会话列表
- 调用链时间轴
- 并行泳道展示
- 默认折叠重复/并行同类工具调用
- LLM 的 Prompt / Response 弹窗
- 状态标签页：
  - `Context`
  - `Plan`
  - `Execution`
  - `Resume`
- 问题诊断视图
- LLM 复盘区块
- 最终 Agent 输出折叠/展开

### 5. LLM 复盘

每次运行结束后，可自动调用 LLM 对执行流做复盘。

复盘目标包括：

- 多余工具调用
- 错误工具调用
- 失败工具调用
- 可疑 fallback
- 多余 / 错误 skill 调用
- 执行流中的明显问题

支持严格度配置：

- `review_level=1`：开放，少报问题
- `review_level=2`：平衡，默认模式
- `review_level=3`：保守，更严格

说明：

- `level=1/2` 前端默认不展示 `low` 等级 findings
- `level=3` 会展示全部 findings

### 6. 问题诊断视图

除了自然语言复盘，AgentTrace 还会生成结构化诊断摘要，突出：

- 关键路径
- 失败工具
- 恢复链路
- 冗余调用簇
- 可疑决策
- findings 严重度分布

---

## 安装

```bash
pip install agenttrace
```

> 当前仓库中的 Python 包名已经迁移为 `agenttrace`。

---

## 快速接入

## 1）pprof 风格接入

先 patch 一次目标模块，然后每次运行用 `session(...)` 包一层即可。

```python
import agenttrace
from my_agent import run

agenttrace.patch(
    "my_agent.tools",
    "my_agent.skills",
    "my_agent.llm",
    llm_modules=["my_agent.llm"],
    skill_modules=["my_agent.skills"],
    review_level=2,
)

output = agenttrace.session("查北京天气并计算 1+2")(run)("查北京天气并计算 1+2")
print(output)
print(agenttrace.last_result().summary())
```

### review level

```python
agenttrace.patch(..., review_level=1)
agenttrace.patch(..., review_level=2)
agenttrace.patch(..., review_level=3)
```

也可以按单次运行覆盖：

```python
agenttrace.session("task", review_level=1)(run)("task")
```

---

## 2）启动 dashboard

```python
from agenttrace.dashboard.server import start_server

start_server(port=3500)
```

打开：

- `http://localhost:3500`

---

## 3）Demo Agent

仓库中自带一个演示用 agent：

- `examples/demo_agent/`

它覆盖了这些场景：

- `bash`
- `read`
- `grep`
- `calculate`
- `get_weather`
- `flaky_weather`
- `weather_report_skill`
- 并行天气查询
- fallback from `flaky_weather` to `get_weather`

运行方式：

```bash
python examples/demo_agent/main.py
```

然后打开：

- `http://localhost:3500`

推荐测试 prompt：

```text
分析当前目录下的项目；bash pwd；read examples/demo_agent/tools.py；grep calculate examples/demo_agent；查北京和西安的天气，并计算1123123123+1283123；生成北京天气播报；最后总结。
```

---

## 4）适配思路

### 有源码的 Python Agent

最适合直接接入：

- `patch(...)`
- `session(...)`

### CLI Agent

可以通过 hook / sidecar / 本地事件服务接入。

当前仓库里也保留了 CLI hook 方向的接入示例与实现思路。

---

## 5）当前定位

AgentTrace 当前更适合被理解为：

- 一个 **通用 Agent 执行流监听工具**
- 一个 **本地优先的 tracing / diagnostics 工具**
- 一个 **面向调试、排障、性能诊断** 的开发者工具

它当前**不是**：

- 完整 benchmark 平台
- 数据集管理平台
- SaaS 托管评测系统
- leaderboard 产品

---

## 6）仍然保留的评测能力

虽然项目现在重心是执行流监听与诊断，但仍保留一些客观指标能力：

- 总耗时
- 平均 / P95 step latency
- 工具成功率
- token 消耗
- 费用估算
- step efficiency
- correctness（若提供 expected_output）
- regression tracking
- comparison helpers

所以它仍可以作为一个轻量 runtime eval layer 使用，只是定位已经不再是“纯评测框架”。

---

## 开发

```bash
git clone https://github.com/your-org/agenttrace
cd agenttrace
pip install -e ".[dev]"
pytest tests/
```

---

## License

MIT
