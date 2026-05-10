import io
import json
import runpy
import sys
import threading
from contextlib import redirect_stdout
from pathlib import Path
from typing import Optional

from app.core.config import TOOLS_DIR, ConfigManager
from app.models.tool_def import ParameterDef, ToolDefinition

_TOOL_TIMEOUT = 60  # seconds


class ToolManager:
    def __init__(self, config: ConfigManager):
        self._config = config
        self._tools: dict[str, ToolDefinition] = {}
        # Serializes sys.stdin/stdout redirection across concurrent tool executions
        # (e.g. a scheduler-triggered tool running while a chat tool is in progress).
        self._exec_lock = threading.Lock()
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
                items=pdata.get("items"),
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
        """Run the tool script in-process using the bundled Python interpreter.

        The script is executed via runpy inside a daemon thread so the calling
        thread can enforce a timeout.  stdin/stdout are redirected per-call so
        the existing script API (read JSON from stdin, print JSON to stdout) is
        preserved without any subprocess overhead.
        """
        tool = self._tools.get(tool_name)
        if not tool:
            return {"status": "error", "data": {"message": f"Tool not found: {tool_name}"}}

        result_holder: list[dict] = []

        def _run():
            result_holder.append(self._exec_script(tool, params))

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        t.join(timeout=_TOOL_TIMEOUT)

        if t.is_alive():
            return {
                "status": "error",
                "data": {"message": f"Execution timed out ({_TOOL_TIMEOUT}s)"},
            }
        if result_holder:
            return result_holder[0]
        return {"status": "success", "data": {}}

    def _exec_script(self, tool: ToolDefinition, params: dict) -> dict:
        """Execute *tool.script_path* in-process and return its JSON result."""
        stdin_payload = json.dumps(
            {"params": params, "context": {}}, ensure_ascii=False
        )
        stdout_buf = io.StringIO()
        stdin_buf = io.StringIO(stdin_payload)

        # The lock serializes sys.stdin/stdout/path mutations so a scheduler-
        # triggered tool and a chat tool can't clobber each other's streams.
        with self._exec_lock:
            script_dir = str(Path(tool.script_path).parent)
            path_inserted = script_dir not in sys.path
            if path_inserted:
                sys.path.insert(0, script_dir)

            old_stdin = sys.stdin
            sys.stdin = stdin_buf
            try:
                with redirect_stdout(stdout_buf):
                    runpy.run_path(tool.script_path, run_name="__main__")
            except SystemExit:
                pass  # scripts may call sys.exit(0) to signal clean completion
            except Exception as e:
                return {"status": "error", "data": {"message": str(e)}}
            finally:
                sys.stdin = old_stdin
                if path_inserted:
                    try:
                        sys.path.remove(script_dir)
                    except ValueError:
                        pass

        output = stdout_buf.getvalue().strip()
        if not output:
            return {"status": "success", "data": {}}

        last_line = output.splitlines()[-1]
        try:
            return json.loads(last_line)
        except json.JSONDecodeError as e:
            return {
                "status": "error",
                "data": {"message": f"Invalid JSON output: {e}", "raw": output},
            }
