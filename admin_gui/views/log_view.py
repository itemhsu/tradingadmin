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

        clr_btn = QPushButton("🗑 清除 log")
        clr_btn.setToolTip("清空本機動作日誌（重現問題前先清，寄來的 log 才乾淨）")
        clr_btn.clicked.connect(self._clear_log)
        bar.addWidget(clr_btn)

        send_btn = QPushButton("📧 發送 log")
        send_btn.setToolTip("把本機動作日誌寄給開發者（itemhsu@gmail.com）以便診斷")
        send_btn.clicked.connect(self._send_log)
        bar.addWidget(send_btn)

        rb = QPushButton("↻ 重新整理")
        rb.clicked.connect(self.refresh)
        bar.addWidget(rb)
        v.addLayout(bar)

        # 重現步驟說明
        hint = QLabel("回報問題標準流程：① 🗑 清除 log → ② 重做出問題的操作 → ③ 📧 發送 log")
        hint.setStyleSheet("color:#94a3b8;font-size:11px;")
        v.addWidget(hint)

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

        # ── 動作日誌（action_log，密集步驟）文字框 ────────────────────────
        v.addWidget(QLabel("動作日誌（本機，含每步驟細節）"))
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
        """顯示新的 action_log（密集步驟，含 env/gh rc/失敗原因）+ 舊 audit 摘要。"""
        from admin_gui.services.action_log import LOG
        parts = []
        action_text = LOG.tail_text(300)
        if action_text.strip():
            parts.append(action_text.strip())
        # 舊 audit（帳戶 CRUD / set_secret 等）附在後面
        old = [f"{e['ts'][5:16]}  {e['action']}  {e['target']}  {e['result']}"
               for e in self.audit.read(limit=30)]
        if old:
            parts.append("── 操作摘要（audit）──\n" + "\n".join(old))
        self.audit_box.setPlainText(
            "\n\n".join(parts) if parts else "（尚無記錄。執行任何操作後會出現於此）")

    # ── 🗑 清除 log ───────────────────────────────────────────────────────
    def _clear_log(self):
        from PySide6.QtWidgets import QMessageBox
        from admin_gui.services.action_log import LOG
        if QMessageBox.question(
                self, "清除 log",
                "清空本機動作日誌（不可逆，只清本機、不碰 GitHub 排程歷史）。\n"
                "建議重現問題前清一次，這樣寄來的 log 才乾淨。要繼續嗎？"
        ) != QMessageBox.Yes:
            return
        n = LOG.clear()
        # 清除本身也記一筆（不靜默）→ 成為新一輪的起點
        with LOG.action("清除 log") as a:
            a.step("truncate action_log.jsonl", "ok", f"清除 {n} 行")
        self.refresh()
        QMessageBox.information(self, "已清除", f"已清空 {n} 行動作日誌。")

    # ── 📧 發送 log ───────────────────────────────────────────────────────
    def _send_log(self):
        from pathlib import Path
        from PySide6.QtWidgets import QMessageBox
        from admin_gui.services.action_log import LOG, env_snapshot
        from admin_gui.services import probes
        from admin_gui.services.global_config import GlobalConfig

        with LOG.action("發送 log email", ctx=self.repo_slug) as a:
            body = (f"# TradingAdmin 動作日誌\n{env_snapshot(self.repo_slug)}\n"
                    + "=" * 50 + "\n" + LOG.tail_text(500))   # tail_text 已遮罩金鑰
            a.step("組裝 log", "ok", f"{len(body)} bytes")
            cfg = GlobalConfig()
            sender = cfg.get("email_sender") or ""
            # EMAIL_PASSWORD 在 GitHub secret，本機沒有 → 後援：存桌面檔
            pw = cfg.get("email_password_local") or ""
            if sender and pw:
                ok, msg = probes.send_log_to_dev(
                    sender, pw, body,
                    subject=f"[TradingAdmin log] {probes.gh_login() or '?'}")
                a.step("SMTP 寄送", "ok" if ok else "fail", msg)
                dlg = (QMessageBox.information if ok else QMessageBox.warning)
                dlg(self, "發送 log", msg)
                return
            # 後援：存桌面檔，請使用者手動寄
            dest = Path.home() / "Desktop" / "tradingadmin-log.txt"
            try:
                dest.write_text(body, encoding="utf-8")
                a.step("存桌面檔（無 SMTP 密碼）", "warn", str(dest))
                QMessageBox.information(
                    self, "已存檔（需手動寄）",
                    f"目前沒有可寄信的密碼，log 已存到：\n{dest}\n\n"
                    f"請手動把這個檔寄給 itemhsu@gmail.com。")
            except Exception as e:  # noqa: BLE001
                a.step("存桌面檔", "fail", f"{type(e).__name__}: {str(e)[:120]}")
                QMessageBox.warning(self, "失敗", f"連存檔都失敗：{e}")

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
