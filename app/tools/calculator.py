"""
计算器工具 — 安全地计算数学表达式。

这是一个典型的"简单工具"示例：
  - 不需要外部依赖（不覆盖 create 方法）
  - 标记为 read_only（可并发执行）
  - 使用受限的 eval 环境防止代码注入

安全措施：
  - __builtins__ 设为空 dict，禁止访问内置函数
  - 只暴露 math 模块的函数和少量安全的内置函数
  - 不允许 import、exec、open 等危险操作
"""
import math
from typing import Any

from app.tools.base import BuiltinTool
from app.tools.schema import Str, tool_params


class CalculatorTool(BuiltinTool):
    """数学表达式计算工具，支持四则运算、幂次、三角函数、对数等。"""

    # 构建安全的执行环境：只包含 math 模块的函数和少量安全内置函数
    _ALLOWED: dict = {k: getattr(math, k) for k in dir(math) if not k.startswith("_")}
    _ALLOWED.update({"abs": abs, "round": round, "int": int, "float": float,
                     "pow": pow, "sum": sum, "min": min, "max": max})

    @property
    def name(self) -> str:
        return "calculator"

    @property
    def description(self) -> str:
        return "计算数学表达式，支持四则运算、幂次、三角函数、对数、常数 pi/e 等"

    @property
    def parameters(self) -> dict[str, Any]:
        return tool_params(
            "expression",  # expression 是必填参数
            expression=Str("要计算的数学表达式，如 '2**10'、'sin(pi/4)'、'log(100, 10)'"),
        )

    @property
    def read_only(self) -> bool:
        """计算器无副作用，可以并发执行。"""
        return True

    def execute(self, params: dict[str, Any]) -> dict[str, Any]:
        expr = params.get("expression", "").strip()
        if not expr:
            return {"status": "error", "data": {"message": "expression is required"}}
        try:
            # 在受限环境中执行表达式（禁止访问 __builtins__）
            result = eval(expr, {"__builtins__": {}}, self._ALLOWED)  # noqa: S307
            # 复数需要特殊序列化（JSON 不支持复数类型）
            if isinstance(result, complex):
                serialized: object = {"real": result.real, "imag": result.imag, "str": str(result)}
            else:
                serialized = result
            return {"status": "success", "data": {"expression": expr, "result": serialized}}
        except Exception as e:
            return {"status": "error", "data": {"message": str(e), "expression": expr}}
