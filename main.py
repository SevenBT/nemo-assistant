import sys
import traceback
from pathlib import Path


def _setup_crash_log():
    """将未捕获异常写入 crash.log（打包后 console=False 时看不到终端）。"""
    if getattr(sys, "frozen", False):
        log_path = Path(sys.executable).parent / "crash.log"
    else:
        log_path = Path(__file__).parent / "crash.log"

    def excepthook(exc_type, exc_value, exc_tb):
        msg = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        log_path.write_text(msg, encoding="utf-8")
        # 弹窗提示（在有 QApplication 之前可能失败，所以用 try）
        try:
            from PyQt6.QtWidgets import QApplication, QMessageBox
            _app = QApplication.instance() or QApplication(sys.argv)
            QMessageBox.critical(None, "启动错误", msg[:2000])
        except Exception:
            pass

    sys.excepthook = excepthook


_setup_crash_log()

from PyQt6.QtWidgets import QApplication

from app.core.config import ConfigManager
from app.core.note_manager import NoteManager
from app.core.scheduler import SchedulerManager
from app.core.session_manager import SessionManager
from app.core.tool_manager import ToolManager
from app.ui.main_window import MainWindow
from app.ui.style import STYLESHEET


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("AI Agent")
    app.setQuitOnLastWindowClosed(False)  # keep alive in tray
    app.setStyleSheet(STYLESHEET)

    config = ConfigManager()
    sessions = SessionManager()
    tools = ToolManager(config)
    notes = NoteManager()
    scheduler = SchedulerManager()
    scheduler.set_tool_manager(tools)
    scheduler.start()

    window = MainWindow(config, sessions, tools, scheduler, notes)
    window.show()

    exit_code = app.exec()
    scheduler.stop()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
