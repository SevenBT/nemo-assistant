"""评测集 / 回归页 —— 失败案例回归集的管理与运行、改动前后对比。

数据源同样是 traces.db（TraceStore 的 eval_cases / eval_runs / eval_results）：
    左侧两块——回归用例列表 + 历史运行列表；右侧——运行结果与「相对上次运行」的
    按维度对比（退步标红）。

定位（对单机单用户的克制版）：不做 Golden Set 分层管理那套组织流程。用例只有
一条朴素的来源——「曾经坑过你」的对话回填。运行是手动触发：换 model / 改 prompt
后跑一遍，确认旧 bug 没复活、核心指标没退步。
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CardWidget,
    FluentIcon,
    ListWidget,
    PushButton,
    SimpleCardWidget,
    SingleDirectionScrollArea,
    StrongBodyLabel,
    setFont,
)

from app.i18n import t

# 维度名 → i18n key。值存 key，在 _dim_label 运行时取文案（语言启动后才锁定）。
_DIM_LABELS = {
    "completed": "settings.eval.dim_completed",
    "tool_success_rate": "settings.eval.dim_tool_success_rate",
    "error_recovery_rate": "settings.eval.dim_error_recovery_rate",
    "redundant_call_rate": "settings.eval.dim_redundant_call_rate",
    "json_valid_rate": "settings.eval.dim_json_valid_rate",
    "expected_tool_hit_rate": "settings.eval.dim_expected_tool_hit_rate",
    "judge_helpfulness": "settings.eval.dim_judge_helpfulness",
    "judge_correctness": "settings.eval.dim_judge_correctness",
    "judge_safety": "settings.eval.dim_judge_safety",
}


def _dim_label(dim: str) -> str:
    key = _DIM_LABELS.get(dim)
    return t(key) if key else dim


class _EvalRunWorker(QThread):
    """后台线程跑回归，避免阻塞 UI 事件循环（否则窗口冻结 + 重绘失效遮挡）。

    runner.run_eval 会对每条用例同步执行一次 AgentLoop（真实 LLM 调用），
    耗时且阻塞。放到独立线程，进度/结果经 Qt 信号回主线程更新 UI。
    TraceStore 每次操作开独立短连接 + 进程内写锁，跨线程安全。
    """

    progress = pyqtSignal(int, int, str)  # (完成数, 总数, 当前用例标题)
    finished_run = pyqtSignal(object, str)  # (run_id 或 None, 错误信息)

    def __init__(self, *, trace_store, llm, registry, prompt_builder, parent=None):
        super().__init__(parent)
        self._store = trace_store
        self._llm = llm
        self._registry = registry
        self._prompt_builder = prompt_builder

    def run(self):
        from app.eval import runner

        try:
            run_id = runner.run_eval(
                trace_store=self._store,
                llm_gateway=self._llm,
                registry=self._registry,
                prompt_builder=self._prompt_builder,
                label="manual",
                progress_fn=lambda done, total, title: self.progress.emit(
                    done, total, title
                ),
            )
            self.finished_run.emit(run_id, "")
        except Exception as exc:  # 兜底：worker 内异常不得静默吞掉
            import logging

            logging.getLogger(__name__).exception("[eval] run_eval failed")
            self.finished_run.emit(None, str(exc))


class EvalPage(QWidget):
    """评测集管理 + 运行 + 对比。

    依赖（全部可选，缺失则相应能力降级）：
        trace_store    必需：用例 / 运行 / 结果的读写。
        llm_gateway    跑评测需要（重跑用例走 AgentLoop + 网关）。
        registry       跑评测需要（工具注册中心）。
        prompt_builder 可选：让重跑更贴近真实运行语境。
    """

    def __init__(
        self,
        trace_store=None,
        llm_gateway=None,
        registry=None,
        prompt_builder=None,
        parent=None,
    ):
        super().__init__(parent)
        self._store = trace_store
        self._llm = llm_gateway
        self._registry = registry
        self._prompt_builder = prompt_builder
        self._cases: list[dict] = []
        self._runs: list[dict] = []
        self._run_worker: _EvalRunWorker | None = None
        self._build()
        self.reload()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        header = QHBoxLayout()
        header.addWidget(StrongBodyLabel(t("settings.eval.title"), self))
        header.addStretch()
        self._run_btn = PushButton(FluentIcon.PLAY, t("settings.eval.run"), self)
        self._run_btn.setToolTip(t("settings.eval.run_tip"))
        self._run_btn.clicked.connect(self._on_run)
        header.addWidget(self._run_btn)
        self._refresh_btn = PushButton(FluentIcon.SYNC, t("settings.eval.refresh"), self)
        self._refresh_btn.clicked.connect(self.reload)
        header.addWidget(self._refresh_btn)
        layout.addLayout(header)

        hint = CaptionLabel(
            t("settings.eval.hint"), self
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self._empty = BodyLabel("", self)
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty.setWordWrap(True)
        layout.addWidget(self._empty)

        body = QHBoxLayout()
        body.setSpacing(12)

        # 左列：用例 + 运行两个列表。
        left = QVBoxLayout()
        left.setSpacing(6)
        left.addWidget(CaptionLabel(t("settings.eval.cases"), self))
        self._case_list = ListWidget(self)
        self._case_list.setFixedWidth(240)
        left.addWidget(self._case_list, 1)
        left.addWidget(CaptionLabel(t("settings.eval.runs"), self))
        self._run_list = ListWidget(self)
        self._run_list.setFixedWidth(240)
        self._run_list.currentRowChanged.connect(self._on_select_run)
        left.addWidget(self._run_list, 1)
        body.addLayout(left)

        # 右列：运行结果 + 对比。
        self._detail = _RunDetailView(self)
        body.addWidget(self._detail, 1)

        layout.addLayout(body, 1)

    def reload(self):
        if self._store is None or not getattr(self._store, "enabled", False):
            self._empty.setText(t("settings.eval.disabled"))
            self._empty.setVisible(True)
            return
        self._empty.setVisible(False)
        self._cases = self._store.list_eval_cases(enabled_only=False)
        self._runs = self._store.list_eval_runs(limit=50)
        self._fill_case_list()
        self._fill_run_list()
        if self._runs:
            self._run_list.setCurrentRow(0)
        else:
            self._detail.clear()
        self._run_btn.setEnabled(bool(self._cases) and self._llm is not None)

    def _fill_case_list(self):
        self._case_list.clear()
        for case in self._cases:
            item = QListWidgetItem()
            widget = _case_row(case, self)
            item.setSizeHint(widget.sizeHint())
            self._case_list.addItem(item)
            self._case_list.setItemWidget(item, widget)

    def _fill_run_list(self):
        self._run_list.clear()
        for run in self._runs:
            item = QListWidgetItem()
            widget = _run_row(run, self)
            item.setSizeHint(widget.sizeHint())
            self._run_list.addItem(item)
            self._run_list.setItemWidget(item, widget)

    def _on_select_run(self, index: int):
        if index < 0 or index >= len(self._runs):
            self._detail.clear()
            return
        run = self._runs[index]
        baseline = self._find_run(run.get("baseline_run_id"))
        results = self._store.get_eval_results(run["run_id"])
        self._detail.set_data(run, baseline, results)

    def _find_run(self, run_id: str | None) -> dict | None:
        if not run_id:
            return None
        return next((r for r in self._runs if r.get("run_id") == run_id), None)

    def _on_run(self):
        """后台线程跑回归集，不阻塞 UI（用例少但每条都跑真实 AgentLoop，仍很慢）。"""
        if self._store is None or self._llm is None or self._registry is None:
            return
        if self._run_worker is not None and self._run_worker.isRunning():
            return

        self._run_btn.setEnabled(False)
        self._refresh_btn.setEnabled(False)
        self._run_btn.setText(t("settings.eval.running"))

        worker = _EvalRunWorker(
            trace_store=self._store,
            llm=self._llm,
            registry=self._registry,
            prompt_builder=self._prompt_builder,
            parent=self,
        )
        worker.progress.connect(self._on_run_progress)
        worker.finished_run.connect(self._on_run_finished)
        self._run_worker = worker
        worker.start()

    def _on_run_progress(self, done: int, total: int, title: str):
        if total and done < total:
            self._run_btn.setText(t("settings.eval.running_progress", done=done, total=total))

    def _on_run_finished(self, run_id, error: str):
        from app.ui.toast import show_toast

        self._run_btn.setText(t("settings.eval.run"))
        self._refresh_btn.setEnabled(True)
        self._run_worker = None

        if error:
            show_toast(t("settings.eval.toast_title"), t("settings.eval.toast_failed", error=error))
        elif run_id:
            show_toast(t("settings.eval.toast_title"), t("settings.eval.toast_done"))
            self.reload()
        else:
            show_toast(t("settings.eval.toast_title"), t("settings.eval.toast_no_cases"))
        # reload 会按当前条件重设 run 按钮可用性；失败/空跑时手动恢复。
        if not run_id:
            self._run_btn.setEnabled(bool(self._cases) and self._llm is not None)


# ── 列表行 ──────────────────────────────────────────────────────────────

def _case_row(case: dict, parent: QWidget) -> QWidget:
    row = QWidget(parent)
    col = QVBoxLayout(row)
    col.setContentsMargins(8, 6, 8, 6)
    col.setSpacing(2)
    enabled = bool(case.get("enabled", 1))
    title = case.get("title") or case.get("case_id", "")[:12]
    name = BodyLabel(title if enabled else t("settings.eval.case_disabled", title=title), row)
    col.addWidget(name)
    tools = case.get("expected_tools") or ""
    if tools and tools not in ("[]", "null"):
        col.addWidget(CaptionLabel(t("settings.eval.expected_tools", tools=tools), row))
    return row


def _run_row(run: dict, parent: QWidget) -> QWidget:
    row = QWidget(parent)
    col = QVBoxLayout(row)
    col.setContentsMargins(8, 6, 8, 6)
    col.setSpacing(2)
    started = (run.get("started_at") or "")[:19].replace("T", " ")
    head = QHBoxLayout()
    head.setSpacing(6)
    head.addWidget(BodyLabel(started, row))
    head.addStretch()
    head.addWidget(CaptionLabel(t("settings.eval.case_count", n=run.get('case_count', 0)), row))
    col.addLayout(head)
    meta = []
    if run.get("model"):
        meta.append(str(run["model"]))
    if run.get("git_commit"):
        meta.append(run["git_commit"])
    if meta:
        col.addWidget(CaptionLabel("  ·  ".join(meta), row))
    return row


# ── 右侧详情：运行汇总 + 对比 ─────────────────────────────────────────────

class _RunDetailView(SingleDirectionScrollArea):
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

    def _add(self, widget: QWidget):
        self._vbox.insertWidget(self._vbox.count() - 1, widget)

    def clear(self):
        while self._vbox.count() > 1:
            item = self._vbox.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def set_data(self, run: dict, baseline: dict | None, results: list[dict]):
        import json

        from app.eval import metrics

        self.clear()
        avg = _loads(run.get("avg_scores"))
        base_avg = _loads(baseline.get("avg_scores")) if baseline else None

        comparison = metrics.compare(avg, base_avg)
        self._add(_ComparisonCard(comparison, has_baseline=base_avg is not None, parent=self))

        # 逐用例结果摘要。
        for res in results:
            self._add(_ResultCard(res, self))


class _ComparisonCard(SimpleCardWidget):
    """各维度均分 + 相对上次运行的 Δ（退步标红、改善标绿）。"""

    def __init__(self, comparison: list[dict], *, has_baseline: bool, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(6)
        title = t("settings.eval.cmp_vs_baseline") if has_baseline else t("settings.eval.cmp_no_baseline")
        layout.addWidget(StrongBodyLabel(title, self))

        if not comparison:
            layout.addWidget(CaptionLabel(t("settings.eval.cmp_empty"), self))
            return

        for row in comparison:
            line = QHBoxLayout()
            line.setSpacing(8)
            line.addWidget(BodyLabel(_dim_label(row["dim"]), self))
            line.addStretch()
            cur = row.get("current")
            line.addWidget(CaptionLabel(_fmt(cur), self))
            delta = row.get("delta")
            if delta is not None:
                tag = CaptionLabel(_fmt_delta(delta), self)
                if row.get("regressed"):
                    tag.setTextColor(QColor("#d03050"), QColor("#ff7875"))
                elif row.get("improved"):
                    tag.setTextColor(QColor("#2e9e5b"), QColor("#52c41a"))
                line.addWidget(tag)
            layout.addLayout(line)


class _ResultCard(CardWidget):
    def __init__(self, res: dict, parent=None):
        super().__init__(parent)
        col = QVBoxLayout(self)
        col.setContentsMargins(12, 10, 12, 10)
        col.setSpacing(4)
        name = BodyLabel(t("settings.eval.result_case", id=res.get('case_id', '')[:12]), self)
        setFont(name, 14)
        col.addWidget(name)
        rule = _loads(res.get("rule_scores"))
        if rule:
            bits = [f"{_dim_label(k)} {_fmt(v)}" for k, v in rule.items()]
            lab = CaptionLabel("　·　".join(bits), self)
            lab.setWordWrap(True)
            col.addWidget(lab)
        judge = _loads(res.get("judge_scores"))
        if judge:
            bits = [f"{_dim_label('judge_' + k)} {v}" for k, v in judge.items()
                    if k != "reasoning"]
            if bits:
                col.addWidget(CaptionLabel("　·　".join(bits), self))
        out = res.get("actual_output")
        if out:
            ans = CaptionLabel(out, self)
            ans.setWordWrap(True)
            col.addWidget(ans)
        return


def _loads(raw):
    import json
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return {}


def _fmt(val) -> str:
    if isinstance(val, (int, float)):
        return f"{val:.2f}"
    return "—"


def _fmt_delta(delta: float) -> str:
    sign = "+" if delta > 0 else ""
    return f"{sign}{delta:.2f}"
