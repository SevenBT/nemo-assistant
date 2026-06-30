"""截图识图动作定义。

每个动作 = 一个发给多模态模型的预设：图标、标签、预填提示词。
截图工具栏据此生成识图按钮；未来其他入口（如划词截图）可复用同一份。

这条路径与本地 OCR 识字完全独立（见 docs/TODO_SCREENSHOT_AI.md）：
识图发的是图片像素，OCR 识字走 _reconstruct_layout 提文字，互不为兜底。
"""
from dataclasses import dataclass

from app.i18n import t


@dataclass(frozen=True)
class VisionAction:
    """One screenshot-to-AI preset.

    展示文案（标签 / 会话标题 / 提示词）一律存 i18n key，在属性里运行时
    取 t()。模块级常量在 import 时构建，那时语言尚未锁定（init_language 在
    QApplication 之后才调），所以绝不能在构造期调 t()，必须延后到访问时。

    Attributes:
        key: stable identifier, used in the ``captured`` action string as
            ``"vision:<key>"``.
        icon: emoji shown on the toolbar button.
        label_key: i18n key for the short button caption.
        title_key: i18n key for the fresh session's title.
        prompt_key: i18n key for the text prefilled alongside the image;
            empty means no preset prompt (the general "ask" action).
    """
    key: str
    icon: str
    label_key: str
    title_key: str
    prompt_key: str = ""

    @property
    def label(self) -> str:
        """按当前语言取按钮标签。"""
        return t(self.label_key)

    @property
    def session_title(self) -> str:
        """按当前语言取新建会话标题。"""
        return t(self.title_key)

    @property
    def prompt(self) -> str:
        """按当前语言取预设提示词；无预设（通用问AI）时返回空串。"""
        return t(self.prompt_key) if self.prompt_key else ""

    @property
    def action_id(self) -> str:
        return f"vision:{self.key}"

    @property
    def auto_send(self) -> bool:
        """有预设提示词的动作自动发送；通用 "问AI" 留空，等用户输入。"""
        return bool(self.prompt)


# Default action set. "ask" is the general catch-all; the rest are presets.
# 仅存 key；展示文案在属性里运行时取 t()，故顺序/语言无关。
VISION_ACTIONS: tuple[VisionAction, ...] = (
    VisionAction(
        key="ask",
        icon="🤖",
        label_key="vision.ask.label",
        title_key="vision.ask.title",
        prompt_key="",  # 通用：不预填，让用户自己写问题
    ),
    VisionAction(
        key="explain",
        icon="💡",
        label_key="vision.explain.label",
        title_key="vision.explain.title",
        prompt_key="vision.explain.prompt",
    ),
    VisionAction(
        key="translate",
        icon="🌐",
        label_key="vision.translate.label",
        title_key="vision.translate.title",
        prompt_key="vision.translate.prompt",
    ),
    VisionAction(
        key="solve",
        icon="✏️",
        label_key="vision.solve.label",
        title_key="vision.solve.title",
        prompt_key="vision.solve.prompt",
    ),
    VisionAction(
        key="table",
        icon="📊",
        label_key="vision.table.label",
        title_key="vision.table.title",
        prompt_key="vision.table.prompt",
    ),
)

_ACTION_BY_KEY = {a.key: a for a in VISION_ACTIONS}


def get_vision_action(key: str) -> VisionAction | None:
    """Look up a vision action by its key (the part after ``vision:``)."""
    return _ACTION_BY_KEY.get(key)
