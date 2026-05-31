"""
工具基类 — 所有内置工具必须继承此 ABC。

本模块定义了工具系统的核心抽象：
  - BuiltinTool: 抽象基类，规定了工具必须实现的接口（name/description/parameters/execute）
  - 类型转换: cast_params() 自动修正 LLM 返回的参数类型（如 "5" → 5）
  - 参数校验: validate_params() 检查必填项和类型匹配

执行流程（由 ToolRegistry 驱动）：
  1. cast_params()   — 宽容地将参数转为正确类型
  2. validate_params() — 严格校验转换后的参数
  3. execute()       — 执行工具逻辑

为什么 cast 在 validate 之前？
  LLM 经常返回字符串形式的数字（"5" 而不是 5）或布尔值（"true" 而不是 true），
  如果先校验会产生大量误报。先转换再校验，既宽容又安全。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from app.tools.context import ToolContext

# JSON Schema type → Python 类型的映射表，用于 validate_params 中的类型检查
_TYPE_MAP: dict[str, type | tuple[type, ...]] = {
    "string": str,
    "number": (int, float),  # number 同时接受 int 和 float
    "integer": int,
    "boolean": bool,
    "array": list,
    "object": dict,
}

# 字符串转布尔值的映射（不区分大小写）
_BOOL_TRUE = frozenset(("true", "1", "yes"))
_BOOL_FALSE = frozenset(("false", "0", "no"))


class BuiltinTool(ABC):
    """
    内置工具抽象基类。

    所有工具必须实现以下抽象属性/方法：
      - name: 工具唯一标识符，用于注册和调用
      - description: 工具功能描述，展示给 LLM 帮助它决定何时调用
      - parameters: JSON Schema 格式的参数定义
      - execute(params): 执行工具逻辑，返回 {"status": "success/error", "data": {...}}

    可选覆盖：
      - read_only: 标记为只读工具，可被并发批量执行（默认 False）
      - enabled: 控制工具是否可用（默认 True）
      - create(ctx): 工厂方法，接收 ToolContext 获取依赖（默认直接 cls()）
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """工具唯一名称，如 "web_search"、"calculator"。"""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """工具功能描述，LLM 根据此描述决定是否调用该工具。"""
        ...

    @property
    @abstractmethod
    def parameters(self) -> dict[str, Any]:
        """
        JSON Schema 格式的参数定义。用于描述工具的参数规格，大模型根据格式生成工具的参数

        推荐使用 schema.py 中的 tool_params() 辅助函数生成，
        也可以直接返回手写的 dict。
        """
        ...

    @abstractmethod
    def execute(self, params: dict[str, Any]) -> dict[str, Any]:
        """
        执行工具逻辑。

        Args:
            params: 经过 cast_params + validate_params 处理后的参数字典

        Returns:
            统一格式: {"status": "success"|"error", "data": {...}}
        """
        ...

    @property
    def read_only(self) -> bool:
        """
        是否为只读工具（无副作用）。

        只读工具可以被 AgentLoop 并发批量执行，提高响应速度。
        例如 calculator、read_file、web_search 都是只读的。
        """
        return False

    @property
    def retry_safe(self) -> bool:
        """
        工具是否允许自动重试。

        默认沿用 read_only：只读工具一般无副作用，可以安全重试；有副作用工具
        必须显式覆盖为 True 才会自动重试，避免重复写文件、创建笔记或任务。
        """
        return bool(getattr(self, "_retry_safe", self.read_only))

    @property
    def enabled(self) -> bool:
        """工具是否启用。禁用的工具不会出现在 LLM 的可用工具列表中。"""
        return True

    @classmethod
    def create(cls, ctx: "ToolContext") -> "BuiltinTool":
        """
        工厂方法 — 从 ToolContext 获取依赖并构造工具实例。

        简单工具（如 calculator）不需要覆盖此方法，默认直接 cls()。
        需要外部依赖的工具（如 scheduler、notes）应覆盖此方法，
        从 ctx 中取出所需资源。

        Args:
            ctx: 统一上下文容器，包含 config、note_mgr、scheduler 等共享资源
        """
        return cls()

    def to_openai_function(self) -> dict[str, Any]:
        """
        生成 OpenAI function calling 格式的工具描述。

        返回格式：
        {
            "type": "function",
            "function": {
                "name": "...",
                "description": "...",
                "parameters": {...}  # JSON Schema
            }
        }

        此格式直接传给 OpenAI API 的 tools 参数。
        """
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def cast_params(self, params: dict[str, Any]) -> dict[str, Any]:
        """
        根据 parameters schema 做宽容的类型转换。

        LLM 返回的参数经常类型不对，常见情况：
          - 数字写成字符串: "5" → 5
          - 布尔值写成字符串: "true" → True
          - 数字写成布尔: 1 → True（不转换，因为可能是有意的）

        只转换 schema 中声明的参数，未声明的参数原样保留。
        """
        schema = self.parameters
        if schema.get("type") != "object":
            return params
        properties = schema.get("properties", {})
        result = {}
        for key, value in params.items():
            if key in properties:
                # 按照 schema 中声明的类型进行转换
                result[key] = self._cast_value(value, properties[key])
            else:
                # 未在 schema 中声明的参数，原样保留
                result[key] = value
        return result

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        """
        校验参数合法性。

        检查项：
          1. required 中声明的参数是否都存在
          2. 每个参数的类型是否匹配 schema 声明
          3. 有 enum 约束的参数值是否在允许范围内

        Returns:
            错误消息列表，空列表表示校验通过
        """
        schema = self.parameters
        required = schema.get("required", [])
        properties = schema.get("properties", {})
        errors = []
        # 检查必填参数
        for name in required:
            if name not in params:
                errors.append(f"缺少必需参数: {name}")
        # 检查类型和枚举约束
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

    @staticmethod
    def _check_type(value: Any, expected: str) -> bool:
        """检查值是否匹配期望的 JSON Schema 类型。None 值总是通过（视为可选）。"""
        if value is None:
            return True
        py_type = _TYPE_MAP.get(expected)
        if py_type is None:
            # 未知类型不做检查
            return True
        return isinstance(value, py_type)

    @staticmethod
    def _cast_value(value: Any, prop_schema: dict[str, Any]) -> Any:
        """
        将单个值转换为 schema 声明的目标类型。

        转换规则（按优先级）：
          1. 已经是正确类型 → 直接返回
          2. 字符串 → 数字: "5" → 5, "3.14" → 3.14
          3. 字符串 → 布尔: "true"/"1"/"yes" → True
          4. 任意 → 字符串: 调用 str()
          5. 数组 → 递归转换每个元素
          6. 无法转换 → 原样返回（交给 validate_params 报错）
        """
        target_type = prop_schema.get("type")
        if target_type is None or value is None:
            return value

        # ── 已经是正确类型，直接返回 ──
        if target_type == "boolean" and isinstance(value, bool):
            return value
        if target_type == "integer" and isinstance(value, int) and not isinstance(value, bool):
            # 注意：Python 中 bool 是 int 的子类，所以要排除 bool
            return value
        if target_type == "number" and isinstance(value, (int, float)) and not isinstance(value, bool):
            return value
        if target_type == "string" and isinstance(value, str):
            return value

        # ── 字符串 → 数字 ──
        if isinstance(value, str) and target_type in ("integer", "number"):
            try:
                return int(value) if target_type == "integer" else float(value)
            except ValueError:
                return value  # 无法转换，原样返回

        # ── 字符串 → 布尔 ──
        if isinstance(value, str) and target_type == "boolean":
            low = value.lower()
            if low in _BOOL_TRUE:
                return True
            if low in _BOOL_FALSE:
                return False
            return value  # 无法识别的字符串，原样返回

        # ── 任意类型 → 字符串 ──
        if target_type == "string" and not isinstance(value, str):
            return str(value)

        # ── 数组元素递归转换 ──
        if target_type == "array" and isinstance(value, list):
            items_schema = prop_schema.get("items")
            if items_schema:
                return [BuiltinTool._cast_value(item, items_schema) for item in value]

        return value
