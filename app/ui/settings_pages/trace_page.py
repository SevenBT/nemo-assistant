"""Runtime history, usage, provider-reported charges and diagnostic export."""

from __future__ import annotations

import json
from pathlib import Path
from collections.abc import Callable

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QDialog, QDialogButtonBox, QFileDialog, QMessageBox, QPlainTextEdit,
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
    HyperlinkButton,
    setFont,
)

from app.i18n import t
from app.ui.style import contrasting_text
from app.core.billing import normalize_provider_cost, validate_billing_url

# 状态 → (i18n key, 语义色)。语义色固定不随主题，对齐 InfoBadge 内部用色。
# 文案存 key，在 _status_meta 运行时取（语言启动后才锁定）。
_STATUS = {
    "ok": ("settings.trace.status_ok", "#2e9e5b"),
    "error": ("settings.trace.status_error", "#d03050"),
    "cancelled": ("settings.trace.status_cancelled", "#9aa0a6"),
    "running": ("settings.trace.status_running", "#5b8def"),
}

_MAX_TURNS = 100


def _status_meta(status: str) -> tuple[str, str]:
    entry = _STATUS.get(status)
    if entry is None:
        return (status or "?", "#9aa0a6")
    return (t(entry[0]), entry[1])


class TracePage(QWidget):
    """运行记录列表 + 单次运行的全链路回放。"""

    def __init__(self, trace_store=None, session_mgr=None, parent=None):
        super().__init__(parent)
        self._store = trace_store
        self._session_mgr = session_mgr
        self._traces: list[dict] = []
        self._build()
        self.reload()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        header = QHBoxLayout()
        header.addWidget(StrongBodyLabel(t("settings.trace.title"), self))
        header.addStretch()
        self._export_btn = PushButton(FluentIcon.SAVE, t("settings.trace.export"), self)
        self._export_btn.clicked.connect(self._on_export)
        self._export_btn.setEnabled(False)
        header.addWidget(self._export_btn)
        self._refresh_btn = PushButton(FluentIcon.SYNC, t("settings.trace.refresh"), self)
        self._refresh_btn.clicked.connect(self.reload)
        header.addWidget(self._refresh_btn)
        layout.addLayout(header)

        hint = CaptionLabel(
            t("settings.trace.hint"), self
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self._empty = BodyLabel(t("settings.trace.empty"), self)
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty.setWordWrap(True)
        layout.addWidget(self._empty, 1)

        body = QHBoxLayout()
        body.setSpacing(12)

        self._list = ListWidget(self)
        self._list.setFixedWidth(240)
        self._list.currentRowChanged.connect(self._on_select)
        body.addWidget(self._list)

        self._detail = _TraceDetailView(self)
        body.addWidget(self._detail, 1)

        self._body_container = QWidget(self)
        self._body_container.setLayout(body)
        layout.addWidget(self._body_container, 1)

    def reload(self):
        """从 TraceStore 重新拉取最近的 Trace 列表并重渲染。"""
        self._list.clear()
        self._detail.clear()
        if self._store is None or not getattr(self._store, "enabled", False):
            self._traces = []
            self._set_empty(True, t("settings.trace.disabled"))
            return
        self._traces = self._store.list_traces(limit=_MAX_TURNS)
        self._set_empty(not self._traces)
        for trace in self._traces:
            self._add_row(trace)
        if self._traces:
            self._list.setCurrentRow(0)

    def _set_empty(self, is_empty: bool, message: str = ""):
        self._empty.setText(message or t("settings.trace.empty"))
        self._empty.setVisible(is_empty)
        self._body_container.setVisible(not is_empty)

    def _add_row(self, trace: dict):
        item = QListWidgetItem()
        widget = _make_trace_row(trace, self)
        item.setSizeHint(widget.sizeHint())
        self._list.addItem(item)
        self._list.setItemWidget(item, widget)

    def _on_select(self, index: int):
        if index < 0 or index >= len(self._traces):
            self._detail.clear()
            self._export_btn.setEnabled(False)
            return
        self._export_btn.setEnabled(True)
        trace_id = self._traces[index].get("trace_id")
        if not trace_id:
            return
        data = self._store.get_trace(trace_id)
        self._detail.set_data(data)

    def _on_export(self):
        from app.core.diagnostics import build_diagnostic
        row = self._list.currentRow()
        if self._store is None or not (0 <= row < len(self._traces)):
            return
        data = self._store.get_trace(self._traces[row]["trace_id"])
        if data is None:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(t("settings.trace.export_preview"))
        dialog.resize(720, 520)
        layout = QVBoxLayout(dialog)
        hint = CaptionLabel(t("settings.trace.export_hint"), dialog)
        hint.setWordWrap(True)
        layout.addWidget(hint)
        editor = QPlainTextEdit(dialog)
        editor.setPlainText(json.dumps(build_diagnostic(data), ensure_ascii=False, indent=2))
        layout.addWidget(editor)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel, dialog)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            payload = json.loads(editor.toPlainText())
            filename, _ = QFileDialog.getSaveFileName(self, t("settings.trace.export"), "diagnostic.json", "JSON (*.json)")
            if filename:
                Path(filename).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, t("settings.trace.export"), str(exc))


