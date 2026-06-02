"""admin_gui/views/log_view.py — 全域日誌分頁（第四 tab）。

合併顯示：操作日誌（audit）＋ 排程執行（gh run）。
從總覽分頁獨立出來，給日誌更大的顯示空間。
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QPlainTextEdit, QLabel,
)

from admin_gui.services.audit_log import AuditLog
from admin_gui.services import log_reader


class LogView(QWidget):
    def __init__(self, repo_slug: str = "itemhsu/tech-rebalance", parent=None):
        super().__init__(parent)
        self.repo_slug = repo_slug
        self.audit = AuditLog()

        v = QVBoxLayout(self)
        bar = QHBoxLayout()
        bar.addWidget(QLabel("📜 全域日誌（操作 + 排程執行）"))
        bar.addStretch()
        rb = QPushButton("↻ 重新整理"); rb.clicked.connect(self.refresh)
        bar.addWidget(rb)
        v.addLayout(bar)

        self.log_box = QPlainTextEdit(); self.log_box.setReadOnly(True)
        self.log_box.setStyleSheet("font-family:monospace;font-size:12px;")
        v.addWidget(self.log_box)
        self.refresh()

    def refresh(self):
        lines = ["── 操作日誌 ──"]
        for e in self.audit.read(limit=30):
            lines.append(f"{e['ts'][5:16]}  {e['action']}  {e['target']}  {e['result']}")
        lines.append("")
        lines.append("── 排程執行（gh run）──")
        for r in log_reader.cron_runs(repo=self.repo_slug, limit=20):
            lines.append(f"{(r.get('createdAt') or '')[:16]}  "
                         f"{r.get('workflowName','')}  {r.get('conclusion','')}")
        self.log_box.setPlainText("\n".join(lines))
