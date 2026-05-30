"""
轻量 Schema DSL — 用 Python 类声明 JSON Schema，避免手写 dict 出错。

设计目标：
  1. 让工具参数定义像写文档一样直观
  2. 自动生成符合 OpenAI function calling 规范的 JSON Schema
  3. 通过 tool_params() 辅助函数一步完成 required + properties 组装

支持的类型：
  - Str:  字符串，可选 enum 枚举约束
  - Int:  整数，可选 minimum/maximum 范围
  - Num:  浮点数，可选 minimum/maximum 范围
  - Bool: 布尔值
  - Arr:  数组，需指定 items 元素类型
  - Obj:  嵌套对象，可指定子属性

用法示例：
    from app.tools.schema import Str, Int, Bool, tool_params

    parameters = tool_params(
        "query",                          # 位置参数 = required 字段名
        query=Str("搜索关键词"),            # 关键字参数 = 属性定义
        count=Int("结果数量", maximum=10),
        verbose=Bool("是否详细输出"),
    )
    # 生成 → {"type": "object", "properties": {...}, "required": ["query"]}
"""
from typing import Any


class _Schema:
    """Schema 片段基类，所有类型类继承此类并实现 to_dict()。"""

    def to_dict(self) -> dict[str, Any]:
        raise NotImplementedError


class Str(_Schema):
    """字符串类型参数。

    Args:
        description: 参数描述，会展示给 LLM 帮助它理解如何填写
        enum: 可选的枚举列表，限制 LLM 只能从中选择
    """

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
    """整数类型参数。

    Args:
        description: 参数描述
        minimum: 最小值约束（含）
        maximum: 最大值约束（含）
    """

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
    """浮点数类型参数。

    Args:
        description: 参数描述
        minimum: 最小值约束（含）
        maximum: 最大值约束（含）
    """

    def __init__(self, description: str = "", *, minimum: float | None = None, maximum: float | None = None):
        self._desc = description
        self._min = minimum
        self._max = maximum

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"type": "number"}
        if self._desc:
            d["description"] = self._desc
        if self._min is not None:
            d["minimum"] = self._min
        if self._max is not None:
            d["maximum"] = self._max
        return d


class Bool(_Schema):
    """布尔类型参数。

    Args:
        description: 参数描述
    """

    def __init__(self, description: str = ""):
        self._desc = description

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"type": "boolean"}
        if self._desc:
            d["description"] = self._desc
        return d


class Arr(_Schema):
    """数组类型参数。

    Args:
        items: 数组元素的类型定义（_Schema 实例或原始 dict）
        description: 参数描述
    """

    def __init__(self, items: _Schema | dict, description: str = ""):
        self._items = items
        self._desc = description

    def to_dict(self) -> dict[str, Any]:
        # 如果 items 是 _Schema 实例则调用 to_dict()，否则直接使用原始 dict
        items = self._items.to_dict() if isinstance(self._items, _Schema) else self._items
        d: dict[str, Any] = {"type": "array", "items": items}
        if self._desc:
            d["description"] = self._desc
        return d


class Obj(_Schema):
    """嵌套对象类型参数。

    Args:
        description: 参数描述
        **properties: 子属性定义，键为属性名，值为 _Schema 实例或原始 dict
    """

    def __init__(self, description: str = "", **properties: _Schema | dict):
        self._desc = description
        self._props = properties

    def to_dict(self) -> dict[str, Any]:
        # 递归转换所有子属性
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
    构建工具的 parameters JSON Schema。

    这是定义工具参数的主要入口函数。位置参数指定哪些字段是必填的，
    关键字参数定义每个字段的类型和描述。

    Args:
        *required: 必填参数的名称（字符串），LLM 必须提供这些参数
        **properties: 参数定义，键为参数名，值为 Schema 类型实例

    Returns:
        符合 JSON Schema 规范的 dict，可直接用于 OpenAI function calling

    用法:
        parameters = tool_params(
            "query",                    # "query" 是必填参数
            query=Str("搜索关键词"),
            count=Int("结果数量", maximum=10),  # count 是可选参数
        )
    """
    # 将所有 _Schema 实例转换为 dict
    props = {
        k: (v.to_dict() if isinstance(v, _Schema) else v)
        for k, v in properties.items()
    }
    schema: dict[str, Any] = {"type": "object", "properties": props}
    if required:
        schema["required"] = list(required)
    return schema
