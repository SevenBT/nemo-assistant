# 工具系统重新设计方案

> 推翻现有双轨架构，统一为 ABC 基类 + ToolContext 注入 + 自动发现。
> 外部脚本工具仅保留为用户自定义扩展机制。

## 设计目标

1. 所有内置工具（含从外部脚本迁移的）统一为 Python 类，in-process 执行
2. 基类提供 `to_openai_function()` 自动生成、`cast_params()` 类型转换
3. 统一 `ToolContext` 注入共享资源，新增工具只需继承基类
4. 外部脚本工具保留为用户扩展机制，通过适配器满足同一基类接口
5. 20+ 工具规模下保持清晰的组织结构

---

## 架构总览

```
app/tools/                          ← 新目录：所有内置工具
├── __init__.py                     ← 导出 BUILTIN_TOOL_CLASSES 列表
├── base.py                         ← BuiltinTool ABC + cast_params
├── schema.py                       ← Schema DSL (Str, Int, Bool, Arr, Obj)
├── context.py                      ← ToolContext 数据类
├── registry.py                     ← ToolRegistry（统一注册中心）
├── loader.py                       ← 自动发现 + 注册逻辑
├── script_adapter.py               ← 外部脚本适配器（替代原 ScriptTool）
│
├── calculator.py                   ← CalculatorTool
├── clipboard.py                    ← ClipboardTool
├── note_create.py                  ← CreateNoteTool
├── note_read.py                    ← ReadNotesTool
├── note_summarize.py               ← SummarizeSessionTool
├── scheduler_create.py             ← CreateScheduledTaskTool
├── scheduler_list.py               ← ListScheduledTasksTool
├── scheduler_delete.py             ← DeleteScheduledTaskTool
├── web_search.py                   ← WebSearchTool（从外部脚本迁移）
├── fetch_url.py                    ← FetchUrlTool（从外部脚本迁移）
├── read_file.py                    ← ReadFileTool（从外部脚本迁移）
├── save_file.py                    ← SaveFileTool（从外部脚本迁移）
├── run_python.py                   ← RunPythonTool（从外部脚本迁移）
├── reminder.py                     ← ReminderTool（从外部脚本迁移）
└── multi_model_consult.py          ← MultiModelConsultTool（从外部脚本迁移）

data/user_tools/                    ← 用户自定义工具（保留 manifest.json + tool.py 形式）
├── my_tool/
│   ├── manifest.json
│   └── tool.py

app/core/
├── tool_manager.py                 ← 精简：只保留对外接口，内部委托 ToolRegistry
└── tool_deps.py                    ← 保留：用户工具依赖管理
```

**删除的文件**：
- `app/core/tool_protocol.py` — 被 `app/tools/base.py` 的 ABC 替代
- `app/core/builtin_tools.py` — 拆分到 `app/tools/` 各文件
- `app/models/tool_def.py` — 仅用于用户脚本工具，移入 `script_adapter.py`
- `tools/` 目录下的内置脚本工具 — 迁移为 in-process 类

---

## 核心模块设计

### 1. base.py — 工具基类

