from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
)


class ManualParamsDialog(QDialog):
    """Ask the user to fill in parameters marked as source=manual."""

    def __init__(self, tool_name: str, param_names: list[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"补充参数 — {tool_name}")
        self.setMinimumWidth(360)
        self._fields: dict[str, QLineEdit] = {}
        self._build(param_names)

    def _build(self, param_names: list[str]):
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("以下参数需要手动输入："))

        form = QFormLayout()
        for name in param_names:
            edit = QLineEdit()
            form.addRow(f"{name}:", edit)
            self._fields[name] = edit
        layout.addLayout(form)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def get_values(self) -> dict:
        return {name: edit.text().strip() for name, edit in self._fields.items()}
