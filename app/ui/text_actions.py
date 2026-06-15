"""划词动作定义。

每个动作 = 针对一段选中文字的预设：图标、标签、预填提示词。
划词浮标据此生成动作按钮；热键路径与浮标路径复用同一份。

与识图动作（vision_actions.py）平行：那边发的是图片像素，这边发的是
选中的纯文本。prompt 中用 {text} 占位，运行时填入选中内容。

prompt 为空的动作（如「存便签」）不走 AI，由调用方按 key 自行处理。
"""
from dataclasses import dataclass

from app.core.config import cfg


@dataclass(frozen=True)
class TextAction:
    """One selected-text-to-action preset.

    Attributes:
        key: stable identifier, used in the popup's action string.
        icon: emoji shown on the popup button.
        label: short button caption.
        prompt: text sent to chat, with ``{text}`` filled by the selection.
            可含 ``{target}`` 占位（翻译目标语言），运行时从配置填入。
            Empty string means this action does NOT go through the LLM
            (e.g. "save as note") — the caller dispatches by key instead.
        session_title: title for the fresh chat session this action creates.
    """
    key: str
    icon: str
    label: str
    prompt: str
    session_title: str

    @property
    def goes_to_ai(self) -> bool:
        """有预设提示词的动作走 LLM；prompt 为空的（存便签）本地处理。"""
        return bool(self.prompt)

    def render(self, text: str) -> str:
        """Fill the {text} placeholder with the captured selection.

        翻译动作的 {target} 占位由配置 selectionTranslateTarget 填入，
        与气泡路径共用同一份目标语言设置。
        """
        target = cfg.get(cfg.selectionTranslateTarget) or "中文"
        return self.prompt.format(text=text, target=target)


# Default action set. "note" is local (no prompt); the rest go to the LLM.
TEXT_ACTIONS: tuple[TextAction, ...] = (
    TextAction(
        key="explain",
        icon="💡",
        label="解释",
        prompt="请解释下面这段文字的含义：\n\n{text}",
        session_title="解释选中",
    ),
    TextAction(
        key="translate",
        icon="🌐",
        label="翻译",
        prompt="请将下面这段文字翻译成{target}，只输出译文：\n\n{text}",
        session_title="翻译选中",
    ),
    TextAction(
        key="note",
        icon="📌",
        label="存便签",
        prompt="",  # 本地：不走 AI，直接写入笔记库
        session_title="",
    ),
)

_ACTION_BY_KEY = {a.key: a for a in TEXT_ACTIONS}


def get_text_action(key: str) -> TextAction | None:
    """Look up a text action by its key."""
    return _ACTION_BY_KEY.get(key)