```python
"""工具基类。所有内置工具继承此类。"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from app.tools.context import ToolContext

# JSON Schema 类型到 Python 类型的映射
_TYPE_MAP: dict[str, type | tuple[type, ...]] = {
    "string": str,
    "number": (int, float),
    "integer": int,
    "boolean": bool,
    "array": list,
    "object": dict,
}

_BOOL_TRUE = frozenset(("true", "1", "yes"))
_BOOL_FALSE = frozenset(("false", "0", "no"))


class BuiltinTool(ABC):
    """内置工具抽象基类。"""

    # ── 子类必须定义 ──────────────────────────────────────────────────────

    @property
    @abstractmethod
    def name(self) -> str:
        """工具唯一标识名。"""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """工具描述，暴露给 LLM。"""
        ...

    @property
    @abstractmethod
    def parameters(self) -> dict[str, Any]:
        """JSON Schema 参数定义（type: object 层级）。"""
        ...

    @abstractmethod
    def execute(self, params: dict[str, Any]) -> dict[str, Any]:
        """
        执行工具。

        Returns:
            {"status": "success"|"error", "data": {...}}
        """
        ...

    # ── 子类可选覆盖 ──────────────────────────────────────────────────────

    @property
    def read_only(self) -> bool:
        """无副作用，可并发执行。默认 False。"""
        return False

    @property
    def enabled(self) -> bool:
        """是否启用。默认 True。"""
        return True

    @classmethod
    def create(cls, ctx: "ToolContext") -> "BuiltinTool":
        """工厂方法。需要依赖注入的工具覆盖此方法。"""
        return cls()

    # ── 基类提供 ──────────────────────────────────────────────────────────

    def to_openai_function(self) -> dict[str, Any]:
        """自动生成 OpenAI function calling schema。子类无需覆盖。"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def cast_params(self, params: dict[str, Any]) -> dict[str, Any]:
        """根据 parameters schema 做类型转换，容忍 LLM 传错类型。"""
        schema = self.parameters
        if schema.get("type") != "object":
            return params
        properties = schema.get("properties", {})
        result = {}
        for key, value in params.items():
            if key in properties:
                result[key] = self._cast_value(value, properties[key])
            else:
                result[key] = value
        return result

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        """校验参数，返回错误列表（空 = 通过）。"""
        schema = self.parameters
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        errors = []
        for name in required:
            if name not in params:
                errors.append(f"缺少必需参数: {name}")
        for key, value in params.items():
            if key in properties:
                prop_schema = properties[key]
                expected_type = prop_schema.get("type")
                if expected_type and not self._check_type(value, expected_type):
                    errors.append(
                        f"参数 {key} 类型错误: 期望 {expected_type}, "
                        f"实际 {type(value).__name__}"
                    )
                if "enum" in prop_schema and value not in prop_schema["enum"]:
                    errors.append(f"参数 {key} 值不在允许范围: {prop_schema['enum']}")
        return errors

    # ── 私有方法 ──────────────────────────────────────────────────────────

    @staticmethod
    def _check_type(value: Any, expected: str) -> bool:
        if value is None:
            return True
        py_type = _TYPE_MAP.get(expected)
        if py_type is None:
            return True
        return isinstance(value, py_type)

    @staticmethod
    def _cast_value(value: Any, prop_schema: dict[str, Any]) -> Any:
        """单个值的类型转换。"""
        target_type = prop_schema.get("type")
        if target_type is None or value is None:
            return value

        # 已经是正确类型
        if target_type == "boolean" and isinstance(value, bool):
            return value
        if target_type == "integer" and isinstance(value, int) and not isinstance(value, bool):
            return value
        if target_type == "number" and isinstance(value, (int, float)) and not isinstance(value, bool):
            return value
        if target_type == "string" and isinstance(value, str):
            return value

        # 字符串 → 数字
        if isinstance(value, str) and target_type in ("integer", "number"):
            try:
                return int(value) if target_type == "integer" else float(value)
            except ValueError:
                return value

        # 字符串 → 布尔
        if isinstance(value, str) and target_type == "boolean":
            low = value.lower()
            if low in _BOOL_TRUE:
                return True
            if low in _BOOL_FALSE:
                return False
            return value

        # 任意 → 字符串
        if target_type == "string" and not isinstance(value, str):
            return str(value)

        # 数组元素递归转换
        if target_type == "array" and isinstance(value, list):
            items_schema = prop_schema.get("items")
            if items_schema:
                return [BuiltinTool._cast_value(item, items_schema) for item in value]

        return value
```

### 2. schema.py — Schema DSL

