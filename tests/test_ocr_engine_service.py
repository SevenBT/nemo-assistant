"""Tests for the shared, single-flight OCR engine lifecycle."""
from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import pytest

from app.content.file_parser import FileParser
from app.content.ocr_engine import OcrEngineService
from app.ui.screenshot_overlay import ScreenshotOverlay


def _wait_until(predicate, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition was not met before timeout")


class _SuccessfulService:
    def __init__(self, engine):
        self.engine = engine

    def get_engine(self):
        return self.engine


class _FakeEngine:
    def __call__(self, _image):
        return [[[[0, 0], [10, 0], [10, 10], [0, 10]], "识别结果", 0.99]], 0.01


def test_concurrent_get_engine_initializes_only_once():
    calls = 0
    calls_lock = threading.Lock()
    release_factory = threading.Event()
    factory_started = threading.Event()
    engine = object()

    def factory():
        nonlocal calls
        with calls_lock:
            calls += 1
        factory_started.set()
        assert release_factory.wait(2)
        return engine

    service = OcrEngineService(factory=factory)
    assert service.warm_async() is True
    assert factory_started.wait(1)
    assert service.warm_async() is False

    results = []
    threads = [
        threading.Thread(target=lambda: results.append(service.get_engine(2)))
        for _ in range(4)
    ]
    for thread in threads:
        thread.start()
    release_factory.set()
    for thread in threads:
        thread.join(timeout=2)

    assert calls == 1
    assert results == [engine] * 4
    assert service.is_ready


def test_failed_warmup_retries_on_next_request():
    engine = object()
    attempts = 0

    def factory():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("first load failed")
        return engine

    service = OcrEngineService(factory=factory)
    assert service.warm_async() is True
    _wait_until(lambda: service.state.value == "failed")

    assert service.get_engine(timeout=2) is engine
    assert attempts == 2
    assert service.is_ready


def test_file_parser_uses_injected_shared_engine():
    engine = object()
    parser = FileParser(ocr_engine_service=_SuccessfulService(engine))

    assert parser.ocr_engine is engine


def test_screenshot_ocr_consumes_shared_engine():
    overlay = SimpleNamespace(
        _ocr_engine_service=_SuccessfulService(_FakeEngine())
    )

    assert "识别结果" in ScreenshotOverlay._run_ocr_from_array(overlay, object())


def test_timeout_does_not_duplicate_loading_task():
    release_factory = threading.Event()
    calls = 0

    def factory():
        nonlocal calls
        calls += 1
        release_factory.wait(2)
        return object()

    service = OcrEngineService(factory=factory)
    assert service.warm_async() is True

    with pytest.raises(TimeoutError):
        service.get_engine(timeout=0.01)

    assert service.warm_async() is False
    release_factory.set()
    _wait_until(lambda: service.is_ready)
    assert calls == 1
