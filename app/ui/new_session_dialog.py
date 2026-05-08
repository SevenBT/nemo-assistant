"""
新建会话对话框

网格布局显示所有预设角色，用户点击选择。
"""
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QGridLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.core.preset_manager import PresetManager
from app.models.preset import Preset


class PresetButton(QPushButton):
    """预设角色按钮"""

    def __init__(self, preset: Preset, parent=None):
        super().__init__(parent)
        self.preset = preset
        self.setFixedSize(100, 100)
        self.setText(f"{preset.icon}\n{preset.name}")
        self.setStyleSheet("""
            QPushButton {
                border: 2px solid #3b4252;
                border-radius: 8px;
                background: #2e3440;
                color: #d8dee9;
                font-size: 13px;
                padding: 8px;
            }
            QPushButton:hover {
                background: #3b4252;
                border-color: #5e81ac;
            }
            QPushButton:pressed {
                background: #434c5e;
            }
        """)


class NewSessionDialog(QDialog):
    """新建会话对话框"""

    preset_selected = pyqtSignal(str)  # preset_id

    def __init__(self, preset_mgr: PresetManager, parent=None):
        super().__init__(parent)
        self._preset_mgr = preset_mgr
        self.setWindowTitle("新建会话")
        self.setMinimumSize(500, 400)
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)

        # 标题
        title = QLabel("选择预设角色")
        title.setStyleSheet("font-size: 16px; font-weight: bold; color: #d8dee9;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        # 滚动区域
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        # 网格容器
        grid_widget = QWidget()
        grid = QGridLayout(grid_widget)
        grid.setSpacing(12)

        # 添加预设角色按钮
        presets = self._preset_mgr.get_all()
        cols = 4
        for i, preset in enumerate(presets):
            btn = PresetButton(preset)
            btn.clicked.connect(lambda checked, p=preset: self._on_preset_clicked(p))
            row, col = divmod(i, cols)
            grid.addWidget(btn, row, col)

        scroll.setWidget(grid_widget)
        layout.addWidget(scroll)

    def _on_preset_clicked(self, preset: Preset):
        """预设角色被点击"""
        self.preset_selected.emit(preset.id)
        self.accept()