```python
"""轻量 Schema DSL，减少手写 JSON Schema dict 的出错率。"""
from typing import Any


class _Schema:
    """Schema 片段基类。"""
    def to_dict(self) -> dict[str, Any]:
        raise NotImplementedError


class Str(_Schema):
    def __init__(self, description: str = "", *, enum: list[str] | None = None):
        self._desc = description
        self._enum = enum

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"type": "string"}
        if self._desc:
            d["description"] = self._desc
        if self._enum:
            d["enum"] = self._enum
        return d


class Int(_Schema):
    def __init__(self, description: str = "", *, minimum: int | None = None, maximum: int | None = None):
        self._desc = description
        self._min = minimum
        self._max = maximum

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"type": "integer"}
        if self._desc:
            d["description"] = self._desc
        if self._min is not None:
            d["minimum"] = self._min
        if self._max is not None:
            d["maximum"] = self._max
        return d


class Num(_Schema):
    def __init__(self, description: str = ""):
        self._desc = description

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"type": "number"}
        if self._desc:
            d["description"] = self._desc
        return d


class Bool(_Schema):
    def __init__(self, description: str = ""):
        self._desc = description

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"type": "boolean"}
        if self._desc:
            d["description"] = self._desc
        return d


class Arr(_Schema):
    def __init__(self, items: _Schema | dict, description: str = ""):
        self._items = items
        self._desc = description

    def to_dict(self) -> dict[str, Any]:
        items = self._items.to_dict() if isinstance(self._items, _Schema) else self._items
        d: dict[str, Any] = {"type": "array", "items": items}
        if self._desc:
            d["description"] = self._desc
        return d


class Obj(_Schema):
    def __init__(self, description: str = "", **properties: _Schema | dict):
        self._desc = description
        self._props = properties

    def to_dict(self) -> dict[str, Any]:
        props = {
            k: (v.to_dict() if isinstance(v, _Schema) else v)
            for k, v in self._props.items()
        }
        d: dict[str, Any] = {"type": "object", "properties": props}
        if self._desc:
            d["description"] = self._desc
        return d


def tool_params(*required: str, **properties: _Schema | dict) -> dict[str, Any]:
    """
    构建工具 parameters schema。

    用法:
        parameters = tool_params(
            "query",  # required 参数名
            query=Str("搜索关键词"),
            count=Int("结果数量", maximum=10),
        )
    """
    props = {
        k: (v.to_dict() if isinstance(v, _Schema) else v)
        for k, v in properties.items()
    }
    schema: dict[str, Any] = {"type": "object", "properties": props}
    if required:
        schema["required"] = list(required)
    return schema
```

### 3. context.py — ToolContext

```python
"""工具上下文 — 所有内置工具共享的资源容器。"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.ai_client import AIClient
    from app.core.config import QConfig
    from app.core.note_manager import NoteManager
    from app.core.scheduler import SchedulerManager


@dataclass
class ToolContext:
    """
    统一上下文，通过工厂方法 create() 注入到每个内置工具。

    新增共享资源只需在此添加字段，不影响已有工具。
    工具按需使用，不用的字段忽略即可。
    """
    # 核心
    config: Any                                  # QConfig 实例
    workspace: Path                              # 工作目录

    # 管理器
    note_mgr: "NoteManager | None" = None
    scheduler: "SchedulerManager | None" = None
    ai_client: "AIClient | None" = None

    # 回调
    on_note_created: Callable[[], None] | None = None

    # 网络
    http_timeout: int = 30
    proxy: str | None = None

    # 扩展字段（未来按需添加）
    extra: dict[str, Any] = field(default_factory=dict)
```

### 4. registry.py — ToolRegistry

```python
"""统一工具注册中心。"""
from __future__ import annotations

import json
import logging
from typing import Any

from app.tools.base import BuiltinTool

logger = logging.getLogger(__name__)

_MAX_RESULT_CHARS = 8000
_ERROR_HINT = "\n\n[工具执行出错。请分析错误原因，尝试不同的参数或方法。]"


class ToolRegistry:
    """管理所有工具的注册、查询、校验、执行。"""

    def __init__(self):
        self._tools: dict[str, BuiltinTool] = {}

    # ── 注册 ──────────────────────────────────────────────────────────────

    def register(self, tool: BuiltinTool) -> None:
        self._tools[tool.name] = tool
        logger.info("[Registry] Registered: %s (read_only=%s)", tool.name, tool.read_only)

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)

    # ── 查询 ──────────────────────────────────────────────────────────────

    def get(self, name: str) -> BuiltinTool | None:
        return self._tools.get(name)

    def get_all(self) -> list[BuiltinTool]:
        return list(self._tools.values())

    def get_enabled(self) -> list[BuiltinTool]:
        return [t for t in self._tools.values() if t.enabled]

    def get_openai_functions(self) -> list[dict[str, Any]]:
        return [t.to_openai_function() for t in self._tools.values() if t.enabled]

    @property
    def tool_names(self) -> list[str]:
        return list(self._tools.keys())

    # ── 执行 ──────────────────────────────────────────────────────────────

    def execute(self, name: str, params: dict[str, Any]) -> dict[str, Any]:
        """执行工具：cast → validate → execute。"""
        tool = self._tools.get(name)
        if not tool:
            return {"status": "error", "data": {"message": f"Tool not found: {name}"}}

        # 类型转换
        params = tool.cast_params(params)

        # 参数校验
        errors = tool.validate_params(params)
        if errors:
            return {"status": "error", "data": {"message": "参数校验失败", "errors": errors}}

        # 执行
        try:
            return tool.execute(params)
        except Exception as e:
            logger.exception("[Registry] Tool %s execution error", name)
            return {"status": "error", "data": {"message": str(e)}}

    # ── 结果格式化 ────────────────────────────────────────────────────────

    @staticmethod
    def format_result(result: dict[str, Any]) -> str:
        """格式化工具结果：错误增强 + 截断。"""
        content = json.dumps(result, ensure_ascii=False)
        if result.get("status") == "error":
            content += _ERROR_HINT
        if len(content) > _MAX_RESULT_CHARS:
            content = content[:_MAX_RESULT_CHARS]
            content += f"\n\n[结果已截断，显示前 {_MAX_RESULT_CHARS} 字符]"
        return content
```

