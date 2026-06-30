"""
工具发现与加载 — 基于 pkgutil 的自动注册机制。

本模块实现了"零配置新增工具"的核心能力：
  1. discover_builtin_tools(): 扫描 app/tools/ 包下所有 .py 模块，
     找到继承了 BuiltinTool 的非抽象类
  2. load_builtin_tools(): 对发现的工具类调用 create(ctx) 工厂方法，
     注册到 ToolRegistry
  3. load_user_script_tools(): 扫描用户工具目录（data/user_tools/），
     将 manifest.json + tool.py 包装为 ScriptToolAdapter 并注册

新增内置工具的流程：
  在 app/tools/ 下创建 .py 文件 → 定义继承 BuiltinTool 的类 → 完成。
  loader 会自动发现并注册，无需修改任何其他文件。

跳过的模块（_SKIP_MODULES）：
  基础设施模块（base、schema、context、registry、loader、script_adapter）
  不包含工具实现，扫描时跳过以避免误注册。
"""
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

# 基础设施模块列表 — 这些模块不包含工具实现，扫描时跳过
_SKIP_MODULES = frozenset({
    "base", "schema", "context", "registry", "loader",
    "script_adapter", "__init__",
})


def discover_builtin_tools() -> list[type[BuiltinTool]]:
    """
    扫描 app/tools/ 包，自动发现所有 BuiltinTool 子类。

    发现逻辑：
      1. 用 pkgutil.iter_modules 遍历包内所有模块（PyInstaller 6.x 的
         PyiFrozenLoader 同样支持，故源码/打包共用一套逻辑；打包时由
         AI_Agent.spec 的 collect_submodules('app.tools') 确保模块入包）
      2. 跳过基础设施模块和下划线开头的私有模块
      3. 导入模块后遍历其所有属性
      4. 筛选条件：是类 + 是 BuiltinTool 子类 + 不是 BuiltinTool 本身 + 非抽象类
      5. 用 id() 去重（同一个类可能被多次引用）

    Returns:
        按类名排序的工具类列表
    """
    import app.tools as _pkg

    results: list[type[BuiltinTool]] = []
    seen: set[int] = set()  # 用 id 去重，防止同一个类被多个模块引用时重复注册

    for _importer, module_name, _ispkg in pkgutil.iter_modules(_pkg.__path__):
        # 跳过基础设施模块和私有模块
        if module_name in _SKIP_MODULES or module_name.startswith("_"):
            continue
        try:
            module = importlib.import_module(f".{module_name}", _pkg.__name__)
        except Exception:
            logger.exception("Failed to import tool module: %s", module_name)
            continue

        # 遍历模块中的所有属性，找到 BuiltinTool 子类
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if (
                isinstance(attr, type)                          # 是类
                and issubclass(attr, BuiltinTool)               # 是 BuiltinTool 子类
                and attr is not BuiltinTool                     # 不是基类本身
                and not getattr(attr, "__abstractmethods__", None)  # 非抽象类
                and id(attr) not in seen                        # 未重复
            ):
                seen.add(id(attr))
                results.append(attr)

    # 按类名排序，保证注册顺序稳定（方便调试和测试）
    results.sort(key=lambda cls: cls.__name__)
    return results


def load_builtin_tools(ctx: ToolContext, registry: ToolRegistry) -> list[str]:
    """
    发现并注册所有内置工具。

    流程：
      1. 调用 discover_builtin_tools() 获取所有工具类
      2. 对每个类调用 create(ctx) 工厂方法创建实例
      3. 将实例注册到 registry

    Args:
        ctx: 统一上下文容器，传递给每个工具的 create() 方法
        registry: 工具注册中心

    Returns:
        成功注册的工具名称列表
    """
    registered: list[str] = []
    for tool_cls in discover_builtin_tools():
        try:
            tool = tool_cls.create(ctx)
            registry.register(tool)
            registered.append(tool.name)
        except Exception:
            logger.exception("Failed to create tool: %s", tool_cls.__name__)
    logger.info("Loaded %d builtin tools: %s", len(registered), ", ".join(sorted(registered)))
    return registered


def load_user_script_tools(
    user_tools_dir: Path,
    registry: ToolRegistry,
) -> list[str]:
    """
    扫描用户工具目录，注册外部脚本工具。

    目录结构要求：
      user_tools_dir/
        ├── my_tool/
        │   ├── manifest.json   ← 工具元数据（名称、描述、参数定义）
        │   └── tool.py         ← 工具执行脚本（通过 subprocess 隔离运行）
        └── another_tool/
            ├── manifest.json
            └── tool.py

    Args:
        user_tools_dir: 用户工具根目录（通常是 data/user_tools/）
        registry: 工具注册中心

    Returns:
        成功注册的工具名称列表
    """
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
