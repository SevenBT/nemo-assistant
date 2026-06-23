"""运行记录 / Trace 设置页 — 回放一次 Agent 运行的全链路。

数据源是独立的 traces.db（TraceStore）：每次 AgentLoop 运行 = 一个 trace_id，
贯穿其下所有 LLM 调用、工具调用、安全审计事件、评测样本与状态机流转。本页
把它们重组展示，是「可观测 + 安全 + 评测」地基的可视化出口。

布局：左侧运行列表，右侧 = 顶部概览卡 + 分段切换（SegmentedWidget）。把
LLM / 工具 / 安全 / 评测 / 状态机分到独立分页，每页结构化卡片列表，替代早期
「全部信息堆一个 Markdown 块」的混乱排版。

只读：trace 由 TraceStore 自动限容（prune），本页不提供删除，避免误删审计证据。
"""

from __future__ import annotations

from collections.abc import Callable

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QListWidgetItem,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CardWidget,
    InfoBadge,
    ListWidget,
    SegmentedWidget,
    SimpleCardWidget,
    SingleDirectionScrollArea,
    StrongBodyLabel,
    PushButton,
    FluentIcon,
    setFont,
)

# 状态 → (文案, 语义色)。语义色固定不随主题，对齐 InfoBadge 内部用色。
_STATUS = {
    "ok": ("成功", "#2e9e5b"),
    "error": ("失败", "#d03050"),
    "cancelled": ("已取消", "#9aa0a6"),
    "running": ("运行中", "#5b8def"),
}

_MAX_TURNS = 100


def _status_meta(status: str) -> tuple[str, str]:
    return _STATUS.get(status, (status or "?", "#9aa0a6"))


class TracePage(QWidget):
    """运行记录列表 + 单次运行的全链路回放。"""

    def __init__(self, trace_store=None, parent=None):
        super().__init__(parent)
        self._store = trace_store
        self._turns: list[dict] = []
        self._build()
        self.reload()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        header = QHBoxLayout()
        header.addWidget(StrongBodyLabel("运行记录", self))
        header.addStretch()
        self._refresh_btn = PushButton(FluentIcon.SYNC, "刷新", self)
        self._refresh_btn.clicked.connect(self.reload)
        header.addWidget(self._refresh_btn)
        layout.addLayout(header)

        hint = CaptionLabel(
            "每次对话运行的全链路记录。点击左侧条目查看详情。", self
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self._empty = BodyLabel("暂无运行记录。", self)
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._empty, 1)

        body = QHBoxLayout()
        body.setSpacing(12)

        self._list = ListWidget(self)
        self._list.setFixedWidth(240)
        self._list.currentRowChanged.connect(self._on_select)
        body.addWidget(self._list)

        self._detail = _TurnDetailView(self)
        body.addWidget(self._detail, 1)

        self._body_container = QWidget(self)
        self._body_container.setLayout(body)
        layout.addWidget(self._body_container, 1)

    def reload(self):
        """从 TraceStore 重新拉取最近的 turn 列表并重渲染。"""
        self._list.clear()
        self._detail.clear()
        if self._store is None or not getattr(self._store, "enabled", False):
            self._turns = []
            self._set_empty(True, "遥测未启用，无运行记录。")
            return
        self._turns = self._store.list_turns(limit=_MAX_TURNS)
        self._set_empty(not self._turns)
        for turn in self._turns:
            self._add_row(turn)
        if self._turns:
            self._list.setCurrentRow(0)

    def _set_empty(self, is_empty: bool, message: str = "暂无运行记录。"):
        self._empty.setText(message)
        self._empty.setVisible(is_empty)
        self._body_container.setVisible(not is_empty)

    def _add_row(self, turn: dict):
        item = QListWidgetItem()
        widget = _make_turn_row(turn, self)
        item.setSizeHint(widget.sizeHint())
        self._list.addItem(item)
        self._list.setItemWidget(item, widget)

    def _on_select(self, index: int):
        if index < 0 or index >= len(self._turns):
            self._detail.clear()
            return
        trace_id = self._turns[index].get("trace_id")
        if not trace_id:
            return
        data = self._store.get_turn(trace_id)
        self._detail.set_data(data)


# ── 列表行 ──────────────────────────────────────────────────────────────

def _make_turn_row(turn: dict, parent: QWidget) -> QWidget:
    row = QWidget(parent)
    col = QVBoxLayout(row)
    col.setContentsMargins(8, 6, 8, 6)
    col.setSpacing(3)

    top = QHBoxLayout()
    top.setSpacing(6)
    label, color = _status_meta(turn.get("status", ""))
    top.addWidget(_Dot(color, row))
    name = BodyLabel(label, row)
    top.addWidget(name)
    top.addStretch()
    col.addLayout(top)

    started = (turn.get("started_at") or "")[:19].replace("T", " ")
    meta_bits = [started]
    if turn.get("total_tokens"):
        meta_bits.append(f"{turn['total_tokens']} tok")
    if turn.get("duration_ms"):
        meta_bits.append(f"{turn['duration_ms'] / 1000:.1f}s")
    col.addWidget(CaptionLabel("  ·  ".join(meta_bits), row))
    return row


