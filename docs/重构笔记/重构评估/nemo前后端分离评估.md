# Nemo-Assistant 前后端分离评估

> 分析当前耦合现状、分离可行性和推荐方案

---

## 一、当前架构全局图

```
main.py
  └─ MainWindow (ui/main_window.py)
       └─ ChatSessionController (ui/chat_session_controller.py)  ← ★ 胶水层
            ├── 创建 AgentLoop(LLMGateway, ToolRegistry, ...)      ← "后端"
            ├── 连接 AgentLoop.QtSignals → UI 更新                 ← 绑定点
            └── 管理 ChatWidget / InputWidget / SessionPanel       ← "前端"
```

### 依赖关系图

```
┌─────────────────────────────────────────────┐
│                  UI 层 (ui/*.py)             │
│  main_window, chat_widget, input_widget,     │
│  session_panel, result_bubble, tool_card...  │
└────────────────────┬────────────────────────┘
                     │ 创建 & 订阅信号
                     ▼
┌─────────────────────────────────────────────┐
│          ChatSessionController              │  ← 胶水层 (860行)
│  - _submit_turn → 创建 AgentLoop            │
│  - _connect_worker → 连接 QtSignals         │
│  - _on_text_chunk / _on_tool_event / ...    │
└────────────────────┬────────────────────────┘
                     │ 直接实例化
                     ▼
┌─────────────────────────────────────────────┐
│           AgentLoop (QThread)               │  ← "后端"核心
│  - 状态机: PREPARE→STREAM→EXECUTE→FEEDBACK  │
│  - pyqtSignal: text_chunk, tool_event, ...  │
│  - 依赖: LLMGateway, ToolRegistry           │
└────────────────────┬────────────────────────┘
                     │ 调用
                     ▼
┌─────────────────────────────────────────────┐
│         LLMGateway + ToolRegistry           │  ← 纯逻辑（无 Qt 依赖）
│  - LiteLLM 流式调用                          │
│  - 20+ 工具执行                              │
└─────────────────────────────────────────────┘
```

---

## 二、耦合点清单

### 🔴 硬耦合（必须解除才能分离）

| # | 耦合点 | 位置 | 说明 |
| --- | -------- | ------ | ------ |
| 1 | **AgentLoop 继承 QThread** | `agent_loop.py:66` | `class AgentLoop(QThread)` — 核心循环与 Qt 线程模型绑定 |
| 2 | **pyqtSignal 作为唯一通信通道** | `agent_loop.py:74-79` | `text_chunk` / `tool_event` / `state_changed` / `need_input` / `new_turn` / `done` — 6 个信号 |
| 3 | **ChatSessionController 直接 new AgentLoop** | `chat_session_controller.py:431` | `worker = AgentLoop(llm_gateway=..., registry=..., ...)` |
| 4 | **_connect_worker 直接 .connect() Qt 信号** | `chat_session_controller.py:573-595` | `worker.text_chunk.connect(lambda ...)` |

### 🟡 软耦合（可保留但需适配）

| # | 耦合点 | 说明 |
| --- | -------- | ------ |
| 5 | **LLMGateway 被多处直接引用** | UI 组件（result_bubble, consolidator）也直接调用 LLMGateway，不仅是 AgentLoop |
| 6 | **ToolRegistry 全局共享** | AgentLoop 和 UI（toolbox_panel, tool_editor）共享同一个 registry 实例 |
| 7 | **cfg 全局配置** | `app.config.config.cfg` 被所有层直接 import |
| 8 | **SessionManager 与 ChatSessionController 紧耦合** | controller 直接操作 session CRUD |

### 🟢 天然解耦（无需改动）

| 模块 | 说明 |
| ------ | ------ |
| `LLMGateway` | 纯 Python，无 Qt 依赖 |
| `ToolRegistry` + 所有工具 | 纯 Python，无 Qt 依赖 |
| `consolidator` / `context_manager` | 纯 Python |
| `trace_store` / `cost_calculator` | 纯 Python |
| `prompt_builder` | 纯 Python |

---

## 三、分离可行性分析

### 3.1 核心问题：AgentLoop 的 Qt 依赖

当前 AgentLoop 承担了**两个职责**：

