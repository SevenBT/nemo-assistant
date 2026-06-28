"""SessionManager 原子写 + 并发安全测试。"""
import json
import threading
import unittest
from unittest import mock

from app.core import session_manager as sm_mod
from app.core.session_manager import SessionManager
from app.models.message import Message


class SessionManagerConcurrencyTest(unittest.TestCase):
    def setUp(self):
        self._tmp = __import__("tempfile").TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        from pathlib import Path

        self.dir = Path(self._tmp.name)
        # SESSIONS_DIR 在 session_manager 模块顶层被引用，patch 模块属性。
        self._patcher = mock.patch.object(sm_mod, "SESSIONS_DIR", self.dir)
        self._patcher.start()
        self.addCleanup(self._patcher.stop)

    def test_save_is_atomic_and_loadable(self):
        mgr = SessionManager()
        session = mgr.create(title="t")
        for i in range(20):
            mgr.add_message(session.id, Message(role="user", content=f"m{i}"))
        # 落盘文件应是完整可解析的 JSON。
        path = self.dir / f"{session.id}.json"
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(len(data["messages"]), 20)
        # 不应残留临时文件。
        self.assertEqual(list(self.dir.glob("*.tmp")), [])

    def test_concurrent_add_message_no_corruption(self):
        mgr = SessionManager()
        session = mgr.create(title="t")
        sid = session.id

        def worker(n):
            for i in range(10):
                mgr.add_message(sid, Message(role="user", content=f"w{n}-{i}"))

        threads = [threading.Thread(target=worker, args=(n,)) for n in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # 文件始终可解析（无写一半截断）。
        path = self.dir / f"{sid}.json"
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        # 内存中消息数应为 5 线程 * 10 条。
        self.assertEqual(len(mgr.get(sid).messages), 50)
        self.assertIsInstance(data["messages"], list)


if __name__ == "__main__":
    unittest.main()
