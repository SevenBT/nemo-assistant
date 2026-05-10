"""
应用常量定义

包含 System Prompt 相关常量，避免循环导入。
"""

import datetime


def get_current_datetime_info() -> str:
    """获取当前日期时间信息，用于 system prompt"""
    now = datetime.datetime.now()
    weekday = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][now.weekday()]
    tz = now.astimezone().tzname()
    return f"""
【当前时间信息】
日期时间: {now.strftime("%Y-%m-%d %H:%M:%S")}
星期: {weekday}
时区: {tz}
"""


# 默认的用户可编辑部分（当配置为空时使用）
DEFAULT_USER_PROMPT = """你是一个智能AI助手。你可以调用工具来帮助用户完成任务。

请用中文回复。"""

# 内置工具说明（不可编辑，自动追加）
BUILTIN_TOOLS_INSTRUCTION = """
【定时任务】
如果用户想创建定时任务，使用 create_scheduled_task 工具。触发器配置示例：
- 每天9点: {"trigger_type": "cron", "trigger_config": {"hour": 9, "minute": 0}}
- 每小时: {"trigger_type": "interval", "trigger_config": {"hours": 1}}
- 一次性: {"trigger_type": "date", "trigger_config": {"run_date": "2025-12-31 09:00:00"}}

【列出定时任务】使用 list_scheduled_tasks 工具。
【删除定时任务】使用 delete_scheduled_task 工具，提供 job_id 参数。

【笔记】
- 使用 read_notes 查看用户的笔记列表和内容预览。
- 使用 create_note 为用户保存一条新笔记（title + content）。
- 使用 summarize_session_as_note 将当前对话总结后保存为笔记。
"""
