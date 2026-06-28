"""ScriptToolAdapter.from_manifest 路径穿越防护测试。"""
import json
import tempfile
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