| 职责 | 代码 | Qt 依赖 |
| ------ | ------ | :------: |
| Agent 调度逻辑（状态机） | `_state_prepare/stream/execute/feedback/wrap_up/finalize` | ❌ 不需要 |
| 与 UI 通信（信号发射） | `text_chunk.emit()`, `tool_event.emit()`, `done.emit()` | ✅ 已绑定 |

**好消息**：调度逻辑（~400 行）可以完整剥离，它只是读写 `TurnContext` 并调用 `LLMGateway` 和 `ToolRegistry`，完全不碰 Qt。

### 3.2 分离方案

```
分离前（现状）：
┌──────────────────────────────┐
│      AgentLoop(QThread)      │
│  ┌────────────────────────┐  │
│  │  状态机调度逻辑 (400行)  │  │  ← 纯 Python
│  │  LLM 调用               │  │
│  │  工具执行                │  │
│  └────────────────────────┘  │
│  ┌────────────────────────┐  │
│  │  Qt 信号发射             │  │  ← Qt 绑定
│  │  QThread 生命周期        │  │
│  └────────────────────────┘  │
└──────────────────────────────┘

分离后（目标）：
┌──────────────────────────────┐     ┌──────────────────────────────┐
│    NemoAgent (纯 Python)      │     │  AgentThread(QThread) 薄封装  │
│  ┌────────────────────────┐  │     │  ┌────────────────────────┐  │
│  │  run_loop(messages,     │  │     │  │  持有 NemoAgent 实例    │  │
│  │    callbacks) → result  │  │────→│  │  将 callbacks 桥接到    │  │
│  │                        │  │     │  │  Qt signals            │  │
│  │  - 无 Qt 依赖           │  │     │  └────────────────────────┘  │
│  │  - 可测试/可复用        │  │     │  仅 ChatSessionController    │
│  │  - 可换 UI 框架         │  │     │  使用此封装                  │
│  └────────────────────────┘  │     └──────────────────────────────┘
└──────────────────────────────┘
```

---

## 四、具体分离实施

### Step 1：定义 Agent 回调接口（替换 Qt Signals）

```python
# app/agent/agent_interface.py — 新增文件

from dataclasses import dataclass, field
from typing import Callable, Any, Protocol

@dataclass
class AgentCallbacks:
    """纯 Python 回调集合，替代 pyqtSignal。"""
    
    on_text_chunk: Callable[[str], None] | None = None
    on_tool_start: Callable[[str, str, dict], None] | None = None   # (call_id, name, params)
    on_tool_done: Callable[[str, str, dict], None] | None = None    # (call_id, name, result)
    on_turn_start: Callable[[int], None] | None = None              # (turn_count)
    on_state_change: Callable[[str], None] | None = None            # (state_name)
    on_need_input: Callable[[str, str, list], None] | None = None
    on_done: Callable[[dict], None] | None = None                   # (result_dict)
```

### Step 2：从 AgentLoop 中提取 NemoAgent（纯逻辑）

```python
# app/core/nemo_agent.py — 新增文件

class NemoAgent:
    """
    纯 Python Agent 核心，不依赖 PyQt6。
    
    用法：
        agent = NemoAgent(llm_gateway, registry)
        result = agent.run(
            messages=api_messages,
            callbacks=AgentCallbacks(
                on_text_chunk=lambda delta: print(delta, end=""),
                on_tool_start=lambda cid, name, args: print(f"\n🔧 {name}"),
                on_done=lambda info: print(f"\n✅ {info}"),
            ),
            session_id="...",
            max_turns=10,
        )
    """
    
    def __init__(self, llm_gateway, registry, trace_store=None, hooks=None):
        self._llm = llm_gateway
        self._registry = registry
        self._trace_store = trace_store
        self._hooks = CompositeHook(hooks) if hooks else None
    
    def run(
        self,
        messages: list[dict],
        callbacks: AgentCallbacks,
        *,
        session_id: str = "",
        max_turns: int = 10,
        cancel_token: CancellationToken | None = None,
        tools: list[dict] | None = None,
    ) -> dict:
        """
        执行完整的 Agent 运行。
        
        返回: {"ok": bool, "error": str|None, "trace": [...]}
        """
        if tools is None:
            tools = self._registry.get_openai_functions()
        
        ctx = TurnContext(
            messages=list(messages),
            tools=tools,
            max_turns=max_turns,
        )
        
        # ... 状态机主循环（从 AgentLoop.run() 复制，去掉 self.xxx.emit()）...
        # 所有 self.xxx.emit() 替换为 callbacks.on_xxx()
```

