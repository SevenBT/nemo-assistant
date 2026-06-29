# 安全评测系统 — 构建全流程导览

> 面向：想搞清楚「这套可观测 / 安全 / 评测地基怎么来的、原来什么样、现在什么样」的开发者。
> 读完你能：看懂整体架构、知道每块代码在哪、明白一次对话运行如何被完整记录下来。

---

## 0. 一句话概括

把原本**散落三处、互不关联**的零星埋点，重构成一套**以 `trace_id` 为主线**的统一链路系统：一次 Agent 运行 = 一个 `trace_id`，它下面的 LLM 调用、工具调用、安全审计、评测样本、状态机流转全部串在一起，落进独立的 `traces.db`，并在「设置 → 运行记录」里可视化回放。

---

## 1. 改造前：是「点」，不是「系统」

改造前，系统里确实有一些观测/防护动作，但它们是**孤立的点**，彼此不共享任何关联键：

| 已有的「点」 | 在哪 | 问题 |
|---|---|---|
| LLM 调用日志 | `GatewayLogger` 写 JSONL | 只记网关侧，和具体哪次对话、哪次工具调用对不上号 |
| 工具错误分类 | `ToolRegistry` 的 `ToolErrorType` | 分类了，但不落库、不可回放 |
| 状态机 trace | `AgentLoop` 内存里的 `ctx.trace` | turn 结束即丢，只在内存 |

三个点各说各话：你无法回答「**上周三那次失败的对话，LLM 返回了什么、调了哪些工具、token 花了多少、卡在哪个状态**」——因为没有一根线把它们串起来。

安全方面更弱：

- `run_python` 工具直接在**主进程 `exec()`**，把完整 `__builtins__` 和所有环境变量（含 API Key）暴露给 LLM 生成的代码 —— 一个后门。
- 没有任何「工具执行前审批」的挂载点，想加安全策略只能改状态机核心。

---

## 2. 改造后：以 trace_id 为主线的统一系统

```
一次对话运行（AgentLoop.run）
        │  生成唯一 trace_id
        ▼
┌─────────────────────────────────────────────────────────┐
│  trace_id 贯穿全程                                         │
│                                                           │
│  ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌────────┐ │
│  │ LLM 调用  │   │ 工具调用  │   │ 安全审计  │   │ 评测   │ │
│  │ llm_calls│   │tool_calls│   │ security │   │ eval   │ │
│  └────┬─────┘   └────┬─────┘   └────┬─────┘   └───┬────┘ │
│       └──────────────┴──────┬───────┴─────────────┘      │
│                             ▼                            │
│                   全部 keyed by trace_id                 │
│                             ▼                            │
│                      traces.db (SQLite)                  │
└─────────────────────────────────────────────────────────┘
                             ▼
              设置 → 运行记录（TracePage 回放）
```

核心思想来自两点：
1. **统一关联键**：`trace_id` 在 `AgentLoop.run()` 一开始生成，贯穿其下所有子操作。
2. **横切关注点用 Hook 解耦**（借鉴 nanobot 的 AgentHook，但适配我们的同步 QThread 状态机）：安全审批、评测埋点不塞进状态机分支，而是挂在扩展点上。

---

## 3. 五块地基逐一讲解

整个系统由五块拼成，下面每块都讲清「**原来 → 现在 → 代码在哪**」。

### 地基 0：统一 Trace 存储（`app/core/trace_store.py`）

这是所有东西的落脚点。

- **原来**：没有统一存储，三个点各写各的（JSONL / 内存 / 不落）。
- **现在**：独立的 `data/traces.db`，不污染业务 `notes.db`，可单独清理/限容。

**关键设计**：

1. **独立库**：遥测和业务数据物理隔离。
2. **多线程安全写**：AgentLoop 在 QThread、只读工具在 ThreadPoolExecutor，并发写 —— 每次操作开独立短连接 + 进程内写锁 + WAL 模式。
3. **异常绝不波及主流程**：所有写入 `try/except` 包死，只 log 不抛。遥测坏了，对话照常。
4. **入参脱敏**：`_redact_args()` 把 `api_key`/`token`/`password` 等敏感键打码成 `***`，并剥掉 `_` 开头的内部参数（如 `_session_id`）。

