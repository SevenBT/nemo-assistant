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


@dataclass(frozen=True)
class TextAction:
    """One selected-text-to-action preset.

    Attributes:
        key: stable identifier, used in the popup's action string.
        icon: FluentIcon shown on the popup button.
        label: short button caption (also used as tooltip).
        default_prompt: text sent to chat, with ``{text}`` filled by the
            selection. 用户可在设置页覆盖（见 render）。空串表示该动作不走
            LLM（如「存便签」）——调用方按 key 自行处理。
        session_title: title for the fresh chat session this action creates.
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
    label: str
    default_prompt: str
    session_title: str
    mode: str = "oneshot"

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
_POLISH_PROMPT = (
    "润色下面这段文字，使其更通顺自然、表达更准确，保持原意与语言。"
    "只输出润色后的文字，不要任何解释、前后缀或代码块包裹：\n\n{text}"
)
_TRANSLATE_PROMPT = (
    "翻译下面这段文字：是中文就译成英文，是其他语言就译成中文。"
    "只输出译文，不要任何解释、前后缀或代码块包裹：\n\n{text}"
)
_FIX_GRAMMAR_PROMPT = (
    "修正下面这段文字里的错别字、标点和语法错误，保持原意、风格和语言不变。"
    "只输出修正后的文字，不要任何解释、前后缀或代码块包裹：\n\n{text}"
)

TEXT_ACTIONS: tuple[TextAction, ...] = (
    TextAction(
        key="explain",
        icon=FluentIcon.DICTIONARY,
        label="解释",
        default_prompt=_EXPLAIN_PROMPT,
        session_title="解释选中",
        mode="oneshot",
    ),
    TextAction(
        key="continue_explain",
        icon=FluentIcon.CHAT,
        label="续入会话",
        default_prompt="",  # compose：无预设提示词，用户自己加指令
        session_title="快速会话",
        mode="compose",
    ),
    TextAction(
        key="new_continue_explain",
        icon=FluentIcon.ADD,
        label="新建会话",
        default_prompt="",  # compose：无预设提示词
        session_title="快速会话",
        mode="compose_new",
    ),
    TextAction(
        key="polish",
        icon=FluentIcon.EDIT,
        label="润色",
        default_prompt=_POLISH_PROMPT,
        session_title="润色改写",
        mode="rewrite",
    ),
    TextAction(
        key="translate_inplace",
        icon=FluentIcon.LANGUAGE,
        label="翻译",
        default_prompt=_TRANSLATE_PROMPT,
        session_title="翻译",
        mode="rewrite",
    ),
    TextAction(
        key="fix_grammar",
        icon=FluentIcon.ACCEPT,
        label="订正",
        default_prompt=_FIX_GRAMMAR_PROMPT,
        session_title="订正改写",
        mode="rewrite",
    ),
    TextAction(
        key="note",
        icon=FluentIcon.QUICK_NOTE,
        label="存便签",
        default_prompt="",  # 本地：不走 AI，直接写入笔记库
        session_title="",
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
