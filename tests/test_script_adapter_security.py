"""ScriptToolAdapter.from_manifest 路径穿越防护测试。"""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.core.tool_build.models import ToolPermission
from app.tools.script_adapter import ScriptToolAdapter


class ManifestPathTraversalTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._tmp.cleanup)
        self.tool_dir = Path(self._tmp.name) / "my_tool"
        self.tool_dir.mkdir()

    def _write_manifest(self, script_value: str) -> Path:
        manifest = {
            "name": "t",
            "description": "d",
            "script": script_value,
            "parameters": {},
        }
        path = self.tool_dir / "manifest.json"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        return path

    def test_legal_script_accepted(self):
        adapter = ScriptToolAdapter.from_manifest(self._write_manifest("tool.py"))
        self.assertTrue(adapter._script_path.endswith("tool.py"))

    def test_legal_subdir_script_accepted(self):
        adapter = ScriptToolAdapter.from_manifest(self._write_manifest("sub/run.py"))
        self.assertIn("sub", adapter._script_path)

    def test_parent_traversal_rejected(self):
        with self.assertRaises(ValueError):
            ScriptToolAdapter.from_manifest(self._write_manifest("../../../evil.py"))

    def test_windows_style_traversal_rejected(self):
        with self.assertRaises(ValueError):
            ScriptToolAdapter.from_manifest(self._write_manifest(r"..\..\evil.py"))

    def test_legacy_manifest_exposes_empty_permissions_and_legacy_marker(self):
        adapter = ScriptToolAdapter.from_manifest(self._write_manifest("tool.py"))

        self.assertEqual(adapter.permissions, frozenset())
        self.assertTrue(adapter.is_legacy_manifest)

    def test_legacy_manifest_defaults_missing_script_to_tool_py(self):
        path = self.tool_dir / "manifest.json"
        path.write_text(json.dumps({"name": "t", "description": "d"}), encoding="utf-8")

        adapter = ScriptToolAdapter.from_manifest(path)

        self.assertTrue(adapter._script_path.endswith("tool.py"))

    def test_legacy_manifest_rejects_required_metadata_and_invalid_script(self):
        invalid_manifests = (
            {"description": "d", "script": "tool.py"},
            {"name": "t", "script": "tool.py"},
            {"name": "", "description": "d", "script": "tool.py"},
            {"name": "t", "description": "", "script": "tool.py"},
            {"name": "t", "description": "d", "script": None},
            {"name": "t", "description": "d", "script": {}},
            {"name": "t", "description": "d", "script": []},
            {"name": "t", "description": "d", "script": ""},
        )
        for invalid_manifest in invalid_manifests:
            path = self.tool_dir / "manifest.json"
            path.write_text(json.dumps(invalid_manifest), encoding="utf-8")
            with self.assertRaises(ValueError):
                ScriptToolAdapter.from_manifest(path)


        for strict_invalid in (
            {"manifest_version": 2, "name": "t", "description": "d", "script": "tool.py"},
            {"manifest_version": "1", "name": "t", "description": "d", "script": "tool.py"},
            {"manifest_version": 1, "name": "t", "description": "d", "script": "tool.py", "parameters": {}, "permissions": [], "dependencies": []},
            {"manifest_version": 1, "name": "t", "description": "d", "script": "tool.py", "parameters": {}, "output": {}, "permissions": ["unknown"], "dependencies": []},
            {"manifest_version": 1, "name": "t", "description": "d", "script": "tool.py", "parameters": {}, "output": {}, "permissions": [], "dependencies": ["requests"]},
        ):
            path = self.tool_dir / "manifest.json"
            path.write_text(json.dumps(strict_invalid), encoding="utf-8")
            with self.assertRaises(ValueError):
                ScriptToolAdapter.from_manifest(path)

    def test_strict_manifest_exposes_declared_permissions_and_marker(self):
        manifest = {
            "manifest_version": 1,
            "name": "strict_tool",
            "description": "strict",
            "script": "tool.py",
            "parameters": {},
            "output": {"type": "object"},
            "permissions": ["file_read"],
            "dependencies": [],
        }
        path = self.tool_dir / "manifest.json"
        path.write_text(json.dumps(manifest), encoding="utf-8")

        adapter = ScriptToolAdapter.from_manifest(path)

        self.assertEqual({permission.value for permission in adapter.permissions}, {"file_read"})
        self.assertFalse(adapter.is_legacy_manifest)


class ScriptAdapterExecutionTest(unittest.TestCase):
    def _adapter(self, dependencies=None):
        return ScriptToolAdapter(
            "tool", "description", {"type": "object", "properties": {}},
            "tool.py", ".", dependencies=dependencies,
            permissions=frozenset({ToolPermission.FILE_READ}),
            is_legacy_manifest=False,
        )

    def test_properties_and_dependency_failure_are_exposed_without_running_script(self):
        adapter = self._adapter(["package"])
        adapter._deps_mgr = SimpleNamespace(ensure_deps=lambda _deps: (False, "unavailable"))

        result = adapter.execute({})

        self.assertEqual(adapter.name, "tool")
        self.assertEqual(adapter.description, "description")
        self.assertFalse(adapter.read_only)
        self.assertFalse(adapter.retry_safe)
        self.assertTrue(adapter.enabled)
        adapter.enabled = False
        self.assertFalse(adapter.enabled)
        self.assertEqual(adapter.permissions, frozenset({ToolPermission.FILE_READ}))
        self.assertEqual(result["status"], "error")

    def test_strict_adapter_with_dependencies_refuses_without_side_effects(self):
        adapter = self._adapter(["forbidden"])
        adapter._deps_mgr = SimpleNamespace(
            ensure_deps=lambda _deps: self.fail("strict dependencies must not be installed")
        )
        import app.tools.script_adapter as module
        from unittest.mock import patch

        with patch.object(module.subprocess, "run", side_effect=self.fail):
            result = adapter.execute({})

        self.assertEqual(result["status"], "error")
        self.assertFalse(result["data"]["retryable"])

    def test_execute_parses_last_json_line_and_uses_minimal_environment(self):
        adapter = self._adapter()
        captured = {}

        def run(*args, **kwargs):
            captured.update(args=args, kwargs=kwargs)
            return SimpleNamespace(returncode=0, stdout="debug\n{\"status\": \"success\", \"data\": {}}", stderr="notice")

        import app.tools.script_adapter as module
        from unittest.mock import patch
        with patch.object(module.subprocess, "run", run), patch(
            "app.tools.run_python._build_minimal_env", return_value={"PATH": "safe"}
        ):
            result = adapter.execute({"x": "y"})

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["data"]["_stderr"], "notice")
        self.assertEqual(captured["kwargs"]["env"]["PATH"], "safe")

    def test_execute_handles_timeout_nonzero_and_invalid_json(self):
        adapter = self._adapter()
        import app.tools.script_adapter as module
        from unittest.mock import patch

        with patch.object(module.subprocess, "run", side_effect=subprocess.TimeoutExpired("tool", 1)):
            self.assertEqual(adapter.execute({})["data"]["error_type"], "timeout")
        with patch.object(module.subprocess, "run", return_value=SimpleNamespace(returncode=1, stdout="", stderr="failed")):
            self.assertEqual(adapter.execute({})["status"], "error")
        with patch.object(module.subprocess, "run", return_value=SimpleNamespace(returncode=0, stdout="not json", stderr="")):
            self.assertIn("Invalid JSON", adapter.execute({})["data"]["message"])


if __name__ == "__main__":
    unittest.main()
