"""划词动作定义。

每个动作 = 针对一段选中文字的预设：图标、标签、预填提示词。
划词浮标据此生成动作按钮；热键路径与浮标路径复用同一份。

与识图动作（vision_actions.py）平行：那边发的是图片像素，这边发的是
选中的纯文本。prompt 中用 {text} 占位，运行时填入选中内容。

prompt 为空的动作（如「存便签」）不走 AI，由调用方按 key 自行处理。

显隐与提示词可由用户在「划词」设置页配置：get_active_text_actions() 返回
当前启用的动作；render() 在有自定义提示词时优先采用它。
"""
from dataclasses import dataclass

from qfluentwidgets import FluentIcon

from app.core.config import cfg
from app.i18n import t


@dataclass(frozen=True)
class TextAction:
    """One selected-text-to-action preset.

    展示文案（标签 / 会话标题 / 默认提示词）一律存 i18n key，在属性里运行时
    取 t()。模块级常量在 import 时构建（语言此时未锁定），故不能在构造期调 t()。

    Attributes:
        key: stable identifier, used in the popup's action string.
        icon: FluentIcon shown on the popup button.
        label_key: i18n key for the short button caption (also tooltip).
        prompt_key: i18n key for the text sent to chat, with ``{text}`` filled
            by the selection. 用户可在设置页覆盖（见 render）。空 key 表示该动作
            不走 LLM（如「存便签」）——调用方按 key 自行处理。
        title_key: i18n key for the fresh chat session's title (empty for local).
        mode: 处理方式——
            "oneshot"   一次性：气泡显示，不落库、无上下文（解释）；
            "compose"   续入：把选中文填进激活快速会话的输入框，等用户加
                        指令手动发（意图不限——解释/润色/答问题…）；
            "compose_new" 新建：新建并激活快速会话，再同 compose；
            "rewrite"   改写回填：气泡显示 AI 改写结果（可编辑），用户确认后
                        把结果写回源应用、覆盖原选区（润色/翻译/订正）；
            "local"     本地：不走 LLM，调用方按 key 处理（存便签）。
    """
    key: str
    icon: FluentIcon
    label_key: str
    prompt_key: str
    title_key: str
    mode: str = "oneshot"

    @property
    def label(self) -> str:
        """按当前语言取按钮标签。"""
        return t(self.label_key)

    @property
    def default_prompt(self) -> str:
        """按当前语言取内置默认提示词；无预设（compose/local）返回空串。"""
        return t(self.prompt_key) if self.prompt_key else ""

    @property
    def session_title(self) -> str:
        """按当前语言取新建会话标题。"""
        return t(self.title_key) if self.title_key else ""

    @property
    def goes_to_ai(self) -> bool:
        """有预设提示词的动作走 LLM；prompt 为空的（存便签）本地处理。"""
        return bool(self.default_prompt)

    @property
    def is_compose(self) -> bool:
        """续入/新建：填入快速会话输入框，等用户手动发（不自动请求）。"""
        return self.mode in ("compose", "compose_new")

    @property
    def is_rewrite(self) -> bool:
        """改写回填：气泡显示 AI 结果，用户确认后写回源应用覆盖原选区。"""
        return self.mode == "rewrite"

    @property
    def forces_new_reading(self) -> bool:
        """「新建会话」每次都新建并激活一个快速会话。"""
        return self.mode == "compose_new"

    def _effective_prompt(self) -> str:
        """取生效提示词：解释 / 改写动作支持自定义提示词（自定义优先，否则内置）。

        续入/新建走 compose——不预设提示词，由用户在会话里自己输入指令，
        故它们没有 prompt，render 也不会被调用。
        """
        custom_item = _CUSTOM_PROMPT_ITEM.get(self.key)
        if custom_item is not None:
            custom = (cfg.get(getattr(cfg, custom_item)) or "").strip()
            if custom:
                return custom
        return self.default_prompt

    def render(self, text: str) -> str:
        """用选中文字填充提示词。

        提示词含 {text} 占位则就地替换；不含则把选中文字附在末尾——这样
        用户写自定义提示词时即便忘了占位也能正常工作。用 replace 而非 format，
        避免自定义文本里的其它花括号触发 KeyError。
        """
        prompt = self._effective_prompt()
        if "{text}" in prompt:
            return prompt.replace("{text}", text)
        return f"{prompt}\n\n{text}"


