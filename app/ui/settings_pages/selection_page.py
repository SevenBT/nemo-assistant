"""划词设置页 — 浮标总开关、各动作显隐、解释自定义提示词。

显隐开关用 qfluentwidgets 的 SwitchSettingCard；解释提示词需要多行文本编辑，
AutoSettingPage 不支持，故本页手写布局（不继承 AutoSettingPage）。
提示词卡片在编辑器失焦时写回 cfg.selectionExplainPrompt，并带「恢复默认」按钮。
"""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QHBoxLayout,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CardWidget,
    FluentIcon,
    PrimaryPushButton,
    SettingCardGroup,
    StrongBodyLabel,
    SwitchSettingCard,
    TextEdit,
)

from app.core.config import cfg
from app.ui.text_actions import get_text_action

# 解释提示词编辑器高度（px）。
_PROMPT_EDIT_HEIGHT = 120


class _ExplainPromptCard(CardWidget):
    """解释动作的自定义提示词卡片：多行编辑 + 恢复默认。

    失焦即写回 cfg.selectionExplainPrompt（空串表示用内置默认）。
    占位提示里说明 {text} 会被选中文字替换、留空则附在末尾。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build()
        self._load()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        hint = BodyLabel(
            "解释动作发给 AI 的提示词，留空使用内置默认。", self
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self._edit = TextEdit(self)
        self._edit.setFixedHeight(_PROMPT_EDIT_HEIGHT)
        self._edit.setPlaceholderText(
            "用 {text} 表示选中的文字；若不含 {text}，选中文字会自动附在末尾。"
        )
        # 失焦写回，避免每次按键都落盘
        self._edit.focusOutEvent = self._wrap_focus_out(self._edit.focusOutEvent)
        layout.addWidget(self._edit)

        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 0, 0, 0)
        btn_row.addStretch()
        self._reset_btn = PrimaryPushButton("恢复默认", self)
        self._reset_btn.clicked.connect(self._restore_default)
        btn_row.addWidget(self._reset_btn)
        layout.addLayout(btn_row)

    def _wrap_focus_out(self, original):
        def handler(event):
            self._save()
            original(event)
        return handler

    def _load(self):
        self._edit.setPlainText(cfg.get(cfg.selectionExplainPrompt) or "")

    def _save(self):
        cfg.set(cfg.selectionExplainPrompt, self._edit.toPlainText().strip())

    def _restore_default(self):
        """清空自定义提示词（回到内置默认），并把默认文案填入编辑器作参考。"""
        cfg.set(cfg.selectionExplainPrompt, "")
        action = get_text_action("explain")
        self._edit.setPlainText(action.default_prompt if action else "")

    def save(self):
        """供设置窗口在确定时统一调用。"""
        self._save()


class SelectionPage(QScrollArea):
    """划词设置：浮标开关、动作显隐、解释提示词。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.Shape.NoFrame)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        group = SettingCardGroup("划词", container)

        group.addSettingCard(
            SwitchSettingCard(
                FluentIcon.QUICK_NOTE,
                "划词浮标",
                "在任意应用选中文字后，光标旁自动弹出动作条",
                configItem=cfg.selectionFloatEnabled,
                parent=self,
            )
        )
        group.addSettingCard(
            SwitchSettingCard(
                FluentIcon.DICTIONARY,
                "显示「解释」",
                "浮标上显示解释动作（就地解释选中文字的含义）",
                configItem=cfg.selectionExplainEnabled,
                parent=self,
            )
        )
        group.addSettingCard(
            SwitchSettingCard(
                FluentIcon.CHAT,
                "显示「续入会话」",
                "浮标上显示续入会话与新建会话（把选中文填进快速会话，自己补指令再发）",
                configItem=cfg.selectionContinueExplainEnabled,
                parent=self,
            )
        )
        group.addSettingCard(
            SwitchSettingCard(
                FluentIcon.QUICK_NOTE,
                "显示「存便签」",
                "浮标上显示存便签动作（把选中文字直接存入笔记库）",
                configItem=cfg.selectionNoteEnabled,
                parent=self,
            )
        )

        layout.addWidget(group)

        # 解释提示词区：标题 + 自定义卡片，直接挂在页面布局上。
        # 注意不要塞进 SettingCardGroup 的 ExpandLayout——它会把高度压扁，
        # 导致编辑框只剩一条线（之前的显示问题就是这么来的）。
        prompt_title = StrongBodyLabel("解释提示词", container)
        layout.addWidget(prompt_title)
        self._prompt_card = _ExplainPromptCard(container)
        layout.addWidget(self._prompt_card)

        layout.addStretch()
        self.setWidget(container)

    def save(self):
        self._prompt_card.save()