**表结构**（6 张表，全部 keyed by `trace_id`）：

| 表 | 存什么 |
|---|---|
| `turns` | 一次运行的汇总：状态、轮数、耗时、token 总量、错误 |
| `llm_calls` | 每次 LLM 往返：模型、延迟、token、错误 |
| `tool_calls` | 每次工具调用：名称、脱敏入参、结果、耗时 |
| `state_trace` | 状态机流转：PREPARE→STREAM→EXECUTE… |
| `security_events` | 高风险工具调用 + 裁决（放行/拒绝） |
| `eval_samples` | 每轮最终答复 + 工具/错误计数 + `scores`（留空待打分）|

> `security_events` 和 `eval_samples` 是第 4 步新增的两张表，前 4 张是地基阶段建的。

### 地基 1：Hook 扩展点（`app/core/agent_hooks.py`）

让安全/评测能「零侵入」挂上去的机制层。

- **原来**：想在工具执行前做点事（审批、埋点），只能改 `AgentLoop` 状态机核心。
- **现在**：定义 `AgentHook` 基类 + 两个挂载点，新增能力 = 新增一个 Hook 实现。

**两个挂载点**：

```
before_execute_tools   工具执行前 —— 可裁决放行/拒绝（安全审批的天然位置）
after_iteration        一轮 STREAM→EXECUTE 结束后 —— 可读工具结果（评测埋点的天然位置）
```

**比 nanobot 强的地方 —— 软拒绝**：
nanobot 的 `before_execute_tools` 只能读、要中止只能抛异常（硬失败）。我们支持**软拒绝**：返回 `ToolDecision(action="reject")` 时，该工具不执行，转而向 LLM 回灌一条拒绝说明，loop 照常继续 —— LLM 能看到拒绝并改走别的路。

**组合与异常隔离**：`CompositeHook` 把多个 hook 串起来，裁决「最严格者胜」（任一 hook 拒绝即拒绝）；非安全 hook 异常被吞掉只 log，安全 hook（`reraise=True`）异常透传。

### 地基 2：Token 用量落库（`app/core/llm_gateway.py`）

- **原来**：token 用量根本没采集，更没落库。
- **现在**：流式响应里抓 usage，落到 `llm_calls`，turn 结束时 SUM 汇总到 `turns`。

**关键技术点**：

1. 请求里加 `stream_options={"include_usage": True}`，usage 出现在**最后一帧**（choices 为空的那帧）。
2. `_normalize_usage()` 宽松解析：兼容 SDK 对象和 dict，total 缺失自动算，cached_tokens 两个位置都试。
3. **trace_id 贯穿**：`chat_stream(trace_id=...)` 由 AgentLoop 传入；缺省才自生成（保留 4 个非 AgentLoop 调用方的兼容）。
4. `_write_log` 既写 JSONL，又通过 `trace_sink`（即 TraceStore）落 `llm_calls`。

> ⚠️ 这里埋过一个隐蔽 bug，见第 6 节。

### 地基 3：run_python 后门封死（`app/tools/run_python.py`）

- **原来**：主进程 `exec(compile(code, ...), {"__builtins__": __builtins__, ...})` —— LLM 生成的代码能读到主进程**所有环境变量**（包括 API Key）和完整 builtins。这是绕过一切防护的后门。
- **现在**：子进程隔离执行。

**改法**：

```python
subprocess.run(
    [sys.executable, "-I", "-c", code],   # -I 隔离模式
    env=_build_minimal_env(),              # 最小环境变量白名单
    timeout=timeout,                       # 超时保护
    ...
)
```

1. **子进程**：用同一个解释器（保留已安装的第三方包），但代码崩溃/`sys.exit`/死循环都不波及主进程。
2. **`-I` 隔离模式**：忽略所有 `PYTHON*` 环境变量和 user site-packages，杜绝 `sys.path` 注入。
3. **环境变量白名单**：只透传 `PATH`/`SYSTEMROOT`/`TEMP` 等系统必需变量，**主动剔除一切 `*_API_KEY`/`*_SECRET`/`*_PASSWORD`/`*_TOKEN`**。
4. **超时 + 输出截断**：默认 30s、最大 120s；stdout/stderr 各截 32000 字。

