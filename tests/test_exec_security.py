"""exec_security.is_dangerous_command 危险命令匹配测试。

deny pattern 触发的是用户确认而非阻断；这些测试守护正则不被误删/写错，
确保高危命令仍被识别、常规命令不被误伤。
"""
import unittest

from app.tools.exec_security import is_dangerous_command


class DangerousCommandTest(unittest.TestCase):
    def assert_dangerous(self, command: str):
        flag, pattern = is_dangerous_command(command)
        self.assertTrue(flag, f"应识别为危险: {command!r}")
        self.assertTrue(pattern, "应返回匹配的 pattern 描述")

    def assert_safe(self, command: str):
        flag, _ = is_dangerous_command(command)
        self.assertFalse(flag, f"不应误判为危险: {command!r}")

    def test_recursive_remove(self):
        self.assert_dangerous("rm -rf /")
        self.assert_dangerous("rm -r ./build")
        self.assert_dangerous("rm --recursive foo")

    def test_disk_format(self):
        self.assert_dangerous("format C:")
        self.assert_dangerous("mkfs.ext4 /dev/sda1")
        self.assert_dangerous("diskpart")

    def test_shutdown_reboot(self):
        self.assert_dangerous("shutdown -h now")
        self.assert_dangerous("reboot")
        self.assert_dangerous("poweroff")

    def test_registry_delete(self):
        self.assert_dangerous("reg delete HKLM\\Software\\Foo")

    def test_fork_bomb(self):
        self.assert_dangerous(":(){ :|:& };:")

    def test_dd_disk_overwrite(self):
        self.assert_dangerous("dd if=/dev/zero of=/dev/sda")
        self.assert_dangerous("echo x > /dev/sda")

    def test_kill_critical_process(self):
        self.assert_dangerous("taskkill /f /im explorer.exe")
        self.assert_dangerous("kill -9 1")

    def test_case_insensitive(self):
        self.assert_dangerous("SHUTDOWN -h now")
        self.assert_dangerous("RM -RF /tmp")

    def test_safe_commands_not_flagged(self):
        self.assert_safe("ls -la")
        self.assert_safe("pip install requests")
        self.assert_safe("echo hello")
        self.assert_safe("python script.py")
        self.assert_safe("git status")
        # "formatter" 含 "format" 但后面不是盘符，不应命中
        self.assert_safe("npx prettier --write .")
        self.assert_safe("cat README.md")


if __name__ == "__main__":
    unittest.main()
