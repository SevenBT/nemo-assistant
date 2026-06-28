"""note_manager 批量标签查询（消除 N+1）正确性测试。"""
import tempfile
import unittest
from pathlib import Path

from app.core.db_manager import DatabaseManager
from app.core.note_manager import NoteManager


class BatchTagsTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._tmp.cleanup)
        db = DatabaseManager(Path(self._tmp.name) / "notes.db")
        self.mgr = NoteManager(db)

    def test_get_notes_attaches_correct_tags(self):
        n1 = self.mgr.create(title="A")
        n2 = self.mgr.create(title="B")
        n3 = self.mgr.create(title="C")  # 无标签
        self.mgr.update(n1.id, title="A", content="", tags=["工作", "重要"])
        self.mgr.update(n2.id, title="B", content="", tags=["个人"])

        notes = {n.id: n for n in self.mgr.get_notes()}

        self.assertEqual(sorted(notes[n1.id].tags), ["工作", "重要"])
        self.assertEqual(notes[n2.id].tags, ["个人"])
        self.assertEqual(notes[n3.id].tags, [])


if __name__ == "__main__":
    unittest.main()
