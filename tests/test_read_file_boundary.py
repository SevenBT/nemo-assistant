"""read_file 工具的 workspace 边界测试。

与 list_dir/grep/find_files 一致，read_file 必须把路径钳制在 workspace 内，
不允许 AI 通过绝对路径或 ../ 逃逸读取任意系统文件（.ssh、凭据等）。
"""
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app.tools.read_file import ReadFileTool


class ReadFileBoundaryTest(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.workspace = Path(self._tmp.name)
        self.tool = ReadFileTool(workspace=self.workspace)

    def tearDown(self):
        self._tmp.cleanup()

    def test_reads_file_inside_workspace(self):
        target = self.workspace / "note.txt"
        target.write_text("hello workspace", encoding="utf-8")
        result = self.tool.execute({"file_path": "note.txt"})
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["data"]["content"], "hello workspace")

    def test_blocks_parent_traversal(self):
        # 在 workspace 外创建一个文件，尝试用 ../ 逃逸读取应被拒绝。
        outside = self.workspace.parent / "secret.txt"
        outside.write_text("top secret", encoding="utf-8")
        try:
            result = self.tool.execute({"file_path": "../secret.txt"})
        finally:
            outside.unlink(missing_ok=True)
        self.assertEqual(result["status"], "error")

    def test_blocks_absolute_path_outside_workspace(self):
        # 绝对路径指向 workspace 之外应被拒绝，不泄露内容。
        result = self.tool.execute({"file_path": "C:/Windows/system.ini"})
        self.assertEqual(result["status"], "error")

    def test_empty_path_is_rejected(self):
        result = self.tool.execute({"file_path": "   "})
        self.assertEqual(result["status"], "error")
        self.assertIn("required", result["data"]["message"])


if __name__ == "__main__":
    unittest.main()
