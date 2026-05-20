"""Custom list item delegate that respects the widget's font.

qfluentwidgets' ListItemDelegate hardcodes getFont(13) in initStyleOption,
ignoring any font set on the widget via setFont() or QSS. This subclass
falls back to the parent widget's font instead.
"""
from qfluentwidgets import ListItemDelegate
from PyQt6.QtCore import QModelIndex, Qt
from PyQt6.QtWidgets import QStyleOptionViewItem


class FontAwareListDelegate(ListItemDelegate):
    def initStyleOption(self, option: QStyleOptionViewItem, index: QModelIndex):
        super().initStyleOption(option, index)
        # If the item doesn't have its own font, use the widget's font
        if not index.data(Qt.ItemDataRole.FontRole):
            option.font = self.parent().font()