# ── 列表行 ──────────────────────────────────────────────────────────────

def _make_trace_row(trace: dict, parent: QWidget) -> QWidget:
    row = QWidget(parent)
    col = QVBoxLayout(row)
    col.setContentsMargins(8, 6, 8, 6)
    col.setSpacing(3)

    top = QHBoxLayout()
    top.setSpacing(6)
    label, color = _status_meta(trace.get("status", ""))
    top.addWidget(_Dot(color, row))
    name = BodyLabel(label, row)
    top.addWidget(name)
    top.addStretch()
    col.addLayout(top)

    started = (trace.get("started_at") or "")[:19].replace("T", " ")
    meta_bits = [started]
    if trace.get("total_tokens"):
        meta_bits.append(f"{trace['total_tokens']} tok")
    if trace.get("duration_ms"):
        meta_bits.append(f"{trace['duration_ms'] / 1000:.1f}s")
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

class _TraceDetailView(QWidget):
    """单次运行详情：顶部概览卡，下方 SegmentedWidget 分页。"""

    _TABS = [
        ("llm", "settings.trace.tab_llm"),
        ("tools", "settings.trace.tab_tools"),
        ("security", "settings.trace.tab_security"),
        ("state", "settings.trace.tab_state"),
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
            self._pivot.addItem(key, t(text), lambda *_, k=key: self._show(k))

        self._placeholder = BodyLabel(t("settings.trace.placeholder"), self)
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder.setWordWrap(True)
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
            self._placeholder.setText(t("settings.trace.gone"))
            self._placeholder.setVisible(True)
            return

        self._placeholder.setVisible(False)
        self._overview.setVisible(True)
        self._pivot.setVisible(True)
        self._stack.setVisible(True)

        trace = data.get("trace") or {}
        self._overview.set_trace(trace, data.get("cost"))
        counts = _fill_pages(self._pages, data)
        # 分段标题带计数；首个非空分页设为当前。
        first_key = None
        for key, text in self._TABS:
            n = counts.get(key, 0)
            label = t(text)
            self._pivot.widget(key).setText(f"{label} {n}" if n else label)
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

    def set_trace(self, trace: dict, cost: dict | None = None):
        """设置 Trace 概览数据。"""
        status = trace.get("status", "")
        label, color = _status_meta(status)
        # 重建徽章以套用语义色。
        self._badge.setText(label)
        self._badge.setCustomBackgroundColor(QColor(color), QColor(color))
        self._badge.setStyleSheet(f"color: {contrasting_text(color)};")

        sid = trace.get("session_id") or "—"
        self._title.setText(t("settings.trace.session", sid=sid))

        bits = [t("settings.trace.turns", n=trace.get('turn_count', 0))]
        if trace.get("duration_ms"):
            bits.append(f"{trace['duration_ms'] / 1000:.2f}s")
        total = trace.get("total_tokens") or 0
        if total:
            bits.append(
                t("settings.trace.tokens_io", total=total,
                  prompt=trace.get('prompt_tokens', 0),
                  completion=trace.get('completion_tokens', 0))
            )
        bits.append(t("settings.trace.trace_id", id=trace.get('trace_id', '')[:12]))
        if cost is not None:
            for currency, amount in sorted(cost.get("reported_totals", {}).items()):
                bits.append(t("settings.trace.reported_cost", currency=currency, amount=f"{amount:.12g}"))
            if cost.get("unknown_calls"):
                bits.append(t("settings.trace.unreported_calls", n=cost["unknown_calls"]))
        bits.append(t("settings.trace.billing_hint"))
        self._metrics.setText("　·　".join(bits))

        err = trace.get("error")
        self._error.setText(t("settings.trace.error", err=err) if err else "")
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
        label.setWordWrap(True)
        self.add_card(label)


def _fill_pages(pages: dict, data: dict) -> dict[str, int]:
    """把各分类数据填进对应分页，返回每页条数（供分段标题计数）。"""
    counts: dict[str, int] = {}

    llm = data.get("llm_calls") or []
    tools = data.get("tool_calls") or []
    sec = data.get("security_events") or []
    states = data.get("state_trace") or []

    for key, items, builder, empty in [
        ("llm", llm, _llm_card, t("settings.trace.empty_llm")),
        ("tools", tools, _tool_card, t("settings.trace.empty_tools")),
        ("security", sec, _security_card, t("settings.trace.empty_security")),
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
        state_page.add_empty(t("settings.trace.empty_state"))
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
    cost = normalize_provider_cost({"amount": c.get("reported_cost_amount"),
                                    "currency": c.get("reported_cost_currency")})
    if cost is not None:
        text = t("settings.trace.reported_cost", currency=cost["currency"], amount=f"{cost['amount']:.12g}")
    else:
        text = t("settings.trace.unreported_cost")
    col.addWidget(CaptionLabel(text, card))
    if c.get("cost_usd") is not None:
        col.addWidget(CaptionLabel(t("settings.trace.legacy_cost", amount=f"{c['cost_usd']:.12g}"), card))
    url = validate_billing_url(c.get("provider"), c.get("billing_url"))
    if url:
        col.addWidget(HyperlinkButton(url, t("settings.trace.billing_console"), card))
    if c.get("error_message"):
        err = CaptionLabel(c["error_message"], card)
        err.setWordWrap(True)
        err.setTextColor(QColor("#d03050"), QColor("#ff7875"))
        col.addWidget(err)
    return card


def _tool_card(tc: dict, parent: QWidget) -> QWidget:
    card, col = _row_card(parent)
    ok = tc.get("status") != "error"
    right = f"{tc['duration_ms']:.0f}ms" if tc.get("duration_ms") else ""
    _title_row(col, card, dot=("#2e9e5b" if ok else "#d03050"),
               title=tc.get("name", "?"), right=right)
    if tc.get("arguments"):
        args = CaptionLabel(t("settings.trace.tool_args", args=tc['arguments']), card)
        args.setWordWrap(True)
        col.addWidget(args)
    return card


def _security_card(e: dict, parent: QWidget) -> QWidget:
    card, col = _row_card(parent)
    rejected = e.get("decision") == "reject"
    right = t("settings.trace.sec_rejected") if rejected else t("settings.trace.sec_allowed")
    _title_row(col, card, dot=("#d03050" if rejected else "#e0a400"),
               title=e.get("tool_name", "?"), right=right)
    if e.get("reason"):
        reason = CaptionLabel(e["reason"], card)
        reason.setWordWrap(True)
        col.addWidget(reason)
    return card


def _state_card(states: list, parent: QWidget) -> QWidget:
    card, col = _row_card(parent)
    flow = "  →  ".join(s.get("state", "") for s in states if s.get("state"))
    _title_row(col, card, dot=None, title=t("settings.trace.state_flow"))
    body = CaptionLabel(flow, card)
    body.setWordWrap(True)
    col.addWidget(body)
    return card
