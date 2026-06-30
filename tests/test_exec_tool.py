"""ExecTool.execute 校验分支测试 — 不实际执行子进程，只覆盖前置校验与确认逻辑。"""
import tempfile
import unittest
from pathlib import Path

from app.tools.exec_tool import ExecTool


class ExecToolValidationTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._tmp.cleanup)
        self.ws = Path(self._tmp.name)

    def test_empty_command_rejected(self):
        tool = ExecTool(workspace=self.ws)
        result = tool.execute({"command": "   "})
        self.assertEqual(result["status"], "error")
        self.assertIn("command", result["data"]["message"])

    def test_working_dir_escape_rejected(self):
        tool = ExecTool(workspace=self.ws)
        result = tool.execute({"command": "echo hi", "working_dir": "../../etc"})
        self.assertEqual(result["status"], "error")
        # resolve_safe 越界提示
        self.assertIn("workspace", result["data"]["message"])

    def test_nonexistent_working_dir_rejected(self):
        from app.i18n import t
        tool = ExecTool(workspace=self.ws)
        result = tool.execute({"command": "echo hi", "working_dir": "nope"})
        self.assertEqual(result["status"], "error")
        self.assertIn(t("tool.exec.msg.working_dir_not_found").split("{")[0], result["data"]["message"])

    def test_dangerous_command_without_confirm_blocked(self):
        from app.i18n import t
        # 无 confirm_action 时危险命令直接拦截，不执行
        tool = ExecTool(workspace=self.ws, confirm_action=None)
        result = tool.execute({"command": "rm -rf /"})
        self.assertEqual(result["status"], "error")
        self.assertIn(t("tool.exec.msg.dangerous_blocked").split("（")[0].split("(")[0], result["data"]["message"])

    def test_dangerous_command_user_declines(self):
        from app.i18n import t
        # confirm_action 返回 False → 用户取消，不执行
        tool = ExecTool(workspace=self.ws, confirm_action=lambda title, msg: False)
        result = tool.execute({"command": "shutdown -h now"})
        self.assertEqual(result["status"], "error")
        self.assertEqual(t("tool.exec.msg.user_cancelled"), result["data"]["message"])

    def test_safe_command_executes(self):
        # 安全命令应真正执行并返回 success（echo 跨平台可用）
        tool = ExecTool(workspace=self.ws)
        result = tool.execute({"command": "echo hello"})
        self.assertEqual(result["status"], "success")
        self.assertIn("hello", result["data"]["stdout"])
        self.assertEqual(result["data"]["return_code"], 0)


if __name__ == "__main__":
    unittest.main()
