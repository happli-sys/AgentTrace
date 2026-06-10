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

- 监听 `LLM / Tool / Skill` 执行流
- 记录并行、重试、fallback、重复调用
- 采集 `Prompt / Response / Context / Plan / Execution` 等状态快照
- 本地落盘运行记录并提供 Dashboard 可视化
- 运行后用 LLM 自动复盘冗余、失败与可疑调用
- 生成结构化问题诊断：关键路径、恢复链路、冗余调用、可疑决策

---

## 安装

```bash
git clone https://github.com/happli-sys/AgentTrace.git
cd AgentTrace
pip install -e .
```

> 当前推荐从源码安装。未来发布到 PyPI 时，发布名将使用 `agenttrace-runtime`，导入仍然是 `import agenttrace`。

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