**验证过的关键点**：往主进程注入假密钥 `OPENAI_API_KEY`，子进程读到的是 `None` —— 后门确认封死。

### 地基 4：安全审计 + 评测 Hook（`app/core/audit_hooks.py`）

把前面的机制（Hook）变成实际策略。这是「策略层」，和 `agent_hooks.py`（机制层）分开。

**`SecurityAuditHook`**（挂 `before_execute_tools`）：
- 命中 `HIGH_RISK_TOOLS`（`exec`/`run_python`/`save_file`，定义在 `ToolRegistry`）就记一条 `security_events`。
- **默认只审计不拦截**（安全：先观察，不破坏现有行为）。
- 保留 `blocked_tools` 通道：命中即软拒绝（复用地基 1 的软拒绝机制）。

**`EvalHook`**（挂 `after_iteration`）：
- 每轮把最终答复 + 工具/错误计数落 `eval_samples`，`scores` 列留空待离线打分。
- **纯文本收尾轮也触发**（见第 6 节的「after_iteration gap」修复），保证最终答复必被采集。

两者都 `reraise=False` —— 坏了也不拖垮对话。

---

## 4. 一次对话运行如何被完整记录（数据流）

跟着一次真实运行走一遍，看每块在什么时候被触发：

```
用户发消息
   │
   ▼
ChatSessionController.submit()
   │  创建 AgentLoop，注入 trace_store + hooks（_build_hooks）
   ▼
AgentLoop.run()                          ① trace_store.start_turn(trace_id)  → turns 表
   │
   ├─ _state_stream                      ② chat_stream(trace_id, seq)
   │     │                                  LLM 流式返回，done 帧带 usage
   │     └─ gateway._write_log ──────────③ trace_sink.record_llm_call()      → llm_calls 表
   │        （纯文本收尾轮）──────────────④ hook.after_iteration → EvalHook   → eval_samples 表
   │
   ├─ _state_execute
   │     ├─ _apply_before_tools_hook ────⑤ SecurityAuditHook 审计高风险工具   → security_events 表
   │     │     （命中 blocked 则软拒绝，回灌拒绝说明给 LLM）
   │     ├─ 执行工具（并发/串行）────────⑥ trace_store.record_tool_call()     → tool_calls 表
   │     └─ _fire_after_iteration ───────⑦ EvalHook 采集本轮样本             → eval_samples 表
   │
   ▼
AgentLoop 结束                            ⑧ record_state_trace() + finish_turn()
                                            状态机流转 → state_trace 表
                                            从 llm_calls SUM token 汇总到 turns 表
```

**接线点**（谁把 trace_store / hooks 传进去的）：

| 文件 | 干了什么 |
|---|---|
| `app/ui/main_window.py` | `TraceStore()` 创建；`LLMGateway(trace_sink=...)`；传给 controller 和 SettingsWindow |
| `app/ui/chat_session_controller.py` | `_build_hooks()` 构建 `[SecurityAuditHook, EvalHook]`；创建 AgentLoop 时注入 |
| `app/core/agent_loop.py` | 生成 `trace_id`；各状态调用 trace 写入和 hook 触发 |

---

## 5. 怎么查看（TracePage UI）

**设置 → 运行记录**（`app/ui/settings_pages/trace_page.py`）：

- **左侧**：最近运行列表（状态色点 + 时间 · token · 耗时）。
- **右侧**：
  - 顶部**概览卡**：状态徽章 + 会话名 + 关键指标（轮数、耗时、token 明细、trace 短 id），失败时红色错误行。
  - **分段切换**（SegmentedWidget）：LLM 调用 / 工具调用 / 安全审计 / 评测样本 / 状态机，五个分页各自结构化卡片列表，标题带计数。

只读：trace 由 `TraceStore.prune()` 自动限容（默认留最近 2000 个 turn），UI 不提供删除，避免误删审计证据。

---

## 6. 踩过的坑（也是排查方法论）

这套系统在落地时踩了几个真 bug，记下来供参考：

