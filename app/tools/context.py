"""
工具上下文 — 依赖注入容器。

设计思路：
  旧架构中，每个工具在构造时需要传入各种依赖（config、note_mgr、scheduler...），
  导致工具注册代码冗长且耦合严重。

  新架构引入 ToolContext 作为统一的资源容器：
    1. MainWindow 在启动时创建一个 ToolContext，填入所有共享资源
    2. loader.py 调用每个工具类的 create(ctx) 工厂方法
    3. 工具从 ctx 中按需取出自己需要的依赖

  好处：
    - 新增共享资源只需在 ToolContext 加一个字段，不影响已有工具
    - 简单工具（如 calculator）完全不需要 ctx，默认 create() 直接 cls()
    - 测试时可以传入 mock 的 ToolContext
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.ai_client import AIClient
    from app.core.note_manager import NoteManager
    from app.core.scheduler import SchedulerManager


@dataclass
class ToolEvents:
    note_created: Callable[[], None] | None = None


@dataclass
class ToolContext:
    """
    统一上下文容器，通过工厂方法 create(ctx) 注入到每个内置工具。

    字段说明：
      config:          AppConfig 实例，提供全局配置读取
      workspace:       工作目录路径（预留，未来可用于文件操作工具的沙箱限制）
      note_mgr:        笔记管理器，供笔记相关工具使用
      scheduler:       定时任务管理器，供 scheduler 工具使用
      ai_client:       AI 客户端，供多模型咨询等工具使用
      events:          工具事件回调集合（如笔记创建后触发 UI 刷新）
      http_timeout:    HTTP 请求超时秒数，供网络工具使用
      proxy:           HTTP 代理地址（预留）
      extra:           扩展字典，用于传递非标准依赖
    """
    config: Any  # AppConfig 实例（避免循环导入，用 Any）
    workspace: Path = field(default_factory=lambda: Path("."))

    note_mgr: "NoteManager | None" = None
    scheduler: "SchedulerManager | None" = None
    ai_client: "AIClient | None" = None

    events: ToolEvents = field(default_factory=ToolEvents)

    http_timeout: int = 20
    proxy: str | None = None

    extra: dict[str, Any] = field(default_factory=dict)
