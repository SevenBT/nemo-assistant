"""
脚本工具适配器 — 将用户自定义的脚本工具包装为 BuiltinTool 接口。

设计目的：
  用户可以通过 manifest.json + tool.py 的方式创建自定义工具，
  无需了解 BuiltinTool 的内部实现。ScriptToolAdapter 负责：
    1. 解析 manifest.json 中的元数据和参数定义
    2. 将参数定义转换为标准 JSON Schema 格式
    3. 通过 subprocess 隔离执行 tool.py（用户脚本崩溃不影响主进程）
    4. 解析脚本的 stdout 输出为标准结果格式

脚本通信协议：
  输入：通过 stdin 传入 JSON → {"params": {...}, "context": {...}}
  输出：脚本最后一行 stdout 必须是 JSON → {"status": "success/error", "data": {...}}

隔离机制：
  - 每个脚本在独立子进程中运行
  - PYTHONPATH 注入工具目录和共享 site-packages
  - 超时保护（默认 60 秒）
  - 依赖自动安装（通过 ToolDependencyManager）
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from app.tools.base import BuiltinTool
from app.core.tool_deps import ToolDependencyManager

# 脚本执行超时时间（秒）
_TOOL_TIMEOUT = 60


class ScriptToolAdapter(BuiltinTool):
    """
    将 manifest.json + tool.py 包装为 BuiltinTool。

    继承 BuiltinTool 后，脚本工具和内置工具在注册表中完全平等，
    AgentLoop 无需区分它们。

    属性（相比 BuiltinTool 额外提供）：
      - version: 工具版本号
      - author: 工具作者
      - tool_dir: 工具所在目录路径
      - dependencies: pip 依赖列表
      - enabled: 可读写，支持用户在设置中开关工具
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
        version: str = "",
        author: str = "",
    ):
        self._name = tool_name
        self._description = tool_description
        self._parameters = tool_parameters
        self._script_path = script_path
        self._tool_dir = tool_dir
        self._read_only = is_read_only
        self._dependencies = dependencies or []
        self._enabled = True
        self._version = version
        self._author = author
        # 依赖管理器：负责将工具声明的 pip 包安装到隔离的 site-packages
        self._deps_mgr = ToolDependencyManager()

    # ── BuiltinTool 接口实现 ──

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
        """允许用户在设置界面中开关工具。"""
        self._enabled = value

    # ── 脚本工具特有属性 ──

    @property
    def version(self) -> str:
        return self._version

    @property
    def author(self) -> str:
        return self._author

    @property
    def tool_dir(self) -> str:
        return self._tool_dir

    @property
    def dependencies(self) -> list[str]:
        return self._dependencies

    def execute(self, params: dict[str, Any]) -> dict[str, Any]:
        """
        通过 subprocess 执行脚本工具。

        执行流程：
          1. 检查并安装依赖（首次运行时）
          2. 构造 stdin 输入（JSON 格式）
          3. 设置 PYTHONPATH 环境变量（注入工具目录和 site-packages）
          4. 启动子进程执行 tool.py
          5. 解析 stdout 最后一行为 JSON 结果
        """
        # 确保依赖已安装
        if self._dependencies:
            ok, err = self._deps_mgr.ensure_deps(self._dependencies)
            if not ok:
                return {"status": "error", "data": {"message": f"依赖安装失败: {err}"}}

        # 构造传给脚本的 JSON 输入
        stdin_payload = json.dumps({"params": params, "context": {}}, ensure_ascii=False)

        # 设置环境变量，让脚本能 import 工具目录和共享 site-packages 中的包
        env = os.environ.copy()
        extra_paths = [str(self._deps_mgr.site_packages_path), self._tool_dir]
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = os.pathsep.join(extra_paths + ([existing] if existing else []))

        try:
            result = subprocess.run(
                [sys.executable, self._script_path],
                input=stdin_payload,
                capture_output=True,
                text=True,
                timeout=_TOOL_TIMEOUT,
                env=env,
                cwd=self._tool_dir,  # 工作目录设为工具所在目录
            )
        except subprocess.TimeoutExpired:
            return {"status": "error", "data": {"message": f"执行超时 ({_TOOL_TIMEOUT}s)"}}
        except Exception as e:
            return {"status": "error", "data": {"message": str(e)}}

        stdout = result.stdout.strip()
        stderr = result.stderr.strip()

        # 非零退出码且无 stdout → 视为执行失败
        if result.returncode != 0 and not stdout:
            return {"status": "error", "data": {"message": stderr or f"Exit code {result.returncode}"}}
        if not stdout:
            return {"status": "success", "data": {}}

        # 解析 stdout 最后一行为 JSON（脚本可能有调试输出在前面的行）
        last_line = stdout.splitlines()[-1]
        try:
            parsed = json.loads(last_line)
            # 如果有 stderr 输出，附加到结果中供调试
            if stderr and isinstance(parsed.get("data"), dict):
                parsed["data"].setdefault("_stderr", stderr)
            return parsed
        except json.JSONDecodeError as e:
            return {"status": "error", "data": {"message": f"Invalid JSON: {e}", "raw": stdout[-500:]}}

    @classmethod
    def from_manifest(cls, manifest_path: Path) -> "ScriptToolAdapter":
        """
        从 manifest.json 构建适配器实例。

        manifest.json 格式示例：
        {
            "name": "my_tool",
            "description": "工具描述",
            "script": "tool.py",
            "version": "1.0.0",
            "author": "作者",
            "read_only": false,
            "dependencies": ["requests>=2.28"],
            "parameters": {
                "query": {
                    "type": "string",
                    "description": "搜索关键词",
                    "required": true
                },
                "api_key": {
                    "type": "string",
                    "source": "config"  ← 来自配置的参数，不暴露给 LLM
                }
            }
        }

        注意：source="config" 的参数会被过滤掉，不出现在 JSON Schema 中。
        """
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)

        tool_dir = manifest_path.parent
        script_path = str(tool_dir / manifest.get("script", "tool.py"))

        # 将 manifest 中的参数定义转换为标准 JSON Schema 格式
        properties = {}
        required = []
        for pname, pdata in manifest.get("parameters", {}).items():
            # source="config" 的参数来自应用配置，不暴露给 LLM
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
            # 默认 required=True，除非显式设为 False
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
            version=manifest.get("version", ""),
            author=manifest.get("author", ""),
        )
