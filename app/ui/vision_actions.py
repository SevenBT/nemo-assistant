"""截图识图动作定义。

每个动作 = 一个发给多模态模型的预设：图标、标签、预填提示词。
截图工具栏据此生成识图按钮；未来其他入口（如划词截图）可复用同一份。

这条路径与本地 OCR 识字完全独立（见 docs/TODO_SCREENSHOT_AI.md）：
识图发的是图片像素，OCR 识字走 _reconstruct_layout 提文字，互不为兜底。
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class VisionAction:
    """One screenshot-to-AI preset.

    Attributes:
        key: stable identifier, used in the ``captured`` action string as
            ``"vision:<key>"``.
        icon: emoji shown on the toolbar button.
        label: short button caption.
        prompt: text prefilled into the chat input alongside the image.
        session_title: title for the fresh session this action creates.
    """
    key: str
    icon: str
    label: str
    prompt: str
    session_title: str

    @property
    def action_id(self) -> str:
        return f"vision:{self.key}"

    @property
    def auto_send(self) -> bool:
        """有预设提示词的动作自动发送；通用 "问AI" 留空，等用户输入。"""
        return bool(self.prompt)


# Default action set. "ask" is the general catch-all; the rest are presets.
VISION_ACTIONS: tuple[VisionAction, ...] = (
    VisionAction(
        key="ask",
        icon="🤖",
        label="问AI",
        prompt="",  # 通用：不预填，让用户自己写问题
        session_title="问AI",
    ),
    VisionAction(
        key="explain",
        icon="💡",
        label="解释",
        prompt="请解释这张图片的内容。",
        session_title="解释截图",
    ),
    VisionAction(
        key="translate",
        icon="🌐",
        label="翻译",
        prompt="请翻译图片中的文字，保持原有的排版结构。",
        session_title="翻译截图",
    ),
    VisionAction(
        key="solve",
        icon="✏️",
        label="解题",
        prompt="请解答图片中的题目，给出详细步骤。",
        session_title="解题截图",
    ),
    VisionAction(
        key="table",
        icon="📊",
        label="转表格",
        prompt="请把图片中的表格转换成 Markdown 表格，保持行列结构。",
        session_title="转表格截图",
    ),
)

_ACTION_BY_KEY = {a.key: a for a in VISION_ACTIONS}


def get_vision_action(key: str) -> VisionAction | None:
    """Look up a vision action by its key (the part after ``vision:``)."""
    return _ACTION_BY_KEY.get(key)
