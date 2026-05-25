# 工具模块架构对比分析

> 对比 assistant 项目与 nanobot 项目的工具系统实现，提取可借鉴的架构模式和代码实现。

## 1. 整体架构对比

| 维度 | assistant (当前项目) | nanobot |
|------|---------------------|---------|
| 工具定义方式 | manifest.json + tool.py 脚本 | Python 类继承 ABC |
| 执行模型 | 子进程隔离 (subprocess) | 异步 in-process (async/await) |
| 注册机制 | 目录扫描 + JSON 解析 | pkgutil 模块扫描 + entry_points 插件 |
| 参数校验 | 无显式校验，依赖 LLM 输出 | Schema 类型系统 + validate_value() |
| 并发控制 | 无（串行执行） | read_only/exclusive 标记 + 批次分区 |
| 作用域 | 无区分 | core/subagent/memory 多作用域 |
| 上下文注入 | 无 | ContextAware 协议 + contextvars |
| 结果处理 | 原样透传 JSON | 截断/持久化/错误提示增强 |
| 外部工具协议 | 自定义 stdin/stdout JSON | MCP (Model Context Protocol) |

---

## 2. 工具定义

### assistant 当前实现

```
tools/web_search/
├── manifest.json    ← 声明 name, description, parameters, dependencies
└── tool.py          ← stdin 读 JSON, stdout 写 JSON
```

- 优点：低门槛，非 Python 开发者也能写工具脚本；进程隔离安全
- 缺点：无类型约束，无基类契约，工具间无法共享状态或复用逻辑

### nanobot 实现

```python
class WebSearchTool(Tool):
    name = "web_search"
    description = "..."
    _scopes = {"core", "subagent"}

    @tool_parameters(tool_parameters_schema(
        query=StringSchema("搜索关键词"),
        max_results=IntegerSchema("最大结果数", minimum=1, maximum=20),
    ))
    class _: pass

    async def execute(self, **kwargs) -> str:
        ...
```

- 优点：强类型、IDE 补全、可测试、可组合
- 缺点：必须是 Python，与主进程耦合

---

## 3. 参数系统

### assistant

```python
@dataclass
class ParameterDef:
    name: str
    type: str           # "string" | "number" | "boolean" | "array" | "object"
    description: str
    source: str         # "config" | "ai" | "manual"
    required: bool
    default: Optional[str]
    enum: list
    items: Optional[dict]
```

**参数来源 (source)** 是 assistant 的独特设计：
- `ai`：暴露给 LLM，由模型填充
- `config`：从应用配置注入（如 API key），对 LLM 隐藏
- `manual`：运行时弹出 UI 让用户手动输入

**解析优先级**：manual > ai > config > default

### nanobot

```python
class StringSchema(Schema):
    def __init__(self, description, min_length=None, max_length=None, enum=None, nullable=False): ...
    def to_json_schema(self) -> dict: ...
    def validate_value(self, value, path="") -> list[str]: ...
```

- 提供 String/Integer/Number/Boolean/Array/Object 六种具体 Schema 类
- 每种都有 `validate_value()` 方法，在执行前校验参数合法性
- `@tool_parameters` 装饰器自动注入 `parameters` 属性

### 可借鉴点

1. **参数校验层**：nanobot 的 Schema 校验可以在调用工具前拦截非法参数，减少无效执行
2. **assistant 的 source 机制更灵活**：nanobot 没有等价的参数来源分离，所有参数都由 LLM 提供

---

## 4. 注册与发现

### assistant

```python
class ToolManager:
    def _discover(self):
        self._discover_dir(TOOLS_DIR, is_builtin=True)      # tools/
        self._discover_dir(USER_TOOLS_DIR, is_builtin=False) # data/user_tools/
```

- 扫描固定目录，查找 `manifest.json`
- 内置工具始终启用，用户工具可开关
- `reload()` 清空重新扫描

### nanobot

```python
class ToolLoader:
    def discover(self):
        # pkgutil.iter_modules 扫描 nanobot.agent.tools 包
        # 收集所有 Tool 子类（_plugin_discoverable=True）

    def _discover_plugins(self):
        # entry_points("nanobot.tools") 加载外部插件

    def load(self, ctx, registry, scope="core"):
        # 过滤 scope → enabled(ctx) → create(ctx) → register
```

- 基于 Python 模块系统自动发现
- 支持 entry_points 外部插件扩展
- 工厂方法 `create(ctx)` 允许依赖注入
- `enabled(ctx)` 条件注册（根据配置决定是否加载）

