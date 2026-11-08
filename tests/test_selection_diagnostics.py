"""诊断必须区分 UP/move 时序，且不能把选中文字或异常内容写入日志。"""
import logging
import time
from types import SimpleNamespace

import pytest
from PyQt6.QtCore import QRect
from mouse import ButtonEvent, MoveEvent

from app.core import selection_monitor as monitor_module
from app.core import selection_uia as uia
from app.ui import global_click_watcher as click_module


@pytest.mark.parametrize("start,end", [((200, 200), (100, 100)), ((100, 100), (200, 200))])
def test_up_ends_gesture_without_movement_despite_stale_physical_state(monkeypatch, caplog, start, end):
    monitor = monitor_module.SelectionMonitor()
    emitted = []
    monitor._maybe_emit = lambda x, y: emitted.append((x, y))
    monkeypatch.setattr(monitor_module, "is_text_cursor", lambda: True)
    monkeypatch.setattr(monitor_module, "_foreground_identity", lambda: (123, 456))
    down = [False]  # DOWN 回调时异步状态也可能尚未更新
    monkeypatch.setattr(monitor_module, "is_left_button_physically_down", lambda: down[0])
    position = [start]
    monkeypatch.setattr(monitor_module, "_mouse", SimpleNamespace(get_position=lambda: position[0]))
    ticks = [10.0]
    monkeypatch.setattr(monitor_module.time, "perf_counter", lambda: ticks[0])
    monkeypatch.setattr(monitor_module.time, "monotonic", lambda: ticks[0])
    caplog.set_level(logging.INFO)

    def event(kind, x, y):
        position[0] = (x, y)
        if kind == "move":
            return MoveEvent(x, y, time.time() - 0.4)
        return ButtonEvent(kind, "left", time.time() - 0.4)

    monitor._on_event(event("down", *start))
    down[0] = True
    ticks[0] = 10.1
    monitor._on_event(event("move", *end))
    ticks[0] = 10.2
    monitor._on_event(event("up", *end))  # UP 到达时，读取的物理状态仍为按下
    assert emitted == [end]
    assert monitor._press_pending is False
    down[0] = False
    ticks[0] = 11.2
    monitor._on_event(event("move", *end))
    monitor._on_event(event("up", *end))  # 重复 UP 不能再次触发

    assert emitted == [end]
    messages = [r.getMessage() for r in caplog.records]
    up = next(m for m in messages if "stage=button_event" in m and "event=up" in m)
    assert "physical_down=True" in up and "pending=True" in up
    ended = next(m for m in messages if "stage=gesture " in m)
    assert "accepted=True" in ended and "end_event=up" in ended
    assert "up_seen=True" in ended and "up_to_release_ms=0.00" in ended
    assert "event_age_ms=400." in ended
    assert f"gesture_id={monitor._gesture_id}" in ended


@pytest.mark.parametrize("cursor_samples,should_show", [
    ((False, True, False), True),
    ((False, False, True), True),
    ((False, False, False), False),
])
def test_fallback_uses_drag_and_release_cursor_evidence(monkeypatch, cursor_samples, should_show):
    monitor = monitor_module.SelectionMonitor()
    emitted = []
    monitor.selection_gesture.connect(lambda *args: emitted.append(args))
    samples = iter(cursor_samples)
    monkeypatch.setattr(monitor_module, "is_text_cursor", lambda: next(samples))
    monkeypatch.setattr(monitor_module, "is_left_button_physically_down", lambda: True)
    monkeypatch.setattr(monitor_module, "caret_hotspot_to_bottom", lambda: 10)
    monkeypatch.setattr(uia, "query_selection", lambda *, point: (uia.SelectionStatus.NO_TEXT_PATTERN, ""))
    for kind, x, y in [("down", 200, 200), ("move", 100, 100), ("up", 100, 100)]:
        monitor._on_event(SimpleNamespace(event_type=kind, button="left" if kind != "move" else "none",
                                          x=x, y=y, time=time.time()))
    assert emitted == ([(150, 210, "")] if should_show else [])


def test_uia_logs_call_boundaries_without_selection_or_exception_content(caplog):
    class Range:
        def GetText(self, limit):
            return "PRIVATE_SELECTED_SENTINEL"

    class Pattern:
        def GetSelection(self):
            return [Range()]

    class Control:
        def GetTextPattern(self):
            return Pattern()

    caplog.set_level(logging.INFO)
    assert uia._selection_via_text_pattern(Control())[1] == "PRIVATE_SELECTED_SENTINEL"
    assert "operation=range_text:0" in caplog.text
    assert "stage=uia_step_begin" in caplog.text and "stage=uia_step_done" in caplog.text
    assert "PRIVATE_SELECTED_SENTINEL" not in caplog.text

    class BrokenControl:
        def GetTextPattern(self):
            raise RuntimeError("PRIVATE_EXCEPTION_SENTINEL")

    assert uia._selection_via_text_pattern(BrokenControl())[0] == uia.SelectionStatus.NO_TEXT_PATTERN
    assert "stage=uia_step_error" in caplog.text and "exception_type=RuntimeError" in caplog.text
    assert "PRIVATE_EXCEPTION_SENTINEL" not in caplog.text


