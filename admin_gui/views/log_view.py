"""admin_gui/views/log_view.py — 全域日誌分頁（第四 tab）。

合併顯示：排程執行（gh run，含線上連結＋下載）＋ 動作日誌（action_log）。
動作日誌依時間序，新事件在最後；不再附舊 audit 摘要段落。
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

from admin_gui.services import log_reader

_ICON = {"success": "✅", "failure": "❌", "cancelled": "⛔",
         "skipped": "⏭", "in_progress": "⏳", "queued": "🔄"}


class LogView(QWidget):
    def __init__(self, repo_slug: str = "itemhsu/tech-rebalance", parent=None):
        super().__init__(parent)
        self.repo_slug = repo_slug

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

        dl_btn = QPushButton("⬇ 下載 log")
        dl_btn.setToolTip("把目前的動作日誌存成 .txt（你自己挑位置，永遠是最新內容）")
        dl_btn.clicked.connect(self._download_action_log)
        bar.addWidget(dl_btn)

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

        # 即時更新：訂閱 action_log，任何新事件都馬上重畫動作日誌框
        # （否則框只在建立/按↻ 時填一次，之後的操作雖有寫入 jsonl 卻看不到）
        from admin_gui.services.action_log import LOG
        LOG.subscribe(self._on_log_record)

        self.refresh()

    def _on_log_record(self, record: dict):
        """action_log 有新紀錄 → 重畫動作日誌框（只重畫文字框，不重打 gh 排程表）。"""
        try:
            self._fill_audit()
        except Exception:   # noqa: BLE001  更新顯示失敗不可影響主流程
            pass

    def showEvent(self, e):   # noqa: N802  切到本分頁時也刷新一次
        super().showEvent(e)
        self._fill_audit()

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
        """只顯示 action_log（每步驟細節，時間序：新的在最後）。不再附 audit 段落。"""
        from PySide6.QtGui import QTextCursor
        from admin_gui.services.action_log import LOG
        action_text = LOG.tail_text(300).strip()   # tail 依檔案順序＝時間序，新事件在最後
        self.audit_box.setPlainText(
            action_text or "（尚無記錄。執行任何操作後會出現於此）")
        # 捲到最底，讓最新事件可見
        self.audit_box.moveCursor(QTextCursor.End)
        self.audit_box.ensureCursorVisible()

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
        # 不再把「清除」本身寫進日誌——否則清完畫面又立刻冒出一筆，使用者誤以為沒清掉。
        self.refresh()   # 檔案已清空 → 日誌框顯示「（尚無記錄）」
        QMessageBox.information(self, "已清除", f"已清空 {n} 行動作日誌。")

    # ── ⬇ 下載 log（存當下最新內容成 .txt）──────────────────────────────────
    def _download_action_log(self):
        from pathlib import Path
        from datetime import datetime
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        from admin_gui.services.action_log import LOG, env_snapshot
        body = (f"# TradingAdmin 動作日誌\n{env_snapshot(self.repo_slug)}\n"
                + "=" * 50 + "\n" + LOG.tail_text(1000))
        default = str(Path.home() / "Desktop" /
                      f"tradingadmin-log-{datetime.now():%Y%m%d-%H%M%S}.txt")
        path, _ = QFileDialog.getSaveFileName(self, "下載 log 成 .txt", default, "文字檔 (*.txt)")
        if not path:
            return
        with LOG.action("下載 log") as a:
            try:
                Path(path).write_text(body, encoding="utf-8")
                a.step("存檔", "ok", path)
                QMessageBox.information(self, "已存檔", f"log 已存到：\n{path}")
            except Exception as e:  # noqa: BLE001
                a.step("存檔", "fail", f"{type(e).__name__}: {str(e)[:120]}")
                QMessageBox.warning(self, "失敗", f"存檔失敗：{e}")

    # ── 📧 發送 log ───────────────────────────────────────────────────────
    def _send_log(self):
        """真的把 log email 出去——走雲端 send_log.yml（用 GitHub secret 的 SMTP，
        本機不需密碼）。觸發後輪詢結果，成功/失敗都回報。"""
        from PySide6.QtWidgets import QMessageBox
        from PySide6.QtCore import QTimer
        from admin_gui.services.action_log import LOG, env_snapshot
        from admin_gui.services import probes

        with LOG.action("發送 log（雲端 email）", ctx=self.repo_slug) as a:
            body = (f"# TradingAdmin 動作日誌\n{env_snapshot(self.repo_slug)}\n"
                    + "=" * 50 + "\n" + LOG.tail_text(500))   # tail_text 已遮罩金鑰
            a.step("組裝 log", "ok", f"{len(body)} bytes")
            who = probes.gh_login() or "?"
            ok, msg = probes.trigger_send_log(self.repo_slug, body, who=who)
            a.step("觸發 send_log.yml", "ok" if ok else "fail", msg)
            if not ok:
                QMessageBox.warning(self, "發送 log 失敗", msg)
                return
        QMessageBox.information(self, "發送 log",
            "已觸發雲端寄送，約 20–40 秒會寄到 itemhsu@gmail.com。\n結果會顯示在日誌。")
        # 輪詢結果
        self._sendlog_secs = 0
        self._sendlog_timer = QTimer(self)
        self._sendlog_timer.setInterval(5000)
        self._sendlog_timer.timeout.connect(self._sendlog_poll)
        self._sendlog_timer.start()

    def _sendlog_poll(self):
        from admin_gui.services.action_log import LOG
        from admin_gui.services import probes
        self._sendlog_secs += 5
        status, concl = probes.last_send_log_result(self.repo_slug)
        if concl == "success":
            self._sendlog_timer.stop()
            LOG.note("send_log 結果", "ok", f"成功（{self._sendlog_secs}s）— 已寄至 itemhsu@gmail.com")
        elif concl in ("failure", "cancelled", "timed_out"):
            self._sendlog_timer.stop()
            reason = probes.last_test_email_failure_reason(
                self.repo_slug, workflow="send_log.yml")
            LOG.note("send_log 結果", "fail", f"{concl}: {reason or '(讀不到 log)'}")
        elif self._sendlog_secs >= 90:
            self._sendlog_timer.stop()
            LOG.note("send_log 結果", "warn", "等待逾時（90s），請到 Actions 看 send_log")

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