class _Dot(QWidget):
    """状态色点。"""

    def __init__(self, color: str, parent=None):
        super().__init__(parent)
        self._color = color
        self.setFixedSize(10, 10)

    def paintEvent(self, _event):
        from PyQt6.QtGui import QPainter

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(self._color))
        p.drawEllipse(1, 1, 8, 8)


# ── 右侧详情：概览卡 + 分段切换 ──────────────────────────────────────────

class _TurnDetailView(QWidget):
    """单次运行详情：顶部概览卡，下方 SegmentedWidget 分页。"""

    _TABS = [
        ("llm", "LLM 调用"),
        ("tools", "工具调用"),
        ("security", "安全审计"),
        ("eval", "评测样本"),
        ("state", "状态机"),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self._overview = _OverviewCard(self)
        layout.addWidget(self._overview)

        self._pivot = SegmentedWidget(self)
        layout.addWidget(self._pivot)

        self._stack = QStackedWidget(self)
        layout.addWidget(self._stack, 1)

        self._pages: dict[str, _CardListPage] = {}
        for key, text in self._TABS:
            page = _CardListPage(self)
            self._pages[key] = page
            self._stack.addWidget(page)
            self._pivot.addItem(key, text, lambda *_, k=key: self._show(k))

        self._placeholder = BodyLabel("选择左侧记录查看详情。", self)
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._placeholder, 1)
        self.clear()

    def _show(self, key: str):
        self._stack.setCurrentWidget(self._pages[key])

    def clear(self):
        self._overview.setVisible(False)
        self._pivot.setVisible(False)
        self._stack.setVisible(False)
        self._placeholder.setVisible(True)

    def set_data(self, data: dict | None):
        if data is None:
            self._overview.setVisible(False)
            self._pivot.setVisible(False)
            self._stack.setVisible(False)
            self._placeholder.setText("（记录已不存在，可能已被清理）")
            self._placeholder.setVisible(True)
            return

        self._placeholder.setVisible(False)
        self._overview.setVisible(True)
        self._pivot.setVisible(True)
        self._stack.setVisible(True)

        self._overview.set_turn(data.get("turn", {}))
        counts = _fill_pages(self._pages, data)
        # 分段标题带计数；首个非空分页设为当前。
        first_key = None
        for key, text in self._TABS:
            n = counts.get(key, 0)
            self._pivot.widget(key).setText(f"{text} {n}" if n else text)
            if first_key is None and n:
                first_key = key
        first_key = first_key or self._TABS[0][0]
        self._pivot.setCurrentItem(first_key)
        self._show(first_key)


