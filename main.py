"""
Application entry point.

Startup flow: check dependencies -> configure crash logging ->
initialize the Qt application -> create the main window.

应用程序入口。
启动流程：检查依赖 → 配置崩溃日志 → 初始化 Qt 应用 → 创建主窗口。
"""
import sys
import traceback
from pathlib import Path

# PyInstaller onefile guard: a frozen child process re-executes this exe.
# freeze_support() makes multiprocessing children exit cleanly here instead of
# falling through and launching another full app instance.
import multiprocessing
multiprocessing.freeze_support()

# ── 依赖自动安装 ──────────────────────────────────────────────────────────
# 每个元组: (import名, pip包名)
_REQUIRED_PACKAGES = [
    ("bs4",         "beautifulsoup4"),
    ("httpx",       "httpx"),
    ("openai",      "openai"),
    ("apscheduler", "APScheduler"),
    ("pyperclip",   "pyperclip"),
    ("keyboard",    "keyboard"),
]

def _can_import(name: str) -> bool:
    try:
        __import__(name)
        return True
    except ImportError:
        return False

def _ensure_deps():
    # When frozen (PyInstaller), dependencies are bundled into the exe — never
    # shell out to pip. Critically, in onefile mode sys.executable IS this app,
    # so "sys.executable -m pip ..." would relaunch the whole app instead of
    # pip, spawning runaway processes. Only auto-install from source checkouts.
    if getattr(sys, "frozen", False):
        return
    missing = [pkg for imp, pkg in _REQUIRED_PACKAGES if not _can_import(imp)]
    if missing:
        missing_text = ", ".join(missing)
        raise SystemExit(
            "[startup] Missing runtime dependencies: "
            f"{missing_text}\nInstall them with: python -m pip install ."
        )

_ensure_deps()
# ─────────────────────────────────────────────────────────────────────────


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
            from app.i18n import t
            _app = QApplication.instance() or QApplication(sys.argv)
            QMessageBox.critical(None, t("app.startupError"), msg[:2000])
        except Exception:
            pass

    sys.excepthook = excepthook


_setup_crash_log()

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication

from app.core.config import cfg
from app.core.note_manager import NoteManager
from app.core.scheduler import SchedulerManager
from app.core.session_manager import SessionManager
from app.ui.main_window import MainWindow
from app.ui.style import apply_theme


def main():
    """初始化各管理器并启动主窗口。"""
    # Windows: set an explicit AppUserModelID so the taskbar groups this app
    # under its own window icon instead of the default Python/PyInstaller icon.
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "sevenbt.nemo-assistant"
            )
        except Exception:
            pass

    app = QApplication(sys.argv)
    app.setApplicationName("Nemo Assistant")
    app.setQuitOnLastWindowClosed(False)  # 保持托盘常驻

    # 加载打包字体并设为全局字体（须在应用主题/样式表之前）。
    from app.ui.fonts import apply_app_font
    apply_app_font()

    # 锁定本次运行的界面语言（切换语言需重启才生效）。
    from app.i18n import init_language
    init_language(cfg.get(cfg.language))

    from app.core.config import ASSETS_DIR
    icon_path = ASSETS_DIR / "app_icon.png"
    icon = QIcon(str(icon_path))
    app.setWindowIcon(icon)

    custom_qss = apply_theme(cfg.get(cfg.theme), content_font_size=cfg.get(cfg.contentFontSize), editor_font_size=cfg.get(cfg.editorFontSize))
    app.setStyleSheet(custom_qss)
    sessions = SessionManager()
    notes = NoteManager()
    scheduler = SchedulerManager()
    scheduler.start()

    window = MainWindow(sessions, scheduler, notes)
    window.setWindowIcon(icon)
    # FluentWindow 构造函数会重置内部样式，需要重新应用主题
    custom_qss = apply_theme(cfg.get(cfg.theme), content_font_size=cfg.get(cfg.contentFontSize), editor_font_size=cfg.get(cfg.editorFontSize))
    app.setStyleSheet(custom_qss)
    window.show()

    exit_code = app.exec()
    scheduler.stop()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
