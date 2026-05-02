from PyQt6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.core.scheduler import SchedulerManager


class SchedulerPanel(QWidget):
    """定时任务面板，嵌入主窗口 QStackedWidget 中。"""

    def __init__(self, scheduler: SchedulerManager, parent=None):
        super().__init__(parent)
        self._scheduler = scheduler
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # header toolbar
        header = QHBoxLayout()
        header.setSpacing(6)
        refresh_btn = QPushButton("刷新")
        refresh_btn.setObjectName("noteToolBtn")
        refresh_btn.clicked.connect(self._load)
        header.addWidget(refresh_btn)
        header.addStretch()
        layout.addLayout(header)

        # table
        self._table = QTableWidget()
        self._table.setColumnCount(5)
        self._table.setHorizontalHeaderLabels(["名称", "工具", "触发类型", "描述", "操作"])
        hh = self._table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        self._table.setColumnWidth(4, 60)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        layout.addWidget(self._table)

    def _load(self):
        jobs = self._scheduler.get_jobs()
        self._table.setRowCount(len(jobs))
        for row, job in enumerate(jobs):
            self._table.setItem(row, 0, QTableWidgetItem(job["name"]))
            self._table.setItem(row, 1, QTableWidgetItem(job.get("tool_name", "")))
            self._table.setItem(row, 2, QTableWidgetItem(job.get("trigger_type", "")))
            self._table.setItem(row, 3, QTableWidgetItem(job.get("description", "")))
            del_btn = QPushButton("删除")
            del_btn.setFixedWidth(54)
            jid = job["id"]
            del_btn.clicked.connect(lambda _checked, j=jid: self._delete(j))
            self._table.setCellWidget(row, 4, del_btn)

    def _delete(self, job_id: str):
        reply = QMessageBox.question(
            self,
            "确认删除",
            "确定要删除这个定时任务吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._scheduler.remove_job(job_id)
            self._load()

    def showEvent(self, event):
        """切换到此视图时自动刷新任务列表。"""
        self._load()
        super().showEvent(event)

    def refresh(self):
        self._load()