class _OverviewCard(SimpleCardWidget):
    """顶部概览：状态徽章 + 关键指标。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)

        top = QHBoxLayout()
        top.setSpacing(10)
        self._badge = InfoBadge.info("—", self)
        top.addWidget(self._badge)
        self._title = StrongBodyLabel("—", self)
        top.addWidget(self._title)
        top.addStretch()
        layout.addLayout(top)

        self._metrics = CaptionLabel("", self)
        self._metrics.setWordWrap(True)
        layout.addWidget(self._metrics)

        self._error = CaptionLabel("", self)
        self._error.setWordWrap(True)
        self._error.setTextColor(QColor("#d03050"), QColor("#ff7875"))
        layout.addWidget(self._error)

    def set_turn(self, turn: dict):
        status = turn.get("status", "")
        label, color = _status_meta(status)
        # 重建徽章以套用语义色。
        self._badge.setText(label)
        self._badge.setCustomBackgroundColor(QColor(color), QColor(color))

        sid = turn.get("session_id") or "—"
        self._title.setText(f"会话 {sid}")

        bits = [f"{turn.get('turn_count', 0)} 轮"]
        if turn.get("duration_ms"):
            bits.append(f"{turn['duration_ms'] / 1000:.2f}s")
        total = turn.get("total_tokens") or 0
        if total:
            bits.append(
                f"{total} tok（入 {turn.get('prompt_tokens', 0)} / "
                f"出 {turn.get('completion_tokens', 0)}）"
            )
        bits.append(f"trace {turn.get('trace_id', '')[:12]}")
        self._metrics.setText("　·　".join(bits))

        err = turn.get("error")
        self._error.setText(f"错误：{err}" if err else "")
        self._error.setVisible(bool(err))


class _CardListPage(SingleDirectionScrollArea):
    """一个可滚动的卡片列表分页。"""

    def __init__(self, parent=None):
        super().__init__(parent, orient=Qt.Orientation.Vertical)
        self.setWidgetResizable(True)
        self.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        self._container = QWidget(self)
        self._container.setStyleSheet("background: transparent;")
        self._vbox = QVBoxLayout(self._container)
        self._vbox.setContentsMargins(2, 2, 8, 2)
        self._vbox.setSpacing(8)
        self._vbox.addStretch()
        self.setWidget(self._container)

    def clear(self):
        while self._vbox.count() > 1:  # 保留末尾 stretch
            item = self._vbox.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def add_card(self, card: QWidget):
        self._vbox.insertWidget(self._vbox.count() - 1, card)

    def add_empty(self, text: str):
        label = CaptionLabel(text, self)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.add_card(label)


def _fill_pages(pages: dict, data: dict) -> dict[str, int]:
    """把各分类数据填进对应分页，返回每页条数（供分段标题计数）。"""
    counts: dict[str, int] = {}

    llm = data.get("llm_calls") or []
    tools = data.get("tool_calls") or []
    sec = data.get("security_events") or []
    evals = data.get("eval_samples") or []
    states = data.get("state_trace") or []

    for key, items, builder, empty in [
        ("llm", llm, _llm_card, "本次运行无 LLM 调用记录。"),
        ("tools", tools, _tool_card, "本次运行未调用工具。"),
        ("security", sec, _security_card, "本次运行无高风险工具调用。"),
        ("eval", evals, _eval_card, "本次运行无评测样本。"),
    ]:
        page = pages[key]
        page.clear()
        counts[key] = len(items)
        if items:
            for it in items:
                page.add_card(builder(it, page))
        else:
            page.add_empty(empty)

    state_page = pages["state"]
    state_page.clear()
    # 状态机是单条流转链，分段标题不计数（置 0 即不显示数字）。
    counts["state"] = 0
    if states:
        state_page.add_card(_state_card(states, state_page))
    else:
        state_page.add_empty("无状态机流转记录。")
    return counts


# ── 各类记录卡片 ─────────────────────────────────────────────────────────

def _row_card(parent: QWidget) -> tuple[CardWidget, QVBoxLayout]:
    card = CardWidget(parent)
    col = QVBoxLayout(card)
    col.setContentsMargins(12, 10, 12, 10)
    col.setSpacing(4)
    return card, col


def _title_row(col: QVBoxLayout, card: QWidget, *, dot: str | None,
               title: str, right: str = ""):
    top = QHBoxLayout()
    top.setSpacing(8)
    if dot:
        top.addWidget(_Dot(dot, card))
    name = BodyLabel(title, card)
    setFont(name, 14)
    top.addWidget(name)
    top.addStretch()
    if right:
        top.addWidget(CaptionLabel(right, card))
    col.addLayout(top)


def _llm_card(c: dict, parent: QWidget) -> QWidget:
    card, col = _row_card(parent)
    ok = (c.get("status") or "ok") == "ok"
    metrics = []
    if c.get("latency_ms"):
        metrics.append(f"{c['latency_ms'] / 1000:.2f}s")
    if c.get("total_tokens"):
        metrics.append(f"{c['total_tokens']} tok")
    title = f"#{c.get('seq', 0)}  {c.get('model') or c.get('provider') or '?'}"
    _title_row(col, card, dot=("#2e9e5b" if ok else "#d03050"),
               title=title, right="　·　".join(metrics))
    if c.get("error_message"):
        err = CaptionLabel(c["error_message"], card)
        err.setWordWrap(True)
        err.setTextColor(QColor("#d03050"), QColor("#ff7875"))
        col.addWidget(err)
    return card


def _tool_card(t: dict, parent: QWidget) -> QWidget:
    card, col = _row_card(parent)
    ok = t.get("status") != "error"
    right = f"{t['duration_ms']:.0f}ms" if t.get("duration_ms") else ""
    _title_row(col, card, dot=("#2e9e5b" if ok else "#d03050"),
               title=t.get("name", "?"), right=right)
    if t.get("arguments"):
        args = CaptionLabel(f"入参　{t['arguments']}", card)
        args.setWordWrap(True)
        col.addWidget(args)
    return card


def _security_card(e: dict, parent: QWidget) -> QWidget:
    card, col = _row_card(parent)
    rejected = e.get("decision") == "reject"
    right = "🚫 已拒绝" if rejected else "✓ 放行"
    _title_row(col, card, dot=("#d03050" if rejected else "#e0a400"),
               title=e.get("tool_name", "?"), right=right)
    if e.get("reason"):
        reason = CaptionLabel(e["reason"], card)
        reason.setWordWrap(True)
        col.addWidget(reason)
    return card


def _eval_card(s: dict, parent: QWidget) -> QWidget:
    card, col = _row_card(parent)
    right_bits = [f"工具 {s.get('tool_count', 0)}"]
    if s.get("error_count"):
        right_bits.append(f"错误 {s['error_count']}")
    if s.get("scores"):
        right_bits.append(f"评分 {s['scores']}")
    _title_row(col, card, dot=None, title=f"轮 {s.get('turn', 0)}",
               right="　·　".join(right_bits))
    if s.get("answer"):
        ans = CaptionLabel(s["answer"], card)
        ans.setWordWrap(True)
        col.addWidget(ans)
    return card


def _state_card(states: list, parent: QWidget) -> QWidget:
    card, col = _row_card(parent)
    flow = "  →  ".join(s.get("state", "") for s in states if s.get("state"))
    _title_row(col, card, dot=None, title="状态机流转")
    body = CaptionLabel(flow, card)
    body.setWordWrap(True)
    col.addWidget(body)
    return card
