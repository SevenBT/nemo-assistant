"""工具设置页 — 搜索引擎、API Key、保存目录

工具的启用/禁用已统一到「能力管理器」(工坊面板),此处只保留配置类设置。
"""

from pathlib import Path

from PyQt6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.core.config import (
    cfg,
    get_search_api_key,
    set_search_api_key,
)
from app.i18n import t

# (data, i18n key)；label/说明文字在运行时按当前语言取，避免在 init_language 之前定型
_SEARCH_PROVIDERS = [
    ("ddg", "settings.tools.providerDdg"),
    ("bing", "settings.tools.providerBing"),
    ("tavily", "settings.tools.providerTavily"),
    ("brave", "settings.tools.providerBrave"),
    ("bocha", "settings.tools.providerBocha"),
]

_KEY_HINT_KEYS = {
    "ddg": "settings.tools.keyHintDdg",
    "bing": "settings.tools.keyHintBing",
    "tavily": "settings.tools.keyHintTavily",
    "brave": "settings.tools.keyHintBrave",
    "bocha": "settings.tools.keyHintBocha",
}


class ToolsPage(QScrollArea):
    def __init__(self, registry=None, parent=None):
        super().__init__(parent)
        self._registry = registry
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
        for data, label_key in _SEARCH_PROVIDERS:
            self._search_provider.addItem(t(label_key), data)
        current = cfg.get(cfg.searchProvider)
        idx = next((i for i, (d, _) in enumerate(_SEARCH_PROVIDERS) if d == current), 0)
        self._search_provider.setCurrentIndex(idx)
        self._search_provider.currentIndexChanged.connect(self._on_provider_changed)
        form.addRow(t("settings.tools.searchEngine"), self._search_provider)

        # Search API key
        self._search_key = QLineEdit()
        self._search_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._search_key.setText(get_search_api_key())
        self._search_key.editingFinished.connect(self._save_search_key)
        self._on_provider_changed(idx)
        form.addRow(t("settings.tools.searchApiKey"), self._search_key)

        # Save directory
        save_row = QWidget()
        save_layout = QHBoxLayout(save_row)
        save_layout.setContentsMargins(0, 0, 0, 0)
        self._save_dir = QLineEdit()
        self._save_dir.setPlaceholderText(str(Path.home() / "Downloads"))
        self._save_dir.setText(cfg.get(cfg.saveDir))
        self._save_dir.editingFinished.connect(self._save_dir_changed)
        browse_btn = QPushButton(t("settings.tools.browse"))
        # 不写死宽度：文案随语言变化（"浏览…" / "Browse…"），加上主题 QSS 的
        # 内边距后固定宽度会裁掉文字。让按钮按 sizeHint 自适应内容。
        browse_btn.clicked.connect(self._browse_save_dir)
        save_layout.addWidget(self._save_dir)
        save_layout.addWidget(browse_btn)
        form.addRow(t("settings.tools.saveDir"), save_row)

        layout.addLayout(form)

        layout.addStretch()
        self.setWidget(container)

    def _on_provider_changed(self, index: int):
        provider = self._search_provider.itemData(index)
        is_free = provider == "ddg"
        self._search_key.setEnabled(not is_free)
        self._search_key.setPlaceholderText(t(_KEY_HINT_KEYS.get(provider, "settings.tools.keyHintDefault")))
        cfg.set(cfg.searchProvider, provider)

    def _save_search_key(self):
        set_search_api_key(self._search_key.text().strip())

    def _save_dir_changed(self):
        cfg.set(cfg.saveDir, self._save_dir.text().strip())

    def _browse_save_dir(self):
        current = self._save_dir.text().strip() or str(Path.home() / "Downloads")
        path = QFileDialog.getExistingDirectory(self, t("settings.tools.chooseSaveDir"), current)
        if path:
            self._save_dir.setText(path)
            cfg.set(cfg.saveDir, path)
