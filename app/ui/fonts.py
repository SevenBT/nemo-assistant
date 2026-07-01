"""
应用字体加载。

启动时扫描 assets/fonts/ 下的字体文件并注册到 QFontDatabase，
然后把全局应用字体设为首选中文字体（MiSans），带回退链。

字体文件随应用打包（onefile 下由 PyInstaller 解压到 _MEIPASS），
若字体文件缺失则回退到系统已安装的同名字体或微软雅黑，不会报错。

Application font loading: register bundled fonts from assets/fonts/,
then set the global UI font to the preferred family with a fallback chain.
"""

import logging
from pathlib import Path

from PyQt6.QtGui import QFont, QFontDatabase
from PyQt6.QtWidgets import QApplication

from app.core.config import ASSETS_DIR

logger = logging.getLogger(__name__)

FONTS_DIR = ASSETS_DIR / "fonts"

# 首选字体族，按优先级回退。第一个可用的即被采用。
# MiSans 随应用打包；后两者是 Windows 系统兜底。
PREFERRED_FAMILIES = ["MiSans", "Microsoft YaHei UI", "Microsoft YaHei"]

_FONT_SUFFIXES = {".ttf", ".otf", ".ttc"}


def _register_bundled_fonts() -> set[str]:
    """注册 assets/fonts/ 下所有字体文件，返回已注册的字体族名集合。"""
    registered: set[str] = set()
    if not FONTS_DIR.is_dir():
        return registered
    for path in FONTS_DIR.iterdir():
        if path.suffix.lower() not in _FONT_SUFFIXES:
            continue
        font_id = QFontDatabase.addApplicationFont(str(path))
        if font_id < 0:
            logger.warning("字体加载失败: %s", path.name)
            continue
        for fam in QFontDatabase.applicationFontFamilies(font_id):
            registered.add(fam)
            logger.info("已注册字体: %s (%s)", fam, path.name)
    return registered


def _pick_family(available: set[str]) -> str | None:
    """从首选列表中选出第一个可用的字体族。"""
    installed = set(QFontDatabase.families())
    for fam in PREFERRED_FAMILIES:
        if fam in available or fam in installed:
            return fam
    return None


def apply_app_font() -> str | None:
    """注册打包字体并设置全局应用字体，返回最终采用的字体族名。"""
    app = QApplication.instance()
    if app is None:
        return None
    bundled = _register_bundled_fonts()
    family = _pick_family(bundled)
    if family is None:
        logger.info("未找到首选字体，沿用系统默认字体")
        return None
    font = QFont(family)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    app.setFont(font)
    logger.info("全局字体已设为: %s", family)
    return family