### 可借鉴点

1. **条件注册**：`enabled(ctx)` 模式比当前的全量加载 + 运行时 enabled 标记更高效
2. **工厂方法**：`create(ctx)` 允许工具在创建时获取所需依赖，比当前的无状态脚本更灵活
3. **插件系统**：entry_points 机制允许第三方包注册工具，扩展性更强

---

## 5. 执行模型

### assistant

```python
def _exec_subprocess(self, tool, params):
    result = subprocess.run(
        [sys.executable, tool.script_path],
        input=json.dumps({"params": params, "context": {}}),
        capture_output=True, text=True, timeout=60,
        env=env,  # 隔离的 PYTHONPATH
    )
    last_line = result.stdout.splitlines()[-1]
    return json.loads(last_line)
```

- 进程隔离：工具崩溃不影响主进程
- 依赖隔离：独立 site-packages
- 同步阻塞：一次只能执行一个工具

### nanobot

```python
# runner.py
async def _execute_tools(self, tool_calls):
    batches = self._partition_tool_batches(tool_calls)
    for batch in batches:
        if batch.concurrent:
            results = await asyncio.gather(*[self._run_tool(c) for c in batch.calls])
        else:
            for call in batch.calls:
                await self._run_tool(call)
```

- 异步执行：不阻塞事件循环
- 并发批次：`read_only` 工具可并行，`exclusive` 工具串行
- 结果增强：截断过长结果、持久化大结果、错误提示追加建议

### 可借鉴点

1. **并发执行**：多个只读工具（如 web_search + read_file）可以并行，显著减少等待时间
2. **结果截断/持久化**：防止超长工具输出撑爆上下文窗口
3. **错误提示增强**：自动追加 "分析错误并尝试不同方法" 引导 LLM 自我修正

---

## 6. 并发安全

### assistant

无并发机制。所有工具串行执行，一次只处理一个 tool_call。

### nanobot

```python
class Tool(ABC):
    read_only: bool = False       # 无副作用，可并行
    exclusive: bool = False       # 必须独占执行

    @property
    def concurrency_safe(self) -> bool:
        return self.read_only and not self.exclusive
```

批次分区算法：
1. 连续的 `concurrency_safe` 工具合并为一个并发批次
2. 非安全工具单独成为串行批次
3. 按顺序执行各批次

### 可借鉴点

assistant 的子进程模型天然隔离，引入并发执行的成本较低：
- 标记 `read_file`、`web_search`、`fetch_url` 为只读
- 用 `concurrent.futures.ThreadPoolExecutor` 并行执行子进程
- 保持 `save_file`、`run_python` 等有副作用工具串行

---

## 7. 上下文与状态

### assistant

工具脚本是无状态的。每次执行都是全新进程，通过 stdin 传入所有需要的参数。

### nanobot

```python
class ToolContext:
    config: AgentConfig
    workspace: Path
    bus: EventBus
    ...

class ContextAware(Protocol):
    def set_context(self, ctx: RequestContext) -> None: ...
```

- `ToolContext`：创建时注入，包含配置、工作区路径、事件总线
- `RequestContext`：每次请求注入，包含 channel、chat_id、message_id
- 使用 `contextvars.ContextVar` 保证并发安全

### 可借鉴点

assistant 的无状态模型对简单工具足够，但对需要访问应用状态的工具（如 scheduler、notes）不得不走内置工具路径。可以考虑：
- 为内置工具引入轻量 Context 对象，统一依赖注入
- 保持外部工具的子进程隔离不变

---

## 8. 内置工具 vs 外部工具

### assistant 的双轨制

| 类型 | 定义位置 | 执行方式 | 特点 |
|------|---------|---------|------|
| 内置工具 | `builtin_tools.py` | in-process 函数调用 | 可访问应用状态 |
| 外部工具 | `tools/` + `data/user_tools/` | subprocess | 隔离但无状态 |

内置工具的 schema 是手写的 OpenAI function dict，与外部工具的 `ToolDefinition.to_openai_function()` 输出格式相同，但定义方式完全不同。

### nanobot 的统一模型

所有工具（包括 MCP 包装器）都实现同一个 `Tool` ABC，注册到同一个 `ToolRegistry`。没有 "内置" vs "外部" 的区分——只有作用域 (`_scopes`) 和是否可发现 (`_plugin_discoverable`) 的差异。

### 可借鉴点

1. **统一接口**：将内置工具也包装为 `ToolDefinition`（或新的 Tool 基类），消除双轨制
2. **统一注册**：所有工具进入同一个 registry，简化 agent_loop 的分发逻辑

