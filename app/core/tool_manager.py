"""
工具管理器。

负责工具发现（内置 + 用户自定义）、参数解析、子进程隔离执行。
工具脚本通过 stdin 接收 JSON 参数，stdout 最后一行输出 JSON 结果。
"""
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

from app.core.config import TOOLS_DIR, USER_TOOLS_DIR, cfg, get_search_api_key
from app.core.tool_deps import ToolDependencyManager
from app.models.tool_def import ParameterDef, ToolDefinition

_TOOL_TIMEOUT = 60  # seconds


class ToolManager:
    """工具管理器，管理工具的发现、参数解析和执行。"""

    def __init__(self):
        self._tools: dict[str, ToolDefinition] = {}
        self._deps = ToolDependencyManager()
        self._discover()

    # ------------------------------------------------------------------ 工具发现
    def _discover(self):
        # 内置工具：tools/（只读，始终启用）
        self._discover_dir(TOOLS_DIR, is_builtin=True)
        # 用户工具：data/user_tools/（可编辑，可开关）
        self._discover_dir(USER_TOOLS_DIR, is_builtin=False)

    def _discover_dir(self, base: Path, is_builtin: bool):
        if not base.exists():
            return
        for tool_dir in base.iterdir():
            if not tool_dir.is_dir():
                continue
            manifest_path = tool_dir / "manifest.json"
            if not manifest_path.exists():
                continue
            try:
                self._load_tool(tool_dir, manifest_path, is_builtin=is_builtin)
            except Exception as e:
                print(f"[ToolManager] Skip {tool_dir.name}: {e}")

    def _load_tool(self, tool_dir: Path, manifest_path: Path, is_builtin: bool = False):
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)

        script_name = manifest.get("script", "tool.py")
        script_path = tool_dir / script_name
        if not script_path.exists():
            raise FileNotFoundError(f"Script not found: {script_path}")

        params: dict[str, ParameterDef] = {}
        for pname, pdata in manifest.get("parameters", {}).items():
            params[pname] = ParameterDef(
                name=pname,
                type=pdata.get("type", "string"),
                description=pdata.get("description", ""),
                source=pdata.get("source", "ai"),
                required=pdata.get("required", True),
                default=pdata.get("default"),
                enum=pdata.get("enum", []),
                items=pdata.get("items"),
            )

        # 内置工具始终启用；用户工具遵循保存的开关状态
        enabled = True if is_builtin else cfg.get(cfg.toolStates).get(manifest["name"], True)

        tool = ToolDefinition(
            name=manifest["name"],
            description=manifest["description"],
            script_path=str(script_path),
            parameters=params,
            tool_dir=str(tool_dir),
            enabled=enabled,
            dependencies=manifest.get("dependencies", []),
            version=manifest.get("version", ""),
            author=manifest.get("author", ""),
            is_builtin=is_builtin,
        )
        self._tools[tool.name] = tool
        print(f"[ToolManager] Loaded: {tool.name} (enabled={enabled})")

    def reload(self):
        self._tools.clear()
        self._discover()

    # ------------------------------------------------------------------ 查询
    def get_tools(self) -> list[ToolDefinition]:
        return list(self._tools.values())

    def get(self, name: str) -> Optional[ToolDefinition]:
        return self._tools.get(name)

    def get_openai_functions(self) -> list[dict]:
        return [t.to_openai_function() for t in self._tools.values() if t.enabled]

    def get_manual_params(self, tool_name: str) -> list[str]:
        """获取需要用户手动输入的参数名列表。"""
        tool = self._tools.get(tool_name)
        if not tool:
            return []
        return [n for n, p in tool.parameters.items() if p.source == "manual"]

    def set_tool_enabled(self, tool_name: str, enabled: bool):
        """切换工具启用状态并持久化。"""
        tool = self._tools.get(tool_name)
        if tool:
            tool.enabled = enabled
        states = dict(cfg.get(cfg.toolStates))
        states[tool_name] = enabled
        cfg.set(cfg.toolStates, states)

    def get_config_params(self, tool_name: str) -> dict:
        """获取工具的配置来源参数值（如搜索 provider、保存目录等）。"""
        if tool_name == "web_search":
            return {"provider": cfg.get(cfg.searchProvider), "api_key": get_search_api_key()}
        if tool_name == "save_file":
            return {"save_dir": cfg.get(cfg.saveDir)}
        return {}

    @property
    def deps_manager(self) -> ToolDependencyManager:
        return self._deps

    # ------------------------------------------------------------------ 参数解析
    def resolve_params(
        self,
        tool_name: str,
        ai_params: dict,
        manual_overrides: Optional[dict] = None,
    ) -> dict:
        """合并参数，优先级：手动输入 > AI 生成 > 配置项 > 默认值。"""
        tool = self._tools.get(tool_name)
        if not tool:
            return ai_params
        manual_overrides = manual_overrides or {}
        config_params = self.get_config_params(tool_name)
        resolved = {}
        for pname, pdef in tool.parameters.items():
            if pname in manual_overrides:
                resolved[pname] = manual_overrides[pname]
            elif pname in ai_params:
                resolved[pname] = ai_params[pname]
            elif pname in config_params:
                resolved[pname] = config_params[pname]
            elif pdef.default is not None:
                resolved[pname] = pdef.default
        return resolved

    # ------------------------------------------------------------------ 执行
    def execute(self, tool_name: str, params: dict) -> dict:
        """在子进程中运行工具脚本，确保隔离性。"""
        tool = self._tools.get(tool_name)
        if not tool:
            return {"status": "error", "data": {"message": f"Tool not found: {tool_name}"}}

        # 确保依赖已安装
        if tool.dependencies:
            ok, err = self._deps.ensure_deps(tool.dependencies)
            if not ok:
                return {"status": "error", "data": {"message": f"依赖安装失败: {err}"}}

        return self._exec_subprocess(tool, params)

    def _exec_subprocess(self, tool: ToolDefinition, params: dict) -> dict:
        """执行工具脚本子进程，解析 stdout 最后一行 JSON 作为结果。"""
        stdin_payload = json.dumps(
            {"params": params, "context": {}}, ensure_ascii=False
        )

        env = os.environ.copy()
        # 构建 PYTHONPATH：隔离的 site-packages + 工具自身目录
        extra_paths = [
            str(self._deps.site_packages_path),
            tool.tool_dir,
        ]
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = os.pathsep.join(
            extra_paths + ([existing] if existing else [])
        )

        try:
            result = subprocess.run(
                [sys.executable, tool.script_path],
                input=stdin_payload,
                capture_output=True,
                text=True,
                timeout=_TOOL_TIMEOUT,
                env=env,
                cwd=tool.tool_dir,
            )
        except subprocess.TimeoutExpired:
            return {
                "status": "error",
                "data": {"message": f"执行超时 ({_TOOL_TIMEOUT}s)"},
            }
        except Exception as e:
            return {"status": "error", "data": {"message": str(e)}}

        stdout = result.stdout.strip()
        stderr = result.stderr.strip()

        # 非零退出且无 stdout — 报告 stderr
        if result.returncode != 0 and not stdout:
            return {
                "status": "error",
                "data": {"message": stderr or f"Exit code {result.returncode}"},
            }

        if not stdout:
            return {"status": "success", "data": {}}

        last_line = stdout.splitlines()[-1]
        try:
            parsed = json.loads(last_line)
            # 若有 stderr 则附加为调试信息
            if stderr and isinstance(parsed.get("data"), dict):
                parsed["data"].setdefault("_stderr", stderr)
            return parsed
        except json.JSONDecodeError as e:
            return {
                "status": "error",
                "data": {
                    "message": f"Invalid JSON output: {e}",
                    "raw": stdout[-500:],
                    "_stderr": stderr[-500:] if stderr else "",
                },
            }