def test_uia_uses_generic_pattern_and_bounding_rectangle_methods(caplog, monkeypatch):
    class Range:
        def GetText(self, _limit):
            return "generic"

        def GetBoundingRectangles(self):
            return [SimpleNamespace(left=20, top=40, right=80, bottom=60),
                    SimpleNamespace(left=10, top=70, right=50, bottom=90)]

    class Pattern:
        def GetSelection(self):
            return [Range()]

    class GenericControl:
        def GetPattern(self, pattern_id):
            assert pattern_id == 10014
            return Pattern()

    class PatternIds:
        TextPattern = 10014

    monkeypatch.setattr(uia, "_auto", SimpleNamespace(PatternId=PatternIds, GetFocusedControl=GenericControl))
    monkeypatch.setattr(uia, "_UIA_OK", True)
    caplog.set_level(logging.INFO)
    status, text = uia._selection_via_text_pattern(GenericControl())
    assert status is uia.SelectionStatus.HAS_TEXT and text == "generic"
    assert "operation=text_pattern" in caplog.text
    assert "operation=range_text:0" in caplog.text

    assert uia.get_selection_bounds() == (10, 40, 80, 90)


@pytest.mark.parametrize("focused_pattern,target_pid,target_pattern,expected", [
    (None, 7, "text", uia.SelectionStatus.HAS_TEXT),
    (None, 8, "text", uia.SelectionStatus.NO_TEXT_PATTERN),
    ("empty", 7, "text", uia.SelectionStatus.EMPTY_SELECTION),
    (None, 7, "empty", uia.SelectionStatus.EMPTY_SELECTION),
    (None, 7, None, uia.SelectionStatus.HAS_TEXT),
])
def test_uia_point_fallback_respects_process_and_empty_selection(
        monkeypatch, focused_pattern, target_pid, target_pattern, expected):
    class Control:
        def __init__(self, pid, pattern, parent=None):
            self.ProcessId, self.pattern, self.parent = pid, pattern, parent

        def GetTextPattern(self):
            if self.pattern is None:
                return None
            ranges = [] if self.pattern == "empty" else [SimpleNamespace(GetText=lambda _: "selection")]
            return SimpleNamespace(GetSelection=lambda: ranges)

        def GetParentControl(self):
            return self.parent

    focused = Control(7, focused_pattern)
    target = Control(target_pid, target_pattern, Control(7, "text"))
    monkeypatch.setattr(uia, "_auto", SimpleNamespace(
        GetFocusedControl=lambda: focused, ControlFromPoint=lambda x, y: target,
    ))
    monkeypatch.setattr(uia, "_UIA_OK", True)
    status, text = uia.query_selection(point=(100, 100))
    assert status is expected
    assert text == ("selection" if expected is uia.SelectionStatus.HAS_TEXT else "")


def test_release_probe_observes_without_ending_gesture_or_emitting(monkeypatch, caplog):
    monitor = monitor_module.SelectionMonitor()
    monitor._gesture_id = "probe-gesture"
    monitor._press_pending = True
    monitor._last_probe_at = 1.0
    monitor._last_event_at = 1.1
    emitted = []
    monitor.selection_gesture.connect(lambda *args: emitted.append(args))
    monkeypatch.setattr(monitor_module.time, "perf_counter", lambda: 1.5)
    monkeypatch.setattr(monitor_module, "is_left_button_physically_down", lambda: False)
    caplog.set_level(logging.INFO)
    monitor._diagnostic_probe()
    monitor._diagnostic_probe()
    assert monitor._press_pending is True and emitted == []
    messages = [r.getMessage() for r in caplog.records]
    assert sum("stage=release_probe " in m for m in messages) == 1
    assert "up_seen=False" in caplog.text and "last_event_gap_ms=400.00" in caplog.text
    assert "stage=qt_probe_late" in caplog.text and "tick_gap_ms=500.00" in caplog.text


def test_global_click_logs_inside_and_outside_without_changing_hide_rule(monkeypatch, caplog):
    position = [(20, 20)]
    monkeypatch.setattr(click_module, "_mouse", SimpleNamespace(
        LEFT="left", RIGHT="right", get_position=lambda: position[0],
    ))
    hidden = []
    watcher = click_module.GlobalClickWatcher(
        geometry_provider=lambda: QRect(10, 10, 40, 40),
        on_hide_requested=lambda: hidden.append(True),
    )
    watcher.diagnostic_id = "test-popup"
    caplog.set_level(logging.INFO)
    event = SimpleNamespace(event_type="down", button="left", time=time.time())
    watcher._on_global_event(event)
    assert hidden == []
    assert "inside=True" in caplog.text
    position[0] = (200, 200)
    watcher._on_global_event(event)
    assert hidden == [True]
    assert "inside=False" in caplog.text and "reason=outside_click" in caplog.text
    assert "popup_id=test-popup" in caplog.text