# Default action set.
#   explain               一次性解释（气泡显示，不落库，用预设/自定义提示词）
#   continue_explain      续入会话（把选中文填进激活的快速会话，手动发，意图不限）
#   new_continue_explain  新建会话（新建并激活快速会话，再同上）
#   polish / translate_inplace / fix_grammar
#                         改写回填（气泡显示 AI 结果，确认后写回源应用覆盖原选区）
#   note                  本地（无 prompt，写入笔记库）
_EXPLAIN_PROMPT = "请用简洁的语言解释下面这段文字的含义：\n\n{text}"
# 改写类提示词统一强约束「只输出结果」——否则 AI 带「好的，这是改写后的：」之类
# 前缀，直接回填会污染原文（这是 rewrite 区别于 explain 的关键）。
# 提示词文案改由 i18n 提供（textaction.*.prompt），见 default_prompt 属性。
TEXT_ACTIONS: tuple[TextAction, ...] = (
    TextAction(
        key="explain",
        icon=FluentIcon.DICTIONARY,
        label_key="textaction.explain.label",
        prompt_key="textaction.explain.prompt",
        title_key="textaction.explain.title",
        mode="oneshot",
    ),
    TextAction(
        key="continue_explain",
        icon=FluentIcon.CHAT,
        label_key="textaction.continue.label",
        prompt_key="",  # compose：无预设提示词，用户自己加指令
        title_key="session.reading.defaultTitle",
        mode="compose",
    ),
    TextAction(
        key="new_continue_explain",
        icon=FluentIcon.ADD,
        label_key="textaction.newContinue.label",
        prompt_key="",  # compose：无预设提示词
        title_key="session.reading.defaultTitle",
        mode="compose_new",
    ),
    TextAction(
        key="polish",
        icon=FluentIcon.EDIT,
        label_key="textaction.polish.label",
        prompt_key="textaction.polish.prompt",
        title_key="textaction.polish.title",
        mode="rewrite",
    ),
    TextAction(
        key="translate_inplace",
        icon=FluentIcon.LANGUAGE,
        label_key="textaction.translate.label",
        prompt_key="textaction.translate.prompt",
        title_key="textaction.translate.title",
        mode="rewrite",
    ),
    TextAction(
        key="fix_grammar",
        icon=FluentIcon.ACCEPT,
        label_key="textaction.fix.label",
        prompt_key="textaction.fix.prompt",
        title_key="textaction.fix.title",
        mode="rewrite",
    ),
    TextAction(
        key="note",
        icon=FluentIcon.QUICK_NOTE,
        label_key="textaction.note.label",
        prompt_key="",  # 本地：不走 AI，直接写入笔记库
        title_key="",
        mode="local",
    ),
)

_ACTION_BY_KEY = {a.key: a for a in TEXT_ACTIONS}

# 每个动作对应的显隐配置项（控制浮标上是否出现该按钮）。
# 「连续解释」与「新开连续」共用一个开关（同一功能的两个入口）。
# 三个改写动作共用一个总开关（同属「改写回填」一组）。
_ENABLED_ITEM = {
    "explain": "selectionExplainEnabled",
    "continue_explain": "selectionContinueExplainEnabled",
    "new_continue_explain": "selectionContinueExplainEnabled",
    "polish": "selectionRewriteEnabled",
    "translate_inplace": "selectionRewriteEnabled",
    "fix_grammar": "selectionRewriteEnabled",
    "note": "selectionNoteEnabled",
}

# 支持自定义提示词的动作 → 对应配置项（空串表示用内置默认）。
_CUSTOM_PROMPT_ITEM = {
    "explain": "selectionExplainPrompt",
    "polish": "selectionPolishPrompt",
    "translate_inplace": "selectionTranslatePrompt",
    "fix_grammar": "selectionFixGrammarPrompt",
}


def get_text_action(key: str) -> TextAction | None:
    """Look up a text action by its key."""
    return _ACTION_BY_KEY.get(key)


def get_active_text_actions() -> tuple[TextAction, ...]:
    """返回当前启用的动作（按设置页的显隐开关过滤）。"""
    active = []
    for action in TEXT_ACTIONS:
        item_name = _ENABLED_ITEM.get(action.key)
        if item_name is None:
            active.append(action)
            continue
        if cfg.get(getattr(cfg, item_name)):
            active.append(action)
    return tuple(active)
