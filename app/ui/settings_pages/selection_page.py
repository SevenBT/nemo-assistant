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
from app.i18n import t
from app.ui.text_actions import get_text_action

# 解释提示词编辑器高度（px）。
_PROMPT_EDIT_HEIGHT = 120


class _PromptCard(CardWidget):
    """某个走 AI 的划词动作的自定义提示词卡片：多行编辑 + 恢复默认。

    失焦即写回对应的 cfg 配置项（空串表示用内置默认）。占位提示里说明
    {text} 会被选中文字替换、留空则附在末尾。一张卡片服务一个动作
    （解释 / 润色 / 翻译 / 订正），由 action_key + config_attr 参数化。
    """

    def __init__(self, action_key: str, config_attr: str, hint_text: str, parent=None):
        super().__init__(parent)
        self._action_key = action_key
        self._config_attr = config_attr
        self._hint_text = hint_text
        self._build()
        self._load()

    @property
    def _config_item(self):
        return getattr(cfg, self._config_attr)

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        hint = BodyLabel(self._hint_text, self)
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self._edit = TextEdit(self)
        self._edit.setFixedHeight(_PROMPT_EDIT_HEIGHT)
        self._edit.setPlaceholderText(t("settings.selection.promptPlaceholder"))
        # 失焦写回，避免每次按键都落盘
        self._edit.focusOutEvent = self._wrap_focus_out(self._edit.focusOutEvent)
        layout.addWidget(self._edit)

        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 0, 0, 0)
        btn_row.addStretch()
        self._reset_btn = PrimaryPushButton(t("settings.selection.restoreDefault"), self)
        self._reset_btn.clicked.connect(self._restore_default)
        btn_row.addWidget(self._reset_btn)
        layout.addLayout(btn_row)

    def _wrap_focus_out(self, original):
        def handler(event):
            self._save()
            original(event)
        return handler

    def _load(self):
        self._edit.setPlainText(cfg.get(self._config_item) or "")

    def _save(self):
        cfg.set(self._config_item, self._edit.toPlainText().strip())

    def _restore_default(self):
        """清空自定义提示词（回到内置默认），并把默认文案填入编辑器作参考。"""
        cfg.set(self._config_item, "")
        action = get_text_action(self._action_key)
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

        group = SettingCardGroup(t("settings.selection.group"), container)

        group.addSettingCard(
            SwitchSettingCard(
                FluentIcon.QUICK_NOTE,
                t("settings.selection.float"),
                t("settings.selection.float.desc"),
                configItem=cfg.selectionFloatEnabled,
                parent=self,
            )
        )
        group.addSettingCard(
            SwitchSettingCard(
                FluentIcon.DICTIONARY,
                t("settings.selection.explain"),
                t("settings.selection.explain.desc"),
                configItem=cfg.selectionExplainEnabled,
                parent=self,
            )
        )
        group.addSettingCard(
            SwitchSettingCard(
                FluentIcon.CHAT,
                t("settings.selection.continue"),
                t("settings.selection.continue.desc"),
                configItem=cfg.selectionContinueExplainEnabled,
                parent=self,
            )
        )
        group.addSettingCard(
            SwitchSettingCard(
                FluentIcon.QUICK_NOTE,
                t("settings.selection.note"),
                t("settings.selection.note.desc"),
                configItem=cfg.selectionNoteEnabled,
                parent=self,
            )
        )
        group.addSettingCard(
            SwitchSettingCard(
                FluentIcon.EDIT,
                t("settings.selection.rewrite"),
                t("settings.selection.rewrite.desc"),
                configItem=cfg.selectionRewriteEnabled,
                parent=self,
            )
        )
        group.addSettingCard(
            SwitchSettingCard(
                FluentIcon.ACCEPT,
                t("settings.selection.verify"),
                t("settings.selection.verify.desc"),
                configItem=cfg.selectionRewriteVerify,
                parent=self,
            )
        )

        layout.addWidget(group)

        # 各动作提示词区：标题 + 自定义卡片，直接挂在页面布局上。
        # 注意不要塞进 SettingCardGroup 的 ExpandLayout——它会把高度压扁，
        # 导致编辑框只剩一条线（之前的显示问题就是这么来的）。
        self._prompt_cards = []
        for title, action_key, config_attr, hint in (
            (t("settings.selection.prompt.explain"), "explain", "selectionExplainPrompt",
             t("settings.selection.prompt.explain.hint")),
            (t("settings.selection.prompt.polish"), "polish", "selectionPolishPrompt",
             t("settings.selection.prompt.polish.hint")),
            (t("settings.selection.prompt.translate"), "translate_inplace", "selectionTranslatePrompt",
             t("settings.selection.prompt.translate.hint")),
            (t("settings.selection.prompt.fix"), "fix_grammar", "selectionFixGrammarPrompt",
             t("settings.selection.prompt.fix.hint")),
        ):
            label = StrongBodyLabel(title, container)
            layout.addWidget(label)
            card = _PromptCard(action_key, config_attr, hint, container)
            layout.addWidget(card)
            self._prompt_cards.append(card)

        layout.addStretch()
        self.setWidget(container)

    def save(self):
        for card in self._prompt_cards:
            card.save()
