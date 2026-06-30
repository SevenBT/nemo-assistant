"""
应用常量定义

包含 System Prompt 相关常量，避免循环导入。
"""

import datetime

from app.i18n import t


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


def get_builtin_tools_instruction() -> str:
    """内置工具说明（不可编辑，自动追加），按当前语言取。"""
    return t("prompt.builtinTools")

