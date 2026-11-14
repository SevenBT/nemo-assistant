"""Default paths; importing performs no IO."""
import sys
from pathlib import Path

if getattr(sys, "frozen", False):
    # Writable data (config/, data/) lives next to the executable.
    BASE_DIR = Path(sys.executable).parent
    # Bundled read-only resources (tools/, assets/) are unpacked by the
    # PyInstaller bootloader. In onefile mode that is the _MEIPASS temp dir;
    # in onedir mode it falls back to the executable's directory.
    BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", BASE_DIR))
    # 可写数据（config/、data/）放在可执行文件旁边；
    # 打包的只读资源（tools/、assets/）由 PyInstaller 引导器解压：
    # onefile 模式下在 _MEIPASS 临时目录，onedir 模式回退到 exe 同级目录。
else:
    # app/config/runtime_paths.py stays two package levels below the project root.
    BASE_DIR = Path(__file__).parent.parent.parent
    BUNDLE_DIR = BASE_DIR

CONFIG_DIR = BASE_DIR / "config"
DATA_DIR = BASE_DIR / "data"
SESSIONS_DIR = DATA_DIR / "sessions"
NOTES_DIR = DATA_DIR / "notes"
NOTES_IMAGES_DIR = NOTES_DIR / "images"
TRASH_DIR = NOTES_DIR / "trash"
SCREENSHOTS_DIR = DATA_DIR / "screenshots"
TOOLS_DIR = BUNDLE_DIR / "tools"
ASSETS_DIR = BUNDLE_DIR / "assets"
USER_TOOLS_DIR = DATA_DIR / "user_tools"
TOOL_RUNTIME_DIR = DATA_DIR / "tool_runtime"
TOOL_SITE_PACKAGES = TOOL_RUNTIME_DIR / "site-packages"
TOOL_BUILDS_DIR = DATA_DIR / "tool_builds"
