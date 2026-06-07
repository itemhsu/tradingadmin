"""admin_gui/views/log_view.py — 全域日誌分頁（第四 tab）。

合併顯示：排程執行歷史（純資訊表，無逐筆按鈕）＋ 動作日誌（action_log）。
總體一份：上方「🔗 線上查看全部」開 Actions 頁；「⬇ 下載 log / 📧 發送 log」
都把「動作日誌 + 排程執行歷史」兩份合一輸出。動作日誌依時間序、新事件在最後。
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QPlainTextEdit,
    QLabel, QSizePolicy,
)

from admin_gui.services import log_reader

_ICON = {"success": "✅", "failure": "❌", "cancelled": "⛔",
         "skipped": "⏭", "in_progress": "⏳", "queued": "🔄"}

# 單一真實來源：畫面顯示、下載、發送 log 都用同一個行數，確保三者完全一致
_TAIL = 1000


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

        # ── 上窗格：排程執行歷史（純 txt，與下載/發送完全相同的內容）──────────
        v.addWidget(QLabel("排程執行歷史（清除後只列新的；失敗附錯誤摘要）"))
        self.runs_box = QPlainTextEdit()
        self.runs_box.setReadOnly(True)
        self.runs_box.setLineWrapMode(QPlainTextEdit.NoWrap)   # 保留橫向捲動
        self.runs_box.setStyleSheet("font-family:monospace;font-size:11px;")
        _sp = QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        _sp.setVerticalStretch(1)
        self.runs_box.setSizePolicy(_sp)
        v.addWidget(self.runs_box)

        # ── 下窗格：動作日誌（本機，含每步驟細節）──────────────────────────
        v.addWidget(QLabel("動作日誌（本機，含每步驟細節）"))
        self.audit_box = QPlainTextEdit()
        self.audit_box.setReadOnly(True)
        self.audit_box.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.audit_box.setStyleSheet("font-family:monospace;font-size:11px;")
        _sp2 = QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        _sp2.setVerticalStretch(1)                              # 與上窗格等高
        self.audit_box.setSizePolicy(_sp2)
        v.addWidget(self.audit_box)

        # 即時更新：訂閱 action_log，任何新事件都馬上重畫動作日誌框
        # （否則框只在建立/按↻ 時填一次，之後的操作雖有寫入 jsonl 卻看不到）
        from admin_gui.services.action_log import LOG
        LOG.subscribe(self._on_log_record)

        self.refresh()

    def _on_log_record(self, record: dict):
        """action_log 有新紀錄 → 重畫下窗格（動作日誌）。"""
        try:
            self._fill_audit()
        except Exception:   # noqa: BLE001  更新顯示失敗不可影響主流程
            pass

    def showEvent(self, e):   # noqa: N802  切到本分頁時刷新
        super().showEvent(e)
        self._fill_audit()

    def refresh(self):
        self._fill_runs()
        self._fill_audit()

    # ── 上窗格：排程執行歷史 ────────────────────────────────────────────────
    def _fill_runs(self):
        """背景載入排程歷史（清除截止後的）+ 失敗附錯誤摘要 → 填上窗格。"""
        self.runs_box.setPlainText("載入排程執行歷史中…")
        from admin_gui.services.async_task import run_async
        from admin_gui.services.action_log import LOG
        cutoff = LOG.get_cutoff()
        repo = self.repo_slug

        def _load(report):
            runs = log_reader.cron_runs(repo=repo, limit=20)
            # 只保留「清除截止」之後的（清完不再重灌舊資料，省 token）
            if cutoff:
                runs = [r for r in runs if (r.get("createdAt") or "") > cutoff]
            # 失敗的 run 補抓錯誤摘要（讓一份 log 就能除錯）
            for r in runs:
                if (r.get("conclusion") in ("failure", "cancelled", "timed_out")
                        and r.get("databaseId")):
                    r["_excerpt"] = log_reader.run_failure_excerpt(repo, r["databaseId"])
            return runs

        run_async(self, _load, on_done=self._apply_runs,
                  on_failed=lambda e: self.runs_box.setPlainText(f"（讀取失敗：{e[:80]}）"))

    def _apply_runs(self, runs):
        self._runs = runs or []
        self.runs_box.setPlainText(self._runs_text())

    def _runs_text(self) -> str:
        """排程執行歷史 → 純文字（畫面上窗格 / 下載 / 發送 完全相同）。"""
        runs = getattr(self, "_runs", None)
        if runs is None:
            return "（尚未載入）"
        if not runs:
            return "（清除後尚無新的排程執行）"
        lines = []
        for r in runs:
            ts = (r.get("createdAt") or "")[:16].replace("T", " ")
            wf = r.get("workflowName") or ""
            concl = r.get("conclusion") or r.get("status") or ""
            icon = _ICON.get(concl, "")
            rid = r.get("databaseId")
            url = (f"https://github.com/{self.repo_slug}/actions/runs/{rid}"
                   if rid else "")
            lines.append(f"{ts}  {wf}  {icon}{concl}  {url}".rstrip())
            exc = r.get("_excerpt")
            if exc:                       # 失敗 → 縮排附錯誤摘要
                for ln in exc.splitlines():
                    lines.append(f"        {ln}")
        return "\n".join(lines)

    # ── 下窗格：動作日誌 ────────────────────────────────────────────────────
    def _fill_audit(self):
        """action_log（時間序、新的在最後）→ 填下窗格、捲到底。"""
        from PySide6.QtGui import QTextCursor
        from admin_gui.services.action_log import LOG
        action_text = LOG.tail_text(_TAIL).strip()
        self.audit_box.setPlainText(
            action_text or "（尚無記錄。執行任何操作後會出現於此）")
        self.audit_box.moveCursor(QTextCursor.End)
        self.audit_box.ensureCursorVisible()

    # ── 🗑 清除 log ───────────────────────────────────────────────────────
    def _clear_log(self):
        from PySide6.QtWidgets import QMessageBox
        from admin_gui.services.action_log import LOG
        if QMessageBox.question(
                self, "清除 log",
                "清除：① 清空本機動作日誌 ② 排程歷史以此刻為界，下次只列新的。\n"
                "（GitHub 上的執行歷史不會被刪，只是本工具不再重列舊的，省得每次重灌。）\n"
                "建議重現問題前清一次，這樣下載/發送的 log 才乾淨。要繼續嗎？"
        ) != QMessageBox.Yes:
            return
        n = LOG.clear()        # 清 action_log + 記排程截止時間
        self.refresh()
        QMessageBox.information(self, "已清除",
            f"已清空 {n} 行動作日誌；排程歷史以此刻為界，下次只列新的。")

    def _combined_log_text(self, n: int = _TAIL) -> str:
        """下載/發送的 txt＝畫面所見（必須相同）：上窗格＝排程執行歷史、下窗格＝動作日誌。"""
        from admin_gui.services.action_log import LOG, env_snapshot
        return ("# TradingAdmin log\n" + env_snapshot(self.repo_slug) + "\n"
                + "=" * 60 + "\n# 排程執行歷史（清除後只列新的；失敗附錯誤摘要）\n"
                + "=" * 60 + "\n" + self._runs_text()
                + "\n\n" + "=" * 60 + "\n# 動作日誌（本機，含每步驟細節）\n"
                + "=" * 60 + "\n" + LOG.tail_text(n))

    # ── ⬇ 下載 log（存當下最新內容成 .txt；兩份 log 合一）─────────────────────
    def _download_action_log(self):
        from pathlib import Path
        from datetime import datetime
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        from admin_gui.services.action_log import LOG
        body = self._combined_log_text(_TAIL)
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
        from admin_gui.services.action_log import LOG
        from admin_gui.services import probes

        with LOG.action("發送 log（雲端 email）", ctx=self.repo_slug) as a:
            body = self._combined_log_text(_TAIL)   # 兩份 log 合一（已遮罩金鑰）
            a.step("組裝 log（含排程歷史）", "ok", f"{len(body)} bytes")
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
