"""工具设置页 — 搜索引擎、API Key、保存目录、工具开关"""

from pathlib import Path

from PyQt6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import SwitchButton

from app.core.config import (
    cfg,
    get_search_api_key,
    set_search_api_key,
)

_SEARCH_PROVIDERS = [
    ("ddg", "DuckDuckGo（免费，无需 Key）"),
    ("bing", "Bing Search"),
    ("tavily", "Tavily"),
    ("brave", "Brave Search"),
    ("bocha", "博查 AI 搜索"),
]

_KEY_HINTS = {
    "ddg": "DuckDuckGo 无需 API Key",
    "bing": "Azure Bing Search API Key（portal.azure.com）",
    "tavily": "Tavily API Key（tavily.com）",
    "brave": "Brave Search API Key（api.search.brave.com）",
    "bocha": "博查 API Key（bocha.ai）",
}


class ToolsPage(QScrollArea):
    def __init__(self, tool_mgr=None, parent=None):
        super().__init__(parent)
        self._tool_mgr = tool_mgr
        self._tool_switches: dict[str, SwitchButton] = {}
        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.Shape.NoFrame)
        self._build()

    def _build(self):
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(16, 16, 16, 16)

        # Search provider
        form = QFormLayout()
        self._search_provider = QComboBox()
        for data, label in _SEARCH_PROVIDERS:
            self._search_provider.addItem(label, data)
        current = cfg.get(cfg.searchProvider)
        idx = next((i for i, (d, _) in enumerate(_SEARCH_PROVIDERS) if d == current), 0)
        self._search_provider.setCurrentIndex(idx)
        self._search_provider.currentIndexChanged.connect(self._on_provider_changed)
        form.addRow("搜索引擎:", self._search_provider)

        # Search API key
        self._search_key = QLineEdit()
        self._search_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._search_key.setText(get_search_api_key())
        self._search_key.editingFinished.connect(self._save_search_key)
        self._on_provider_changed(idx)
        form.addRow("搜索 API Key:", self._search_key)

        # Save directory
        save_row = QWidget()
        save_layout = QHBoxLayout(save_row)
        save_layout.setContentsMargins(0, 0, 0, 0)
        self._save_dir = QLineEdit()
        self._save_dir.setPlaceholderText(str(Path.home() / "Downloads"))
        self._save_dir.setText(cfg.get(cfg.saveDir))
        self._save_dir.editingFinished.connect(self._save_dir_changed)
        browse_btn = QPushButton("浏览…")
        browse_btn.setFixedWidth(60)
        browse_btn.clicked.connect(self._browse_save_dir)
        save_layout.addWidget(self._save_dir)
        save_layout.addWidget(browse_btn)
        form.addRow("文件保存目录:", save_row)

        layout.addLayout(form)

        # Tool enable/disable switches
        if self._tool_mgr:
            layout.addWidget(QLabel("工具开关:"))
            tool_form = QFormLayout()
            states = cfg.get(cfg.toolStates)
            for tool in self._tool_mgr.get_tools():
                name = tool.name
                label = name
                sw = SwitchButton()
                sw.setChecked(states.get(name, True))
                sw.checkedChanged.connect(
                    lambda checked, n=name: self._on_tool_toggled(n, checked)
                )
                self._tool_switches[name] = sw
                tool_form.addRow(label + ":", sw)
            layout.addLayout(tool_form)

        layout.addStretch()
        self.setWidget(container)

    def _on_provider_changed(self, index: int):
        provider = self._search_provider.itemData(index)
        is_free = provider == "ddg"
        self._search_key.setEnabled(not is_free)
        self._search_key.setPlaceholderText(_KEY_HINTS.get(provider, "API Key"))
        cfg.set(cfg.searchProvider, provider)

    def _save_search_key(self):
        set_search_api_key(self._search_key.text().strip())

    def _save_dir_changed(self):
        cfg.set(cfg.saveDir, self._save_dir.text().strip())

    def _browse_save_dir(self):
        current = self._save_dir.text().strip() or str(Path.home() / "Downloads")
        path = QFileDialog.getExistingDirectory(self, "选择文件保存目录", current)
        if path:
            self._save_dir.setText(path)
            cfg.set(cfg.saveDir, path)

    def _on_tool_toggled(self, name: str, checked: bool):
        states = dict(cfg.get(cfg.toolStates))
        states[name] = checked
        cfg.set(cfg.toolStates, states)