### 5. loader.py — 自动发现与注册

```python
"""工具发现与注册。"""
from __future__ import annotations

import importlib
import logging
import pkgutil
from pathlib import Path
from typing import Any

from app.tools.base import BuiltinTool
from app.tools.context import ToolContext
from app.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

# 非工具模块，跳过扫描
_SKIP_MODULES = frozenset({
    "base", "schema", "context", "registry", "loader",
    "script_adapter", "__init__",
})


def discover_builtin_tools() -> list[type[BuiltinTool]]:
    """扫描 app/tools/ 包，找到所有 BuiltinTool 子类。"""
    import app.tools as _pkg

    results: list[type[BuiltinTool]] = []
    seen: set[int] = set()

    for _importer, module_name, _ispkg in pkgutil.iter_modules(_pkg.__path__):
        if module_name in _SKIP_MODULES or module_name.startswith("_"):
            continue
        try:
            module = importlib.import_module(f".{module_name}", _pkg.__name__)
        except Exception:
            logger.exception("Failed to import tool module: %s", module_name)
            continue

        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if (
                isinstance(attr, type)
                and issubclass(attr, BuiltinTool)
                and attr is not BuiltinTool
                and not getattr(attr, "__abstractmethods__", None)
                and id(attr) not in seen
            ):
                seen.add(id(attr))
                results.append(attr)

    results.sort(key=lambda cls: cls.__name__)
    return results


def load_builtin_tools(ctx: ToolContext, registry: ToolRegistry) -> list[str]:
    """发现并注册所有内置工具，返回已注册的工具名列表。"""
    registered: list[str] = []
    for tool_cls in discover_builtin_tools():
        try:
            tool = tool_cls.create(ctx)
            registry.register(tool)
            registered.append(tool.name)
        except Exception:
            logger.exception("Failed to create tool: %s", tool_cls.__name__)
    return registered


def load_user_script_tools(
    user_tools_dir: Path,
    registry: ToolRegistry,
) -> list[str]:
    """扫描用户工具目录，注册外部脚本工具。"""
    from app.tools.script_adapter import ScriptToolAdapter

    registered: list[str] = []
    if not user_tools_dir.exists():
        return registered

    for tool_dir in user_tools_dir.iterdir():
        if not tool_dir.is_dir():
            continue
        manifest_path = tool_dir / "manifest.json"
        if not manifest_path.exists():
            continue
        try:
            adapter = ScriptToolAdapter.from_manifest(manifest_path)
            registry.register(adapter)
            registered.append(adapter.name)
        except Exception:
            logger.warning("Skip user tool: %s", tool_dir.name, exc_info=True)

    return registered
```

### 6. script_adapter.py — 外部脚本适配器

