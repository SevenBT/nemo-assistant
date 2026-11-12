"""LiteLLM 延迟加载器 —— 统一 import 入口，避免启动联网与错误归因偏差。

为什么需要它：
  1. litellm 首次 import 时会去 GitHub 拉取 model_prices_and_context_window.json，
     网络不通时会卡满整个超时（实测 ~13s）才回退本地备份，表现为"卡死"。
     设 LITELLM_LOCAL_MODEL_COST_MAP=True 让它直接用包内本地价格表，import 降到亚秒。
     该环境变量必须在 import litellm 之前设置，故集中在此处理。
  2. 各调用点原先 `except ImportError -> "未安装，请 pip install"` 是错误归因：
     litellm 装着、但其依赖缺失或其它原因导致的 ImportError 也会被误报成"未安装"。
     这里区分"顶层 litellm 真缺失" vs "导入时其它异常"，给出准确信息。
"""
from __future__ import annotations

import importlib.util
import logging
import os
import threading
import time
from typing import Any

# 缓存已加载的 litellm 模块，避免重复设置环境变量与重复 import 开销。
_litellm: Any = None
_load_lock = threading.Lock()
_warmup_lock = threading.Lock()
_warmup_thread: threading.Thread | None = None
logger = logging.getLogger(__name__)


class LiteLLMUnavailableError(ImportError):
    """litellm 不可用。message 已是面向用户的可读说明。"""


def load_litellm() -> Any:
    """加载并返回 litellm 模块。

    Raises:
        LiteLLMUnavailableError: 顶层包缺失（真没装），或导入时发生其它异常。
            其 message 区分两种情况，便于用户对症处理。
    """
    if _litellm is not None:
        return _litellm

    # Startup warmup and an early user request must share one initialization.
    with _load_lock:
        if _litellm is not None:
            return _litellm
        return _import_litellm()


def _import_litellm() -> Any:
    global _litellm

    # 必须在 import litellm 之前设置，禁用启动时的远程价格表拉取。
    os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")

    # 先区分"顶层包是否存在"，避免把"装了但导入出错"误报成"没装"。
    if importlib.util.find_spec("litellm") is None:
        raise LiteLLMUnavailableError("LiteLLM 未安装，请运行: pip install litellm")

    try:
        import litellm  # noqa: PLC0415  (延迟 import 是本模块的设计目的)
    except Exception as e:  # 装了但导入失败（依赖缺失 / 版本冲突等）
        raise LiteLLMUnavailableError(
            f"LiteLLM 已安装但导入失败（可能依赖缺失或版本冲突）: {e}"
        ) from e

    _litellm = litellm
    return litellm


def warm_litellm_async() -> bool:
    """Preload the shared SDK locally without inference or credential access.

    Returns whether a background task started. Failures leave normal loading
    retryable, so a startup failure never prevents a later user request.
    """
    global _warmup_thread
    with _warmup_lock:
        if _litellm is not None or (
            _warmup_thread is not None and _warmup_thread.is_alive()
        ):
            return False
        thread = threading.Thread(
            target=_warm_litellm, name="llm-sdk-warmup", daemon=True
        )
        _warmup_thread = thread
        try:
            thread.start()
        except Exception:
            _warmup_thread = None
            logger.debug("Unable to start LLM SDK warmup", exc_info=True)
            return False
        return True


def _warm_litellm() -> None:
    started = time.perf_counter()
    try:
        load_litellm()
    except Exception:
        logger.debug("LLM SDK warmup failed; will retry on demand", exc_info=True)
    else:
        logger.info("LLM SDK ready in %.0fms", (time.perf_counter() - started) * 1000)