### ① after_iteration gap（设计漏洞）
最初 `after_iteration` 只在 `_state_execute` 触发。但**纯文本收尾轮**（没有工具调用的最后一轮）才是评测最关心的「最终答复」—— 它被漏掉了。修复：在 `_state_stream` 的 `no_tools` 路径和 `error` 路径也触发。

### ② 生成器 yield 之后的副作用丢失（最隐蔽）
**症状**：运行记录里「无 LLM 调用记录」，token 恒为 0，但工具调用有数据。
**根因**：`gateway._stream_with_retry` 的 `done` 事件原本是「先 `yield event`，后 `_write_log`」。AgentLoop 收到 `done` 立即 `break`，生成器永久挂起在 `yield` 处，**`yield` 之后的 `_write_log` 永不执行** → `llm_calls` 一行不落。`tool_calls` 不受影响是因为它由 AgentLoop 直接写、不走这条生成器。
**修法**：把 `_write_log` 移到 `yield` 之前。
**通用教训**：生成器里 `yield` 之后的副作用（日志/落库/清理），遇消费者提前 break 会永不执行 —— 必须放 `yield` 之前。

### ③ SegmentedWidget onClick 回调带 bool
`addItem(key, text, onClick)` 的回调连到按钮 `clicked` 信号，会收到一个 `bool` 参数。`lambda k=key: ...` 会被这个 `True` 覆盖默认值 → `KeyError: True`。修法：`lambda *_, k=key: ...`。

> 方法论：排查「A 类记录有、B 类记录空」时，优先怀疑两者落库路径的差异；用包裹函数打印确认副作用函数是否真被调用（本例发现 `_write_log` 一次都没被调，直接定位）。

---

## 7. 现在 vs 原来 总对比

| 维度 | 原来 | 现在 |
|---|---|---|
| 关联性 | 三个孤立的点，无共享键 | 统一 `trace_id` 贯穿 |
| 存储 | JSONL / 内存 / 不落 | 独立 `traces.db`，6 张表 |
| LLM 可观测 | 网关日志，对不上对话 | 落 `llm_calls`，含 token |
| 工具可观测 | 只分类，不落库 | 落 `tool_calls`，含耗时、脱敏入参 |
| 状态机 | 内存，turn 结束即丢 | 落 `state_trace`，可回放 |
| 安全审批 | 无挂载点，要改核心 | Hook 扩展点 + 软拒绝 |
| 高风险工具 | 无审计 | `security_events` 审计 + 可拦截 |
| 评测 | 无 | `eval_samples`，留 scores 待打分 |
| run_python | 主进程 exec，泄露密钥 | 子进程隔离，密钥不可见 |
| 回放 | 无 | 设置 → 运行记录 |

---

## 8. 未来扩展点（已留好接口，未实现）

1. **离线评测脚本**：读 `eval_samples`、调 LLM 打分、回填 `scores` 列（UI 已留位展示）。
2. **安全策略 UI**：能力面板把高风险工具切到 `blocked`，接通已留好的 `blocked_tools` 通道。
3. **更多 Hook**：成本预算 hook、PII 检测 hook 等 —— 都只需新增一个 `AgentHook` 实现，挂上即可，零侵入核心。

---

## 附：关键文件清单

| 文件 | 角色 |
|---|---|
| `app/core/trace_store.py` | 统一存储（6 表 + 写入/查询/回放/限容/脱敏）|
| `app/core/agent_hooks.py` | Hook 机制层（基类、裁决、组合器、软拒绝）|
| `app/core/audit_hooks.py` | Hook 策略层（SecurityAuditHook、EvalHook）|
| `app/core/agent_loop.py` | 状态机 + trace 写入 + hook 触发 |
| `app/core/llm_gateway.py` | LLM 网关 + token 采集 + trace_sink |
| `app/tools/run_python.py` | 子进程隔离执行（后门封死）|
| `app/tools/registry.py` | `HIGH_RISK_TOOLS` 定义、错误分类 |
| `app/ui/settings_pages/trace_page.py` | 运行记录回放 UI |
| `app/ui/chat_session_controller.py` | hooks/trace_store 接线 |
| `app/ui/main_window.py` | 全局装配点 |