```python
"""将用户自定义脚本工具适配为 BuiltinTool 接口。"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from app.tools.base import BuiltinTool

_TOOL_TIMEOUT = 60


class ScriptToolAdapter(BuiltinTool):
    """
    将 manifest.json + tool.py 包装为 BuiltinTool。

    保留子进程隔离执行，用户工具崩溃不影响主进程。
    """

    def __init__(
        self,
        tool_name: str,
        tool_description: str,
        tool_parameters: dict[str, Any],
        script_path: str,
        tool_dir: str,
        is_read_only: bool = False,
        dependencies: list[str] | None = None,
    ):
        self._name = tool_name
        self._description = tool_description
        self._parameters = tool_parameters
        self._script_path = script_path
        self._tool_dir = tool_dir
        self._read_only = is_read_only
        self._dependencies = dependencies or []
        self._enabled = True

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @property
    def parameters(self) -> dict[str, Any]:
        return self._parameters

    @property
    def read_only(self) -> bool:
        return self._read_only

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool):
        self._enabled = value

    def execute(self, params: dict[str, Any]) -> dict[str, Any]:
        stdin_payload = json.dumps({"params": params, "context": {}}, ensure_ascii=False)
        env = os.environ.copy()

        try:
            result = subprocess.run(
                [sys.executable, self._script_path],
                input=stdin_payload,
                capture_output=True,
                text=True,
                timeout=_TOOL_TIMEOUT,
                env=env,
                cwd=self._tool_dir,
            )
        except subprocess.TimeoutExpired:
            return {"status": "error", "data": {"message": f"执行超时 ({_TOOL_TIMEOUT}s)"}}
        except Exception as e:
            return {"status": "error", "data": {"message": str(e)}}

        stdout = result.stdout.strip()
        stderr = result.stderr.strip()

        if result.returncode != 0 and not stdout:
            return {"status": "error", "data": {"message": stderr or f"Exit code {result.returncode}"}}

        if not stdout:
            return {"status": "success", "data": {}}

        last_line = stdout.splitlines()[-1]
        try:
            parsed = json.loads(last_line)
            return parsed
        except json.JSONDecodeError as e:
            return {"status": "error", "data": {"message": f"Invalid JSON: {e}", "raw": stdout[-500:]}}

    @classmethod
    def from_manifest(cls, manifest_path: Path) -> "ScriptToolAdapter":
        """从 manifest.json 构建适配器实例。"""
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)

        tool_dir = manifest_path.parent
        script_path = str(tool_dir / manifest.get("script", "tool.py"))

        # 构建 parameters schema（只暴露 source=ai 的参数给 LLM）
        properties = {}
        required = []
        for pname, pdata in manifest.get("parameters", {}).items():
            if pdata.get("source") == "config":
                continue
            prop: dict[str, Any] = {"type": pdata.get("type", "string")}
            if pdata.get("description"):
                prop["description"] = pdata["description"]
            if pdata.get("enum"):
                prop["enum"] = pdata["enum"]
            if pdata.get("items"):
                prop["items"] = pdata["items"]
            properties[pname] = prop
            if pdata.get("required", True):
                required.append(pname)

        parameters: dict[str, Any] = {"type": "object", "properties": properties}
        if required:
            parameters["required"] = required

        return cls(
            tool_name=manifest["name"],
            tool_description=manifest["description"],
            tool_parameters=parameters,
            script_path=script_path,
            tool_dir=str(tool_dir),
            is_read_only=manifest.get("read_only", False),
            dependencies=manifest.get("dependencies", []),
        )
```

---

## 内置工具示例

### calculator.py（最简单的工具）

```python
"""计算器工具 — 无依赖注入的最简示例。"""
from typing import Any

from app.tools.base import BuiltinTool
from app.tools.schema import Str, tool_params


class CalculatorTool(BuiltinTool):

    @property
    def name(self) -> str:
        return "calculator"

    @property
    def description(self) -> str:
        return "计算数学表达式，支持基本运算和数学函数"

    @property
    def parameters(self) -> dict[str, Any]:
        return tool_params(
            "expression",
            expression=Str("数学表达式，如 '2+3*4' 或 'sqrt(16)'"),
        )

    @property
    def read_only(self) -> bool:
        return True

    def execute(self, params: dict[str, Any]) -> dict[str, Any]:
        import math
        expression = params["expression"]
        allowed = {k: getattr(math, k) for k in dir(math) if not k.startswith("_")}
        allowed.update({"abs": abs, "round": round, "min": min, "max": max})
        try:
            result = eval(expression, {"__builtins__": {}}, allowed)
            return {"status": "success", "data": {"result": result}}
        except Exception as e:
            return {"status": "error", "data": {"message": f"计算错误: {e}"}}
```

### note_create.py（需要 ToolContext 依赖注入）

