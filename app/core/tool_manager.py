"""Tool discovery, parameter resolution, and subprocess-based execution."""
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
    def __init__(self):
        self._tools: dict[str, ToolDefinition] = {}
        self._deps = ToolDependencyManager()
        self._discover()

    # ------------------------------------------------------------------ discovery
    def _discover(self):
        # Builtin tools: tools/ (read-only, always enabled)
        self._discover_dir(TOOLS_DIR, is_builtin=True)
        # User tools: data/user_tools/ (editable, can be toggled)
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

        # Builtin tools are always enabled; user tools respect saved state
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

    # ------------------------------------------------------------------ queries
    def get_tools(self) -> list[ToolDefinition]:
        return list(self._tools.values())

    def get(self, name: str) -> Optional[ToolDefinition]:
        return self._tools.get(name)

    def get_openai_functions(self) -> list[dict]:
        return [t.to_openai_function() for t in self._tools.values() if t.enabled]

    def get_manual_params(self, tool_name: str) -> list[str]:
        """Return parameter names that require manual user input."""
        tool = self._tools.get(tool_name)
        if not tool:
            return []
        return [n for n, p in tool.parameters.items() if p.source == "manual"]

    def set_tool_enabled(self, tool_name: str, enabled: bool):
        """Toggle tool enabled state and persist."""
        tool = self._tools.get(tool_name)
        if tool:
            tool.enabled = enabled
        states = dict(cfg.get(cfg.toolStates))
        states[tool_name] = enabled
        cfg.set(cfg.toolStates, states)

    def get_config_params(self, tool_name: str) -> dict:
        """Return config-source parameter values for the given tool."""
        if tool_name == "web_search":
            return {"provider": cfg.get(cfg.searchProvider), "api_key": get_search_api_key()}
        if tool_name == "save_file":
            return {"save_dir": cfg.get(cfg.saveDir)}
        return {}

    @property
    def deps_manager(self) -> ToolDependencyManager:
        return self._deps

    # ------------------------------------------------------------------ param resolution
    def resolve_params(
        self,
        tool_name: str,
        ai_params: dict,
        manual_overrides: Optional[dict] = None,
    ) -> dict:
        """Merge params: manual > ai > config > default."""
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

    # ------------------------------------------------------------------ execution
    def execute(self, tool_name: str, params: dict) -> dict:
        """Run the tool script in a subprocess for isolation.

        The script receives JSON on stdin and must print a JSON result as its
        last stdout line.  Same protocol as before — existing tools need no changes.
        """
        tool = self._tools.get(tool_name)
        if not tool:
            return {"status": "error", "data": {"message": f"Tool not found: {tool_name}"}}

        # Ensure dependencies are installed
        if tool.dependencies:
            ok, err = self._deps.ensure_deps(tool.dependencies)
            if not ok:
                return {"status": "error", "data": {"message": f"依赖安装失败: {err}"}}

        return self._exec_subprocess(tool, params)

    def _exec_subprocess(self, tool: ToolDefinition, params: dict) -> dict:
        """Execute tool script in an isolated subprocess."""
        stdin_payload = json.dumps(
            {"params": params, "context": {}}, ensure_ascii=False
        )

        env = os.environ.copy()
        # Build PYTHONPATH: isolated site-packages + tool's own directory
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

        # Non-zero exit with no stdout — report stderr
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
            # Attach stderr as debug info if present
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