### Step 3：Qt 薄封装

```python
# app/ui/agent_thread.py — 新增文件（或保留在 chat_session_controller）

class AgentThread(QThread):
    """将 NemoAgent 桥接到 Qt 信号体系的薄封装。"""
    
    # 保持现有信号不变（向前兼容 UI）
    text_chunk = pyqtSignal(str)
    tool_event = pyqtSignal(str, str, dict)
    need_input = pyqtSignal(str, str, list)
    new_turn = pyqtSignal(int)
    done = pyqtSignal(dict)
    
    def __init__(self, agent: NemoAgent, api_messages, session_id, ...):
        super().__init__()
        self._agent = agent
        self._api_messages = api_messages
        self._session_id = session_id
        self._cancel_token = CancellationToken()
    
    def run(self):
        callbacks = AgentCallbacks(
            on_text_chunk=lambda delta: self.text_chunk.emit(delta),
            on_tool_start=lambda cid, name, args:
                self.tool_event.emit(cid, "start", {"name": name, "params": args}),
            on_tool_done=lambda cid, name, result:
                self.tool_event.emit(cid, "done", {"name": name, "result": result}),
            on_turn_start=lambda tc: self.new_turn.emit(tc),
            on_done=lambda info: self.done.emit(info),
        )
        result = self._agent.run(
            messages=self._api_messages,
            callbacks=callbacks,
            session_id=self._session_id,
            cancel_token=self._cancel_token,
        )
        # agent.run 已经通过 callbacks 发射了 done，这里不重复
    
    def cancel(self):
        self._cancel_token.cancel()
```

---

## 五、分离后的收益

| 收益 | 说明 |
| ------ | ------ |
| **可测试性** | `NemoAgent` 可在 CI 中无头运行，mock callbacks 即可断言 |
| **可复用** | 同一套 agent 逻辑可用于 CLI 版、Web 版、HTTP API 版 |
| **可替换 UI 框架** | 从 PyQt6 迁移到 PySide6 / Textual / Web 只需写新的 `AgentThread` 等价物 |
| **代码清晰** | 状态机和 UI 通信彻底分离，各自独立演进 |
| **插件友好** | 第三方可以 import `NemoAgent` 做自己的 UI，不需要依赖 PyQt6 |

---

## 六、工作量评估

| 步骤 | 内容 | 改动范围 | 时间 |
| :----: | ------ | ---------- | :----: |
| 1 | 定义 `AgentCallbacks` 接口 | 新增 1 文件 | 0.5h |
| 2 | 从 `AgentLoop` 提取 `NemoAgent` | 重构 agent_loop.py | 3h |
| 3 | 创建 `AgentThread` Qt 封装 | 新增/修改 chat_session_controller | 1h |
| 4 | 适配现有测试 | tests/ | 2h |
| 5 | 回归测试 + 修复 | 全面 | 4h |
| **合计** | | | **~1.5 天** |

---

## 七、结论

| 问题 | 答案 |
| ------ | ------ |
| **现在是耦合的吗？** | ✅ 是。AgentLoop 同时承担调度逻辑 + Qt 通信，不可拆分。 |
| **能分离吗？** | ✅ 能。调度逻辑 (~400行) 零 Qt 依赖，可直接提取为纯 Python。 |
| **值得做吗？** | ✅ 值得。投入 1.5 天，收益是：可测试、可复用、可换 UI 框架。 |
| **建议时机** | 在完成「pi 设计移植」的 Phase 1 之后做，先加功能再重构，风险最小。 |

---

> 📌 分离后，`NemoAgent` 的 API 可以和 pi 的 `Agent` 类对标——两者都是「传入 messages + tools + callbacks → 返回结果」的模式。届时再做内核替换评估，结论会完全不同。
