"""Thread-safe, shared RapidOCR engine lifecycle.

The OCR engine is expensive to import and construct.  This service makes the
initialization single-flight so startup warmup and an early OCR request share
the same loading task instead of constructing multiple engines.
"""
from __future__ import annotations

import logging
import sys
import threading
import time
from collections.abc import Callable
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class OcrEngineState(str, Enum):
    UNINITIALIZED = "uninitialized"
    LOADING = "loading"
    READY = "ready"
    FAILED = "failed"


class OcrEngineLoadError(RuntimeError):
    """Raised when the OCR engine cannot be initialized."""


class OcrEngineService:
    """Own one lazily initialized OCR engine for the whole application."""

    def __init__(self, factory: Callable[[], Any] | None = None):
        self._factory = factory or self._default_factory
        self._lock = threading.Lock()
        self._ready = threading.Event()
        self._engine: Any = None
        self._error: Exception | None = None
        self._thread: threading.Thread | None = None
        self._state = OcrEngineState.UNINITIALIZED

    @staticmethod
    def _default_factory() -> Any:
        from rapidocr_onnxruntime import RapidOCR

        return RapidOCR()

    @property
    def state(self) -> OcrEngineState:
        with self._lock:
            return self._state

    @property
    def is_ready(self) -> bool:
        return self.state is OcrEngineState.READY

    def warm_async(self) -> bool:
        """Start loading without blocking; return whether a new task started."""
        with self._lock:
            return self._start_locked()

    def get_engine(self, timeout: float | None = None) -> Any:
        """Return the shared engine, waiting for an in-flight initialization."""
        with self._lock:
            if self._state is OcrEngineState.READY:
                return self._engine
            self._start_locked()
            ready = self._ready

        if not ready.wait(timeout):
            raise TimeoutError("OCR 引擎初始化超时")

        with self._lock:
            if self._state is OcrEngineState.READY:
                return self._engine
            error = self._error
        raise OcrEngineLoadError(f"OCR 引擎初始化失败: {error}") from error

    def _start_locked(self) -> bool:
        if self._state in (OcrEngineState.LOADING, OcrEngineState.READY):
            return False

        self._state = OcrEngineState.LOADING
        self._error = None
        self._ready.clear()
        self._thread = threading.Thread(
            target=self._load,
            daemon=True,
            name="ocr-engine-loader",
        )
        self._thread.start()
        return True

    def _load(self) -> None:
        self._lower_thread_priority()
        started = time.perf_counter()
        try:
            engine = self._factory()
        except Exception as exc:
            with self._lock:
                self._error = exc
                self._state = OcrEngineState.FAILED
            logger.warning(
                "OCR 引擎初始化失败，用时 %.0fms: %s",
                (time.perf_counter() - started) * 1000,
                exc,
            )
        else:
            with self._lock:
                self._engine = engine
                self._error = None
                self._state = OcrEngineState.READY
            logger.info(
                "OCR 引擎预热完成，用时 %.0fms",
                (time.perf_counter() - started) * 1000,
            )
        finally:
            self._ready.set()

    @staticmethod
    def _lower_thread_priority() -> None:
        """Keep model initialization from competing with the UI thread."""
        if sys.platform != "win32":
            return
        try:
            import ctypes

            # THREAD_PRIORITY_BELOW_NORMAL = -1
            ctypes.windll.kernel32.SetThreadPriority(
                ctypes.windll.kernel32.GetCurrentThread(),
                -1,
            )
        except Exception:
            logger.debug("无法降低 OCR 初始化线程优先级", exc_info=True)


_shared_service: OcrEngineService | None = None
_shared_service_lock = threading.Lock()


def get_shared_ocr_engine_service() -> OcrEngineService:
    """Return the process-wide OCR engine service."""
    global _shared_service
    with _shared_service_lock:
        if _shared_service is None:
            _shared_service = OcrEngineService()
        return _shared_service
