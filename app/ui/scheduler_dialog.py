from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from app.core.scheduler import SchedulerManager


class SchedulerDialog(QDialog):
    def __init__(self, scheduler: SchedulerManager, parent=None):
        super().__init__(parent)
        self._scheduler = scheduler
        self.setWindowTitle("定时任务管理")
        self.setMinimumSize(620, 380)
        self._build()
        self._load()

    def _build(self):
        layout = QVBoxLayout(self)

        # header
        header = QHBoxLayout()
        header.addWidget(QLabel("定时任务"))
        header.addStretch()
        refresh_btn = QPushButton("刷新")
        refresh_btn.clicked.connect(self._load)
        header.addWidget(refresh_btn)
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

        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)

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
