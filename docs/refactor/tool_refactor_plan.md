# 工具模块重构方案 — Phase 1 & Phase 2

> 基于 nanobot 架构分析，对 assistant 项目工具系统进行渐进式重构。

## 目录

- [Phase 1: 快速增强（不改架构）](#phase-1-快速增强不改架构)
- [Phase 2: 统一接口（小规模重构）](#phase-2-统一接口小规模重构)
- [待澄清问题](#待澄清问题)

---

## Phase 1: 快速增强（不改架构）

### 1.1 工具并发执行

**现状**：`agent_loop.py:_state_execute()` 中 `for i, tc in enumerate(ctx.tool_calls)` 串行执行所有工具。

**改造方案**：

```
改动文件：
├── app/core/agent_loop.py      ← 主要改动：并发执行逻辑
├── tools/*/manifest.json       ← 新增 "read_only": true/false 字段
└── app/models/tool_def.py      ← ToolDefinition 新增 read_only 属性
```

**工具只读分类**：

| 工具 | read_only | 理由 |
|------|-----------|------|
| web_search | true | 纯查询，无副作用 |
| fetch_url | true | 纯读取，无副作用 |
| read_file | true | 纯读取 |
| multi_model_consult | true | 纯查询 |
| save_file | **false** | 写文件，有副作用 |
| run_python | **false** | 执行代码，不可预测副作用 |
| reminder | **false** | 创建提醒，有副作用 |
| 内置: calculator | true | 纯计算 |
| 内置: clipboard(get) | true | 读取剪贴板 |
| 内置: clipboard(set) | **false** | 写入剪贴板 |
| 内置: create_note | **false** | 写数据库 |
| 内置: create_scheduled_task | **false** | 创建任务 |

**执行策略**：

```python
# 批次分区算法（伪代码）
def partition_batches(tool_calls, tool_manager, builtins):
    batches = []
    current_concurrent = []
    for tc in tool_calls:
        if is_read_only(tc):
            current_concurrent.append(tc)
        else:
            if current_concurrent:
                batches.append(("concurrent", current_concurrent))
                current_concurrent = []
            batches.append(("serial", [tc]))
    if current_concurrent:
        batches.append(("concurrent", current_concurrent))
    return batches
```

**并发实现**：使用 `concurrent.futures.ThreadPoolExecutor`（因为工具执行是 subprocess 阻塞调用，不是 async）。

```python
from concurrent.futures import ThreadPoolExecutor, as_completed

# 在 _state_execute 中
with ThreadPoolExecutor(max_workers=4) as pool:
    futures = {pool.submit(execute_one, tc): tc for tc in batch}
    for future in as_completed(futures):
        result = future.result()
        # 追加到 messages...
```

**Checkpoint 兼容**：并发批次内的工具全部完成后统一保存一次 checkpoint（而非每个工具后保存）。

**UI 信号**：并发执行时 `tool_event` 信号仍然逐个发射（ThreadPoolExecutor 内部加锁或用 QMetaObject.invokeMethod）。

---

### 1.2 结果大小限制和截断

**现状**：工具结果原样 `json.dumps` 后作为 tool message content，无大小限制。

**改造方案**：

```
改动文件：
├── app/core/agent_loop.py      ← 结果截断逻辑
└── app/core/config.py          ← 新增配置项 maxToolResultChars
```

**截断策略**：

```python
MAX_TOOL_RESULT_CHARS = 8000  # 默认 8000 字符（约 2000 token）

def truncate_tool_result(result: dict, max_chars: int = MAX_TOOL_RESULT_CHARS) -> str:
    content = json.dumps(result, ensure_ascii=False)
    if len(content) <= max_chars:
        return content
    # 截断并追加提示
    truncated = content[:max_chars]
    return truncated + "\n\n[结果已截断，原始长度 {} 字符，显示前 {} 字符]".format(
        len(content), max_chars
    )
```

**可配置**：通过 `cfg.maxToolResultChars` 允许用户调整阈值。

---

### 1.3 错误结果追加引导提示

**现状**：工具返回 `{"status": "error", "data": {"message": "..."}}` 时原样传给 LLM，LLM 可能重复相同调用。

**改造方案**：

```
改动文件：
└── app/core/agent_loop.py      ← 错误结果增强
```

**实现**：

```python
ERROR_HINT = "\n\n[工具执行出错。请分析错误原因，尝试不同的参数或方法。]"

def enhance_tool_result(result: dict) -> str:
    content = json.dumps(result, ensure_ascii=False)
    if result.get("status") == "error":
        content += ERROR_HINT
    return content
```

---

### 1.4 外部工具参数校验

**现状**：LLM 提供的参数直接传给工具脚本，无校验。如果 LLM 漏传 required 参数或类型错误，工具脚本自行报错。

**改造方案**：

```
改动文件：
├── app/core/tool_manager.py    ← 新增 validate_params() 方法
└── app/models/tool_def.py      ← ParameterDef 新增 validate() 方法
```

**校验规则**：

```python
def validate_params(self, tool_name: str, params: dict) -> list[str]:
    """校验参数，返回错误列表（空列表表示通过）。"""
    tool = self._tools.get(tool_name)
    if not tool:
        return [f"Tool not found: {tool_name}"]
    errors = []
    for pname, pdef in tool.parameters.items():
        if pdef.source != "ai":
            continue  # 非 AI 参数不校验
        if pdef.required and pname not in params:
            errors.append(f"缺少必需参数: {pname}")
            continue
        if pname in params:
            value = params[pname]
            # 类型校验
            type_ok = _check_type(value, pdef.type)
            if not type_ok:
                errors.append(f"参数 {pname} 类型错误: 期望 {pdef.type}, 实际 {type(value).__name__}")
            # enum 校验
            if pdef.enum and value not in pdef.enum:
                errors.append(f"参数 {pname} 值不在允许范围: {pdef.enum}")
    return errors
```

**校验失败处理**：不执行工具，直接返回错误结果给 LLM：

```python
errors = self._tm.validate_params(tool_name, ai_args)
if errors:
    result = {"status": "error", "data": {"message": "参数校验失败", "errors": errors}}
    # 跳过执行，直接构建 tool message
```

---

## Phase 2: 统一接口（小规模重构）

### 2.1 定义 Tool Protocol

**设计选择**：使用 `Protocol`（鸭子类型）而非 ABC，原因：
- 外部脚本工具无法继承 ABC（它们是独立进程）
- Protocol 更 Pythonic，不强制继承关系
- 内置工具和外部工具可以用不同的实现方式满足同一协议

```
新增文件：
└── app/core/tool_protocol.py   ← Tool Protocol 定义
```

```python
from typing import Any, Protocol, runtime_checkable

@runtime_checkable
class Tool(Protocol):
    """统一工具协议。所有工具（内置/外部/未来的 MCP）都满足此接口。"""

    @property
    def name(self) -> str: ...

    @property
    def description(self) -> str: ...

    @property
    def read_only(self) -> bool: ...

    @property
    def enabled(self) -> bool: ...

    def to_openai_function(self) -> dict: ...

    def execute(self, params: dict) -> dict: ...
```

---

### 2.2 将 BuiltinToolHandler 迁移为 Tool 实例

**现状**：
- 内置工具定义在 `BUILTIN_TOOLS` 列表（手写 OpenAI schema dict）
- 执行逻辑在 `BuiltinToolHandler` 类的各 `_handle_xxx` 方法中
- agent_loop 通过 `if tool_name in self._builtins` 分支判断

**改造方案**：

```
改动文件：
├── app/core/builtin_tools.py   ← 重构为多个 Tool 类
├── app/core/tool_manager.py    ← 统一注册内置工具
└── app/core/agent_loop.py      ← 移除 _builtins 分支，统一走 ToolManager
```

**内置工具拆分为独立类**：

```python
# app/core/builtin_tools.py

class CalculatorTool:
    """内置计算器工具。"""
    name = "calculator"
    description = "计算数学表达式，支持四则运算、幂次、三角函数等"
    read_only = True
    enabled = True

    _ALLOWED = {k: getattr(math, k) for k in dir(math) if not k.startswith("_")}
    _ALLOWED.update({"abs": abs, "round": round, ...})

    def to_openai_function(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "expression": {"type": "string", "description": "..."}
                    },
                    "required": ["expression"],
                },
            },
        }

    def execute(self, params: dict) -> dict:
        expr = params.get("expression", "").strip()
        if not expr:
            return {"status": "error", "data": {"message": "expression is required"}}
        try:
            result = eval(expr, {"__builtins__": {}}, self._ALLOWED)
            return {"status": "success", "data": {"expression": expr, "result": result}}
        except Exception as e:
            return {"status": "error", "data": {"message": str(e)}}
```

**内置工具列表**（每个一个类）：

| 类名 | 原方法 | read_only |
|------|--------|-----------|
| CalculatorTool | _handle_calculator | true |
| ClipboardTool | _handle_clipboard | false |
| CreateNoteTool | _handle_create_note | false |
| ReadNotesTool | _handle_read_notes | true |
| SummarizeSessionTool | _handle_summarize_as_note | false |
| CreateScheduledTaskTool | _handle_create_task | false |
| ListScheduledTasksTool | _handle_list_tasks | true |
| DeleteScheduledTaskTool | _handle_delete_task | false |

**依赖注入**：内置工具需要 `SchedulerManager`、`NoteManager` 等依赖。通过构造函数注入：

```python
class CreateNoteTool:
    def __init__(self, note_mgr: NoteManager, on_created: Callable):
        self._notes = note_mgr
        self._on_created = on_created
    ...
```

---

### 2.3 统一注册到 ToolManager

**现状**：
- 外部工具注册在 `ToolManager._tools: dict[str, ToolDefinition]`
- 内置工具注册在 `BuiltinToolHandler.get_handlers(): dict[str, Callable]`
- agent_loop 构造时接收两者，执行时分支判断

**改造方案**：

```python
# app/core/tool_manager.py

class ToolManager:
    def __init__(self):
        self._tools: dict[str, Tool] = {}  # 统一 registry
        self._deps = ToolDependencyManager()
        self._discover()

    def register(self, tool: Tool):
        """注册任意满足 Tool 协议的工具。"""
        self._tools[tool.name] = tool

    def unregister(self, name: str):
        self._tools.pop(name, None)

    def get_openai_functions(self) -> list[dict]:
        return [t.to_openai_function() for t in self._tools.values() if t.enabled]

    def execute(self, tool_name: str, params: dict) -> dict:
        tool = self._tools.get(tool_name)
        if not tool:
            return {"status": "error", "data": {"message": f"Tool not found: {tool_name}"}}
        return tool.execute(params)
```

**外部脚本工具包装**：

```python
class ScriptTool:
    """将 manifest.json + tool.py 包装为 Tool 协议实例。"""

    def __init__(self, definition: ToolDefinition, deps_mgr: ToolDependencyManager):
        self._def = definition
        self._deps = deps_mgr

    @property
    def name(self) -> str:
        return self._def.name

    @property
    def read_only(self) -> bool:
        return self._def.read_only  # 从 manifest.json 读取

    def execute(self, params: dict) -> dict:
        # 原 ToolManager._exec_subprocess 逻辑移到这里
        ...
```

---

### 2.4 agent_loop 分发逻辑简化

**现状**（`_state_execute` 中）：

```python
if tool_name in self._builtins:
    result = self._builtins[tool_name](resolved)
else:
    resolved = self._tm.resolve_params(tool_name, ai_args, manual_overrides)
    result = self._tm.execute(tool_name, resolved)
```

**改造后**：

```python
resolved = self._tm.resolve_params(tool_name, ai_args, manual_overrides)
result = self._tm.execute(tool_name, resolved)
```

- 移除 `builtin_handlers` 构造参数
- 移除 `self._builtins` 字典
- 所有工具统一走 `ToolManager.execute()`
- `resolve_params` 对内置工具直接返回原参数（无 config/manual 参数）

**AgentLoop 构造函数简化**：

```python
# Before
def __init__(self, ai_client, tool_manager, api_messages, tools,
             builtin_handlers, session_id, max_turns, parent):

# After
def __init__(self, ai_client, tool_manager, api_messages,
             session_id, max_turns, parent):
    # tools 列表从 tool_manager.get_openai_functions() 获取
    # builtin_handlers 不再需要
```

---

## 文件变更总览

### Phase 1（仅修改，不新增文件）

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `app/core/agent_loop.py` | 修改 | 并发执行 + 结果截断 + 错误增强 |
| `app/core/tool_manager.py` | 修改 | 新增 validate_params() |
| `app/models/tool_def.py` | 修改 | 新增 read_only 字段 |
| `tools/*/manifest.json` | 修改 | 新增 "read_only" 字段 |
| `app/core/config.py` | 修改 | 新增 maxToolResultChars 配置 |

### Phase 2（新增 1 文件，修改 3 文件）

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `app/core/tool_protocol.py` | **新增** | Tool Protocol 定义 |
| `app/core/builtin_tools.py` | **重写** | 拆分为独立 Tool 类 |
| `app/core/tool_manager.py` | **重写** | 统一 registry，register/execute |
| `app/core/agent_loop.py` | 修改 | 移除双轨分支，简化构造函数 |

---

## 风险评估

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| 并发执行时 tool_event 信号乱序 | UI 显示混乱 | 加锁或用 QueuedConnection |
| 并发执行时 checkpoint 不完整 | 崩溃恢复丢失部分结果 | 并发批次统一保存 |
| Phase 2 重构 builtin_tools 影响 UI 层 | 需要同步修改 main_window | 保持 ToolManager 对外接口不变 |
| 参数校验过严导致合法调用被拒 | LLM 体验下降 | 仅校验 required + type，不校验值范围 |

---
