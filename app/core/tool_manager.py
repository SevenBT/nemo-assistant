import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

from app.core.config import TOOLS_DIR, ConfigManager
from app.models.tool_def import ParameterDef, ToolDefinition


def _get_python_exe() -> str:
    """Return a usable Python interpreter path.

    When packaged with PyInstaller sys.executable points to the frozen .exe,
    not to a Python interpreter.  Fall back to whatever 'python' is on PATH.
    """
    if getattr(sys, "frozen", False):
        python = shutil.which("python") or shutil.which("python3")
        return python if python else sys.executable
    return sys.executable


class ToolManager:
    def __init__(self, config: ConfigManager):
        self._config = config
        self._tools: dict[str, ToolDefinition] = {}
        self._discover()

    # ------------------------------------------------------------------ discovery
    def _discover(self):
        if not TOOLS_DIR.exists():
            return
        for tool_dir in TOOLS_DIR.iterdir():
            if not tool_dir.is_dir():
                continue
            manifest_path = tool_dir / "manifest.json"
            if not manifest_path.exists():
                continue
            try:
                self._load_tool(tool_dir, manifest_path)
            except Exception as e:
                print(f"[ToolManager] Skip {tool_dir.name}: {e}")

    def _load_tool(self, tool_dir: Path, manifest_path: Path):
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
            )

        tool = ToolDefinition(
            name=manifest["name"],
            description=manifest["description"],
            script_path=str(script_path),
            parameters=params,
            tool_dir=str(tool_dir),
        )
        self._tools[tool.name] = tool
        print(f"[ToolManager] Loaded: {tool.name}")

    def reload(self):
        self._tools.clear()
        self._discover()

    # ------------------------------------------------------------------ queries
    def get_tools(self) -> list[ToolDefinition]:
        return list(self._tools.values())

    def get(self, name: str) -> Optional[ToolDefinition]:
        return self._tools.get(name)

    def get_openai_functions(self) -> list[dict]:
        return [t.to_openai_function() for t in self._tools.values()]

    def get_manual_params(self, tool_name: str) -> list[str]:
        """Return parameter names that require manual user input."""
        tool = self._tools.get(tool_name)
        if not tool:
            return []
        return [n for n, p in tool.parameters.items() if p.source == "manual"]

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
        config_params = self._config.get_tool_params(tool_name)
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
        """Run the Python script, pass params via stdin JSON, parse stdout last line."""
        tool = self._tools.get(tool_name)
        if not tool:
            return {"status": "error", "data": {"message": f"Tool not found: {tool_name}"}}

        stdin_payload = json.dumps(
            {"params": params, "context": {}}, ensure_ascii=False
        )
        try:
            proc = subprocess.run(
                [_get_python_exe(), tool.script_path],
                input=stdin_payload,
                capture_output=True,
                text=True,
                timeout=60,
                encoding="utf-8",
            )
            stdout = proc.stdout.strip()
            if not stdout:
                if proc.returncode != 0:
                    return {
                        "status": "error",
                        "data": {"message": proc.stderr.strip() or "No output"},
                    }
                return {"status": "success", "data": {}}
            last_line = stdout.splitlines()[-1]
            return json.loads(last_line)
        except subprocess.TimeoutExpired:
            return {"status": "error", "data": {"message": "Execution timed out (60s)"}}
        except json.JSONDecodeError as e:
            return {"status": "error", "data": {"message": f"Invalid JSON output: {e}"}}
        except Exception as e:
            return {"status": "error", "data": {"message": str(e)}}