```python
"""创建笔记工具 — 展示 ToolContext 依赖注入模式。"""
from __future__ import annotations

from typing import Any, TYPE_CHECKING

from app.tools.base import BuiltinTool
from app.tools.schema import Str, tool_params

if TYPE_CHECKING:
    from app.tools.context import ToolContext
    from app.core.note_manager import NoteManager


class CreateNoteTool(BuiltinTool):

    def __init__(self, note_mgr: "NoteManager", on_created=None):
        self._note_mgr = note_mgr
        self._on_created = on_created

    @classmethod
    def create(cls, ctx: "ToolContext") -> "CreateNoteTool":
        """从 ToolContext 提取所需依赖。"""
        return cls(note_mgr=ctx.note_mgr, on_created=ctx.on_note_created)

    @property
    def name(self) -> str:
        return "create_note"

    @property
    def description(self) -> str:
        return "创建一条笔记"

    @property
    def parameters(self) -> dict[str, Any]:
        return tool_params(
            "title", "content",
            title=Str("笔记标题"),
            content=Str("笔记内容"),
        )

    def execute(self, params: dict[str, Any]) -> dict[str, Any]:
        title = params["title"]
        content = params["content"]
        note_id = self._note_mgr.create_note(title=title, content=content)
        if self._on_created:
            self._on_created()
        return {"status": "success", "data": {"note_id": note_id, "title": title}}
```

### web_search.py（从外部脚本迁移为 in-process）

```python
"""网页搜索工具 — 展示从外部脚本迁移后的形态。"""
from __future__ import annotations

from typing import Any, TYPE_CHECKING

import requests

from app.tools.base import BuiltinTool
from app.tools.schema import Int, Str, tool_params

if TYPE_CHECKING:
    from app.tools.context import ToolContext


class WebSearchTool(BuiltinTool):

    def __init__(self, api_key: str, timeout: int = 30, proxy: str | None = None):
        self._api_key = api_key
        self._timeout = timeout
        self._proxy = proxy

    @classmethod
    def create(cls, ctx: "ToolContext") -> "WebSearchTool":
        api_key = ctx.config.get("tavily_api_key", "")
        return cls(api_key=api_key, timeout=ctx.http_timeout, proxy=ctx.proxy)

    @property
    def name(self) -> str:
        return "web_search"

    @property
    def description(self) -> str:
        return "搜索互联网获取最新信息"

    @property
    def parameters(self) -> dict[str, Any]:
        return tool_params(
            "query",
            query=Str("搜索关键词"),
            count=Int("返回结果数量", minimum=1, maximum=10),
        )

    @property
    def read_only(self) -> bool:
        return True

    @property
    def enabled(self) -> bool:
        return bool(self._api_key)

    def execute(self, params: dict[str, Any]) -> dict[str, Any]:
        query = params["query"]
        count = params.get("count", 5)
        proxies = {"https": self._proxy} if self._proxy else None

        try:
            resp = requests.post(
                "https://api.tavily.com/search",
                json={"api_key": self._api_key, "query": query, "max_results": count},
                timeout=self._timeout,
                proxies=proxies,
            )
            resp.raise_for_status()
            data = resp.json()
            results = [
                {"title": r["title"], "url": r["url"], "content": r["content"]}
                for r in data.get("results", [])
            ]
            return {"status": "success", "data": {"results": results}}
        except Exception as e:
            return {"status": "error", "data": {"message": str(e)}}
```

---

## Agent Loop 集成

### 改动前（当前 `_state_execute` 核心逻辑）

```python
# app/core/agent_loop.py 中的工具执行
def _execute_one(self, call):
    tool_name = call["function"]["name"]
    params = json.loads(call["function"]["arguments"])
    # 需要区分内置/外部，手动路由
    if tool_name in self._builtin_tools:
        result = self._builtin_tools[tool_name].execute(params)
    else:
        result = self._tool_manager.execute_script_tool(tool_name, params)
    return result
```

### 改动后

```python
# app/core/agent_loop.py — 统一通过 registry 执行
def _execute_one(self, call):
    tool_name = call["function"]["name"]
    params = json.loads(call["function"]["arguments"])
    result = self._registry.execute(tool_name, params)
    return result
```

