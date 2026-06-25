"""
应用常量定义

包含 System Prompt 相关常量，避免循环导入。
"""

import datetime


def get_current_datetime_info() -> str:
    """获取稳定的日期信息，用于 system prompt。

    只到「日期 + 星期 + 时区」粒度，一天内不变，从而不破坏请求前缀缓存。
    精确到分钟的时间由 get_current_time_hint() 附在最新消息尾部。
    """
    now = datetime.datetime.now()
    weekday = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][now.weekday()]
    tz = now.astimezone().tzname()
    return f"""
【当前日期信息】
日期: {now.strftime("%Y-%m-%d")}
星期: {weekday}
时区: {tz}
"""


def get_current_time_hint() -> str:
    """获取精确到分钟的当前时间，附在最新一条消息尾部。

    时间每分钟变化，单独放在请求末尾，避免污染前面可缓存的稳定前缀。
    """
    now = datetime.datetime.now()
    return f"[当前时间: {now.strftime('%Y-%m-%d %H:%M')}]"


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

【笔记】使用 note 工具：
- action=list 查看用户的笔记列表和内容预览。
- action=create 新建笔记（需 title + content）。
- 需要把当前对话总结成笔记时，自己生成总结文本作为 content，用 action=create 保存。

【记忆】使用 memory 工具：
- action=save 保存记忆（需 content + category），用于记住用户偏好、项目决策、重要事实。
- action=recall 查看已记住的信息（可按 category/scope 过滤）。
- action=forget 删除一条记忆（需 memory_id）。
- 分类：user（用户偏好）、project（项目决策）、fact（具体事实）、personality（AI行为风格）。
- 范围：global（所有会话可见）、session（仅当前会话可见）。
"""
