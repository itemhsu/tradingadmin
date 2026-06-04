"""admin_gui/views/log_view.py — 全域日誌分頁（第四 tab）。

合併顯示：排程執行（gh run，含線上連結＋下載）＋ 操作日誌（audit）。
每筆排程執行提供「線上查看」與「下載 log」兩個動作。
"""
from __future__ import annotations

import subprocess
import webbrowser

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QPlainTextEdit,
    QLabel, QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QSizePolicy,
)

from admin_gui.services.audit_log import AuditLog
from admin_gui.services import log_reader

_ICON = {"success": "✅", "failure": "❌", "cancelled": "⛔",
         "skipped": "⏭", "in_progress": "⏳", "queued": "🔄"}


class LogView(QWidget):
    def __init__(self, repo_slug: str = "itemhsu/tech-rebalance", parent=None):
        super().__init__(parent)
        self.repo_slug = repo_slug
        self.audit = AuditLog()

        v = QVBoxLayout(self)
        v.setSpacing(8)

        # ── 標頭列 ────────────────────────────────────────────────────────
        bar = QHBoxLayout()
        bar.addWidget(QLabel("<b>📜 全域日誌</b>"))
        bar.addStretch()

        # 「線上查看全部 →」超連結（瀏覽器開 Actions 頁）
        all_link = QLabel(
            f'<a href="https://github.com/{repo_slug}/actions">'
            f'🔗 線上查看全部 →</a>')
        all_link.setOpenExternalLinks(True)
        all_link.setToolTip(f"https://github.com/{repo_slug}/actions")
        bar.addWidget(all_link)

        rb = QPushButton("↻ 重新整理")
        rb.clicked.connect(self.refresh)
        bar.addWidget(rb)
        v.addLayout(bar)

        # ── 排程執行表格 ─────────────────────────────────────────────────
        v.addWidget(QLabel("排程執行（最近 20 次）"))
        self.run_table = QTableWidget(0, 5)
        self.run_table.setHorizontalHeaderLabels(
            ["時間", "Workflow", "結果", "線上查看", "下載 log"])
        self.run_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.Stretch)
        for col in (0, 2):
            self.run_table.horizontalHeader().setSectionResizeMode(
                col, QHeaderView.ResizeToContents)
        for col in (3, 4):
            self.run_table.horizontalHeader().setSectionResizeMode(
                col, QHeaderView.Fixed)
            self.run_table.setColumnWidth(col, 90)
        self.run_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.run_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.run_table.setAlternatingRowColors(True)
        self.run_table.verticalHeader().setVisible(False)
        sp = QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        sp.setVerticalStretch(3)
        self.run_table.setSizePolicy(sp)
        v.addWidget(self.run_table)

        # ── 操作日誌（audit）文字框 ──────────────────────────────────────
        v.addWidget(QLabel("操作日誌（本機）"))
        self.audit_box = QPlainTextEdit()
        self.audit_box.setReadOnly(True)
        self.audit_box.setStyleSheet("font-family:monospace;font-size:11px;")
        sp2 = QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        sp2.setVerticalStretch(1)
        self.audit_box.setSizePolicy(sp2)
        v.addWidget(self.audit_box)

        self.refresh()

    # ── 填表 ──────────────────────────────────────────────────────────────
    def refresh(self):
        self._fill_run_table()
        self._fill_audit()

    def _fill_run_table(self):
        runs = log_reader.cron_runs(repo=self.repo_slug, limit=20)
        self.run_table.setRowCount(len(runs))
        for row, r in enumerate(runs):
            ts = (r.get("createdAt") or "")[:16].replace("T", " ")
            wf = r.get("workflowName") or ""
            concl = r.get("conclusion") or r.get("status") or ""
            icon = _ICON.get(concl, "❓")
            run_id = r.get("databaseId")
            url = (f"https://github.com/{self.repo_slug}/actions/runs/{run_id}"
                   if run_id else "")

            for col, text in ((0, ts), (1, wf), (2, f"{icon} {concl}")):
                item = QTableWidgetItem(text)
                item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
                if col == 2 and concl == "failure":
                    item.setForeground(Qt.red)
                self.run_table.setItem(row, col, item)

            # 「線上查看」按鈕
            view_btn = QPushButton("🔗 查看")
            view_btn.setEnabled(bool(url))
            view_btn.clicked.connect(lambda _, u=url: webbrowser.open(u))
            self.run_table.setCellWidget(row, 3, view_btn)

            # 「下載 log」按鈕
            dl_btn = QPushButton("⬇ 下載")
            dl_btn.setEnabled(bool(run_id))
            dl_btn.clicked.connect(
                lambda _, rid=run_id: self._download_log(rid))
            self.run_table.setCellWidget(row, 4, dl_btn)

    def _fill_audit(self):
        lines = []
        for e in self.audit.read(limit=50):
            lines.append(
                f"{e['ts'][5:16]}  {e['action']}  {e['target']}  {e['result']}")
        self.audit_box.setPlainText(
            "\n".join(lines) if lines else "（尚無操作記錄）")

    # ── 下載 log ─────────────────────────────────────────────────────────
    def _download_log(self, run_id: int):
        """用 gh CLI 把 log 下載到使用者選的目錄；失敗則改為開瀏覽器。"""
        from pathlib import Path
        from PySide6.QtWidgets import QMessageBox, QFileDialog

        dest = QFileDialog.getExistingDirectory(
            self, "選擇下載目錄", str(Path.home() / "Desktop"))
        if not dest:
            return

        r = subprocess.run(
            ["gh", "run", "download", str(run_id),
             "--repo", self.repo_slug, "--dir", dest],
            capture_output=True, text=True, timeout=60)
        if r.returncode == 0:
            QMessageBox.information(
                self, "下載完成",
                f"Log 已下載至：\n{dest}")
        else:
            url = (f"https://github.com/{self.repo_slug}"
                   f"/actions/runs/{run_id}")
            webbrowser.open(url)
            QMessageBox.information(
                self, "在瀏覽器查看",
                f"下載遇到問題，已在瀏覽器開啟此次執行頁面。\n\n"
                f"你也可以直接在 GitHub Actions 頁面下載 log artifacts。")