**变化要点**：
1. 删除 `_builtin_tools` 字典和手动路由逻辑
2. `_tool_manager` 精简为只负责用户工具的依赖安装
3. `_partition_batches()` 直接用 `tool.read_only` 判断并发安全性
4. 工具列表获取：`self._registry.get_openai_functions()` 替代手动拼接

### 并发批次判断简化

```python
def _partition_batches(self, tool_calls: list) -> list[list]:
    """将工具调用分为可并发批次。"""
    batches = []
    current_batch = []
    for call in tool_calls:
        name = call["function"]["name"]
        tool = self._registry.get(name)
        if tool and tool.read_only:
            current_batch.append(call)
        else:
            if current_batch:
                batches.append(current_batch)
                current_batch = []
            batches.append([call])  # 有副作用的工具单独执行
    if current_batch:
        batches.append(current_batch)
    return batches
```

---

## MainWindow 初始化改动

### 改动前

```python
# app/ui/main_window.py
def _register_builtin_tools(self):
    self.builtin_tools = {}
    calc = CalculatorTool()
    self.builtin_tools["calculator"] = calc
    clip = ClipboardTool()
    self.builtin_tools["clipboard"] = clip
    # ... 逐个手动注册 8 个工具
```

### 改动后

```python
# app/ui/main_window.py
from app.tools.context import ToolContext
from app.tools.registry import ToolRegistry
from app.tools.loader import load_builtin_tools, load_user_script_tools

def _init_tools(self):
    """一次性初始化所有工具。"""
    ctx = ToolContext(
        config=self.config,
        workspace=Path(self.config.get("workspace", ".")),
        note_mgr=self.note_manager,
        scheduler=self.scheduler,
        ai_client=self.ai_client,
        on_note_created=self._on_note_created,
        http_timeout=self.config.get("http_timeout", 30),
        proxy=self.config.get("proxy"),
    )
    self.registry = ToolRegistry()
    builtin_names = load_builtin_tools(ctx, self.registry)
    user_names = load_user_script_tools(
        Path(self.config.get("user_tools_dir", "data/user_tools")),
        self.registry,
    )
    logger.info("Tools loaded: %d builtin, %d user", len(builtin_names), len(user_names))
```

**变化要点**：
- 删除 `_register_builtin_tools()` 方法
- 新增 `_init_tools()` — 构建 ToolContext → 自动发现注册
- `self.registry` 传给 AgentLoop，替代原来的 `builtin_tools` dict + `tool_manager`

---

## UI ToolboxPanel 适配

```python
# app/ui/toolbox_panel.py — 从 registry 获取工具列表
def refresh_tools(self, registry: ToolRegistry):
    """刷新工具面板显示。"""
    self.tool_list.clear()
    for tool in registry.get_all():
        item = QListWidgetItem()
        widget = ToolItemWidget(
            name=tool.name,
            description=tool.description,
            enabled=tool.enabled,
            is_builtin=not isinstance(tool, ScriptToolAdapter),
        )
        item.setSizeHint(widget.sizeHint())
        self.tool_list.addItem(item)
        self.tool_list.setItemWidget(item, widget)
```

---

## 迁移步骤

按以下顺序执行，每步完成后可独立验证：

### Phase 1：基础设施（不影响现有功能）

1. 创建 `app/tools/` 包目录
2. 实现 `base.py`、`schema.py`、`context.py`、`registry.py`、`loader.py`
3. 实现 `script_adapter.py`
4. 编写单元测试验证基础设施

### Phase 2：迁移现有内置工具

5. 迁移 `CalculatorTool` → `app/tools/calculator.py`（最简单，验证模式）
6. 迁移 `ClipboardTool` → `app/tools/clipboard.py`
7. 迁移需要 DI 的工具：`CreateNoteTool`、`ReadNotesTool`、`SummarizeSessionTool`
8. 迁移调度器工具：`CreateScheduledTaskTool`、`ListScheduledTasksTool`、`DeleteScheduledTaskTool`
9. 删除 `app/core/builtin_tools.py`

### Phase 3：迁移外部脚本工具为 in-process

10. 迁移 `web_search` → `app/tools/web_search.py`
11. 迁移 `fetch_url` → `app/tools/fetch_url.py`
12. 迁移 `read_file` → `app/tools/read_file.py`
13. 迁移 `save_file` → `app/tools/save_file.py`
14. 迁移 `run_python` → `app/tools/run_python.py`
15. 迁移 `reminder` → `app/tools/reminder.py`
16. 迁移 `multi_model_consult` → `app/tools/multi_model_consult.py`
17. 删除 `tools/` 目录下对应的脚本工具文件夹

