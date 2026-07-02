"""
应用常量定义

包含 System Prompt 相关常量，避免循环导入。
"""

import datetime
from collections.abc import Iterable

from app.i18n import t


# 需要在 system prompt 里附带专门使用说明的工具 → 对应的 i18n 段落 key。
# 仅这些工具有额外用法说明；其余工具靠 function schema 的 description 即可，
# 不在 system prompt 里重复。段落按此表顺序拼接，保证输出稳定。
_TOOL_PROMPT_KEYS: list[tuple[str, str]] = [
    ("scheduled_task", "prompt.tool.scheduled_task"),
    ("note", "prompt.tool.note"),
    ("memory", "prompt.tool.memory"),
]


def get_current_datetime_info() -> str:
    """获取稳定的日期信息，用于 system prompt。

    只到「日期 + 星期 + 时区」粒度，一天内不变，从而不破坏请求前缀缓存。
    精确到分钟的时间由 get_current_time_hint() 附在最新消息尾部。
    """
    now = datetime.datetime.now()
    weekday = [
        t("prompt.weekday.mon"), t("prompt.weekday.tue"), t("prompt.weekday.wed"),
        t("prompt.weekday.thu"), t("prompt.weekday.fri"), t("prompt.weekday.sat"),
        t("prompt.weekday.sun"),
    ][now.weekday()]
    tz = now.astimezone().tzname()
    return t(
        "prompt.datetimeInfo",
        date=now.strftime("%Y-%m-%d"),
        weekday=weekday,
        tz=tz,
    )


def get_current_time_hint() -> str:
    """获取精确到分钟的当前时间，附在最新一条消息尾部。

    时间每分钟变化，单独放在请求末尾，避免污染前面可缓存的稳定前缀。
    """
    now = datetime.datetime.now()
    return t("prompt.timeHint", time=now.strftime('%Y-%m-%d %H:%M'))


def get_default_user_prompt() -> str:
    """默认用户可编辑部分（当配置为空时使用），按当前语言取。"""
    return t("prompt.defaultUser")


def get_builtin_tools_instruction(enabled_tools: Iterable[str] | None = None) -> str:
    """内置工具说明（不可编辑，自动追加），按当前语言取。

    只拼接**已启用**且有专门用法说明的工具段落，使 system prompt 的能力描述
    与实际可用工具保持一致——用户在能力面板关掉某工具后，模型不应再声称具备
    该能力（详见记忆 tool-disable-must-sync-prompt-and-functions）。

    Args:
        enabled_tools: 已启用工具名的集合。传 None 时拼接全部段落（向后兼容，
            用于无法拿到 registry 的调用点）。
    """
    names = None if enabled_tools is None else set(enabled_tools)
    segments = [
        t(key)
        for tool_name, key in _TOOL_PROMPT_KEYS
        if names is None or tool_name in names
    ]
    return "".join(segments)