---

## 9. MCP 协议支持

### assistant

无 MCP 支持。外部工具使用自定义的 stdin/stdout JSON 协议。

### nanobot

```python
class MCPToolWrapper(Tool):
    """将 MCP server 暴露的 tool 包装为本地 Tool 实例"""
    async def execute(self, **kwargs):
        return await self._session.call_tool(self._mcp_name, kwargs)

async def connect_mcp_servers(config, registry):
    for server_cfg in config.mcp_servers:
        session = await connect(server_cfg)
        for tool in session.list_tools():
            registry.register(MCPToolWrapper(session, tool))
```

### 可借鉴点

MCP 是 Anthropic 推动的标准协议，未来生态会越来越丰富。assistant 可以：
1. 添加 MCP client 支持，连接外部 MCP server
2. 将现有的 stdin/stdout 协议工具包装为 MCP server，实现双向兼容

---

## 10. 工具生成

### assistant 独有

```python
class ToolGenerator:
    """AI 驱动的工具脚本生成器"""
    def generate(self, requirement: str, model: str) -> tuple[dict, str]:
        # 调用 LLM 生成 manifest.json + tool.py
        ...
```

nanobot 没有等价功能。这是 assistant 的差异化优势——用户可以用自然语言描述需求，自动生成工具。

---

## 11. 重构建议优先级

基于对比分析，以下是按投入产出比排序的重构建议：

### P0 - 高价值低成本

| 建议 | 预期收益 | 实现复杂度 |
|------|---------|-----------|
| 工具并发执行 | 多工具调用时延降低 50%+ | 低（ThreadPoolExecutor） |
| 结果截断/大小限制 | 防止上下文溢出 | 低（加一个 max_chars 检查） |
| 错误结果增强 | LLM 自我修正率提升 | 低（字符串追加） |

### P1 - 高价值中等成本

| 建议 | 预期收益 | 实现复杂度 |
|------|---------|-----------|
| 统一 Tool 接口 | 消除双轨制，简化分发 | 中（需重构 builtin_tools） |
| 参数校验层 | 减少无效执行，提升可靠性 | 中（Schema 类 + validate） |
| 条件注册 | 按需加载，启动更快 | 低-中 |

### P2 - 长期演进

| 建议 | 预期收益 | 实现复杂度 |
|------|---------|-----------|
| MCP 协议支持 | 接入标准生态 | 高（需 MCP client 实现） |
| 作用域系统 | 子 agent 工具隔离 | 中（需 agent 架构支持） |
| 插件系统 (entry_points) | 第三方扩展 | 中 |

---

## 12. 推荐重构路径

```
Phase 1: 快速增强（不改架构）
├── 添加工具并发执行（ThreadPoolExecutor）
├── 添加结果大小限制和截断
├── 错误结果追加引导提示
└── 为外部工具添加参数校验

Phase 2: 统一接口（小规模重构）
├── 定义 Tool ABC 或 Protocol
├── 将 BuiltinToolHandler 中的工具迁移为 Tool 实例
├── 统一注册到 ToolManager
└── agent_loop 分发逻辑简化

Phase 3: 生态扩展（架构演进）
├── 添加 MCP client 支持
├── 引入作用域系统
└── 支持 entry_points 插件发现
```

---

## 13. 代码示例：统一 Tool 接口（Phase 2 草案）

```python
from abc import ABC, abstractmethod
from typing import Any, Optional

class Tool(ABC):
    """统一工具基类，合并内置工具和外部工具的接口。"""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def description(self) -> str: ...

    @property
    @abstractmethod
    def parameters(self) -> dict[str, Any]: ...

    @abstractmethod
    async def execute(self, **kwargs: Any) -> dict: ...

    @property
    def read_only(self) -> bool:
        """无副作用的工具可并行执行。"""
        return False

    def to_openai_function(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class SubprocessTool(Tool):
    """外部脚本工具，保持子进程隔离执行。"""

    def __init__(self, definition: ToolDefinition):
        self._def = definition

    @property
    def name(self) -> str:
        return self._def.name

    # ... 其余属性委托给 ToolDefinition

    async def execute(self, **kwargs) -> dict:
        # 在线程池中执行子进程
        return await asyncio.to_thread(tool_manager._exec_subprocess, self._def, kwargs)


class CalculatorTool(Tool):
    """内置计算器工具，直接 in-process 执行。"""
    name = "calculator"
    description = "计算数学表达式"
    read_only = True
    # ...
```

---