### Phase 4：集成与清理

18. 改造 `MainWindow._init_tools()` — 使用 loader 自动发现
19. 改造 `AgentLoop` — 统一通过 registry 执行
20. 适配 `ToolboxPanel` — 从 registry 获取列表
21. 精简 `app/core/tool_manager.py` — 只保留用户工具依赖安装逻辑
22. 删除 `app/core/tool_protocol.py`
23. 删除 `app/models/tool_def.py`（内容已移入 script_adapter）

### Phase 5：用户工具目录迁移

24. 创建 `data/user_tools/` 目录
25. 将 `tools/example_tool/` 移入作为示例模板
26. 更新配置中的用户工具路径

---

## 删除文件清单

| 文件 | 原因 |
|------|------|
| `app/core/tool_protocol.py` | 被 `app/tools/base.py` ABC 替代 |
| `app/core/builtin_tools.py` | 拆分到 `app/tools/` 各独立文件 |
| `app/models/tool_def.py` | 仅 ScriptToolAdapter 使用，逻辑已内联 |
| `tools/web_search/` | 迁移为 `app/tools/web_search.py` |
| `tools/fetch_url/` | 迁移为 `app/tools/fetch_url.py` |
| `tools/read_file/` | 迁移为 `app/tools/read_file.py` |
| `tools/save_file/` | 迁移为 `app/tools/save_file.py` |
| `tools/run_python/` | 迁移为 `app/tools/run_python.py` |
| `tools/reminder/` | 迁移为 `app/tools/reminder.py` |
| `tools/multi_model_consult/` | 迁移为 `app/tools/multi_model_consult.py` |

**保留**：
- `tools/example_tool/` → 移入 `data/user_tools/example_tool/` 作为用户工具模板
- `app/core/tool_manager.py` → 精简为用户工具依赖安装器
- `app/core/tool_deps.py` → 保留，用户工具依赖管理

---

## 测试策略

```python
# tests/tools/test_base.py
class TestBuiltinTool:
    def test_cast_params_string_to_int(self):
        tool = CalculatorTool()
        result = tool.cast_params({"expression": "1+1"})
        assert result == {"expression": "1+1"}

    def test_cast_params_bool_coercion(self):
        # 模拟一个有 bool 参数的工具
        ...

    def test_to_openai_function_format(self):
        tool = CalculatorTool()
        schema = tool.to_openai_function()
        assert schema["type"] == "function"
        assert schema["function"]["name"] == "calculator"
        assert "parameters" in schema["function"]

    def test_validate_params_missing_required(self):
        tool = CalculatorTool()
        errors = tool.validate_params({})
        assert any("expression" in e for e in errors)


# tests/tools/test_registry.py
class TestToolRegistry:
    def test_register_and_get(self):
        registry = ToolRegistry()
        tool = CalculatorTool()
        registry.register(tool)
        assert registry.get("calculator") is tool

    def test_execute_with_cast(self):
        registry = ToolRegistry()
        registry.register(CalculatorTool())
        result = registry.execute("calculator", {"expression": "2+3"})
        assert result["status"] == "success"
        assert result["data"]["result"] == 5

    def test_execute_unknown_tool(self):
        registry = ToolRegistry()
        result = registry.execute("nonexistent", {})
        assert result["status"] == "error"


# tests/tools/test_loader.py
class TestLoader:
    def test_discover_finds_calculator(self):
        classes = discover_builtin_tools()
        names = [cls.__name__ for cls in classes]
        assert "CalculatorTool" in names

    def test_load_builtin_tools_registers_all(self):
        ctx = ToolContext(config={}, workspace=Path("."))
        registry = ToolRegistry()
        names = load_builtin_tools(ctx, registry)
        assert "calculator" in names
```

每个迁移的工具都应有对应的单元测试，验证：
1. `execute()` 正常路径返回 `{"status": "success", ...}`
2. `execute()` 异常路径返回 `{"status": "error", ...}`
3. `cast_params()` 正确处理 LLM 常见类型错误
4. `to_openai_function()` 输出符合 OpenAI schema 格式
