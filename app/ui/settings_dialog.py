from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLineEdit,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.core.config import ConfigManager
from app.ui.style import THEMES


class SettingsDialog(QDialog):
    def __init__(self, config: ConfigManager, parent=None):
        super().__init__(parent)
        self._config = config
        self.setWindowTitle("设置")
        self.setMinimumWidth(400)
        self._build()
        self._load()

    def _build(self):
        layout = QVBoxLayout(self)

        tabs = QTabWidget()

        # ── API tab ───────────────────────────────────────────────────
        api_w = QWidget()
        api_form = QFormLayout(api_w)

        self._base_url = QLineEdit()
        self._base_url.setPlaceholderText("https://api.openai.com/v1")
        api_form.addRow("API 地址:", self._base_url)

        self._api_key = QLineEdit()
        self._api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._api_key.setPlaceholderText("sk-…")
        api_form.addRow("API Key:", self._api_key)

        self._model = QLineEdit()
        self._model.setPlaceholderText("gpt-4o")
        api_form.addRow("模型:", self._model)

        self._max_tokens = QSpinBox()
        self._max_tokens.setRange(256, 65536)
        self._max_tokens.setSingleStep(256)
        api_form.addRow("最大 Token:", self._max_tokens)

        self._temperature = QDoubleSpinBox()
        self._temperature.setRange(0.0, 2.0)
        self._temperature.setSingleStep(0.1)
        self._temperature.setDecimals(1)
        api_form.addRow("Temperature:", self._temperature)

        tabs.addTab(api_w, "API")

        # ── Window tab ────────────────────────────────────────────────
        win_w = QWidget()
        win_form = QFormLayout(win_w)

        self._opacity = QDoubleSpinBox()
        self._opacity.setRange(0.3, 1.0)
        self._opacity.setSingleStep(0.05)
        self._opacity.setDecimals(2)
        win_form.addRow("透明度:", self._opacity)

        self._always_on_top = QCheckBox("始终置顶")
        win_form.addRow("", self._always_on_top)

        self._edge_snap = QCheckBox("贴边自动吸附（上/右边缘）")
        win_form.addRow("", self._edge_snap)

        self._theme_combo = QComboBox()
        for key, t in THEMES.items():
            self._theme_combo.addItem(t["name"], key)
        win_form.addRow("主题:", self._theme_combo)

        tabs.addTab(win_w, "窗口")

        layout.addWidget(tabs)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self._save)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _load(self):
        api = self._config.app_config["api"]
        win = self._config.window_config
        self._base_url.setText(api.get("base_url", ""))
        self._api_key.setText(api.get("api_key", ""))
        self._model.setText(api.get("model", ""))
        self._max_tokens.setValue(api.get("max_tokens", 4096))
        self._temperature.setValue(api.get("temperature", 0.7))
        self._opacity.setValue(win.get("opacity", 0.97))
        self._always_on_top.setChecked(win.get("always_on_top", True))
        self._edge_snap.setChecked(win.get("edge_snap", True))
        theme = win.get("theme", "classic")
        idx = self._theme_combo.findData(theme)
        if idx >= 0:
            self._theme_combo.setCurrentIndex(idx)

    def _save(self):
        self._config.update_api_config(
            base_url=self._base_url.text().strip(),
            api_key=self._api_key.text().strip(),
            model=self._model.text().strip(),
            max_tokens=self._max_tokens.value(),
            temperature=self._temperature.value(),
        )
        self._config.update_window_config(
            opacity=self._opacity.value(),
            always_on_top=self._always_on_top.isChecked(),
            theme=self._theme_combo.currentData(),
            edge_snap=self._edge_snap.isChecked(),
        )
        self.accept()
