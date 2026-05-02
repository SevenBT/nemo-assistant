import sys

from PyQt6.QtWidgets import QApplication

from app.core.config import ConfigManager
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
    scheduler = SchedulerManager()
    scheduler.set_tool_manager(tools)
    scheduler.start()

    window = MainWindow(config, sessions, tools, scheduler)
    window.show()

    exit_code = app.exec()
    scheduler.stop()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
