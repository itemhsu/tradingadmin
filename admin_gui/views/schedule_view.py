"""admin_gui/views/schedule_view.py — 排程分頁（Phase C）。

視覺化編輯 workflow 的 cron；diff 預覽 + push（含 token 掃描攔截）。
"""
from __future__ import annotations

from pathlib import Path
from typing import List

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QHeaderView, QLabel, QDialog, QPlainTextEdit, QDialogButtonBox,
    QMessageBox, QLineEdit,
)

from admin_gui.services import cron_editor as ce

_TZ_OFFSET = 8   # 台灣 UTC+8


class DiffDialog(QDialog):
    def __init__(self, title: str, diff_text: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(640, 360)
        lay = QVBoxLayout(self)
        box = QPlainTextEdit(diff_text or "（無變更）")
        box.setReadOnly(True)
        box.setStyleSheet("font-family:monospace; font-size:11px;")
        lay.addWidget(box)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.button(QDialogButtonBox.Ok).setText("確認 commit")
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)


class ScheduleView(QWidget):
    def __init__(self, repo_slug: str = "itemhsu/tech-rebalance", store=None, parent=None):
        super().__init__(parent)
        self.repo_slug = repo_slug
        if store is None:
            from admin_gui.services.repo_store import make_store
            store = make_store(repo_slug=repo_slug)
        self.store = store

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "每日自動執行時間（已自動開啟，無需設定）。時間為美股收盤後，"
            "下方為台灣時間。"))

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Workflow", "cron", "可讀（含台灣時間）", "編輯"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(self.table)

        # 排程預設就開啟（daily.yml 出廠即啟用）；萬一讀不到才顯示提示
        self.empty_hint = QLabel(
            "排程載入中…若持續空白，請到「總覽」按『重新執行設定精靈』修復一次。")
        self.empty_hint.setStyleSheet("color:#64748b;padding:16px;")
        self.empty_hint.setWordWrap(True)
        layout.addWidget(self.empty_hint)
        self._rows: List[tuple] = []
        self.refresh()

    def _enable_daily(self):
        from admin_gui.services.action_log import LOG
        # 找 daily.yml（或第一個含 run-account 的 workflow）
        target = ".github/workflows/daily.yml"
        text = self.store.read_text_or_none(target)
        if text is None:
            for wf in self._list_workflows():
                if "daily" in Path(wf).name:
                    target, text = wf, self.store.read_text_or_none(wf)
                    break
        if not text:
            QMessageBox.warning(self, "找不到 daily.yml",
                "找不到每日交易 workflow。請先到「總覽」按『重新執行設定精靈』修復交易系統。")
            return
        if ce.read_crons_text(text):
            QMessageBox.information(self, "已是啟用狀態", "每日排程已經啟用，無需重複。")
            self.refresh(); return
        new_text = ce.enable_schedule(text)
        preview = (f"將啟用每日自動執行：\n\n{Path(target).name}\n"
                   f"新增排程：15 21 * * 1-5（UTC 21:15，台灣隔日 05:15，週一至週五）\n\n"
                   f"按「確認 commit」會直接寫回 GitHub。之後可在表格用「改時間」調整。")
        if DiffDialog("啟用每日自動執行", preview, self).exec() != QDialog.Accepted:
            return
        with LOG.action("啟用每日自動執行", ctx=getattr(self, "repo_slug", "")) as a:
            try:
                msg = self.store.write_text(target, new_text,
                                            "chore(schedule): 啟用每日自動執行 cron")
                a.step("寫回 daily.yml", "ok", msg)
                QMessageBox.information(self, "完成", "已啟用每日自動執行。")
            except Exception as e:  # noqa: BLE001
                a.step("寫回 daily.yml", "fail", f"{type(e).__name__}: {str(e)[:160]}")
                QMessageBox.warning(self, "失敗", f"寫入失敗：{e}")
        self.refresh()

    def _list_workflows(self) -> list:
        """動態列出 .github/workflows/ 所有 .yml 檔案（不再硬寫名稱）。"""
        try:
            names = self.store.list_dir(".github/workflows")
            return [f".github/workflows/{n}" for n in names if n.endswith(".yml")]
        except Exception:  # noqa: BLE001
            return []

    def refresh(self):
        self._rows = []
        self._wf_text = {}
        for wf in self._list_workflows():
            try:
                text = self.store.read_text_or_none(wf)
            except Exception:  # noqa: BLE001
                text = None
            if not text:
                continue
            self._wf_text[wf] = text
            for c in ce.read_crons_text(text):
                self._rows.append((wf, c))
        # 有排程→顯示表格藏提示；讀不到→顯示提示
        empty = not self._rows
        self.empty_hint.setVisible(empty)
        self.table.setVisible(not empty)
        self.table.setRowCount(len(self._rows))
        for r, (wf, c) in enumerate(self._rows):
            self.table.setItem(r, 0, QTableWidgetItem(Path(wf).name))
            self.table.setItem(r, 1, QTableWidgetItem(c.to_expr()))
            self.table.setItem(r, 2, QTableWidgetItem(c.human(_TZ_OFFSET)))
            btn = QPushButton("改時間")
            btn.clicked.connect(lambda _=False, idx=r: self._edit(idx))
            self.table.setCellWidget(r, 3, btn)

    def _edit(self, idx: int):
        wf, entry = self._rows[idx]
        # 簡易編輯：用 QLineEdit 讓使用者改 5 欄 cron（保留靈活）
        dlg = QDialog(self); dlg.setWindowTitle(f"編輯 cron — {Path(wf).name}")
        v = QVBoxLayout(dlg)
        v.addWidget(QLabel(f"目前：{entry.to_expr()}  （{entry.human(_TZ_OFFSET)}）"))
        edit = QLineEdit(entry.to_expr())
        v.addWidget(edit)
        hint = QLabel(""); hint.setStyleSheet("color:#888;font-size:11px;")
        v.addWidget(hint)
        edit.textChanged.connect(lambda t: hint.setText(self._preview(t)))
        hint.setText(self._preview(entry.to_expr()))
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.button(QDialogButtonBox.Ok).setText("預覽 diff → push")
        btns.accepted.connect(dlg.accept); btns.rejected.connect(dlg.reject)
        v.addWidget(btns)
        if dlg.exec() != QDialog.Accepted:
            return
        new_expr = edit.text().strip()
        try:
            ce.CronEntry.parse(new_expr)
        except ValueError as e:
            QMessageBox.warning(self, "cron 格式錯", str(e)); return
        self._apply(wf, entry.to_expr(), new_expr)

    def _preview(self, expr: str) -> str:
        try:
            return "→ " + ce.CronEntry.parse(expr).human(_TZ_OFFSET)
        except ValueError as e:
            return f"⚠ {e}"

    def _apply(self, wf: str, old_expr: str, new_expr: str):
        old_text = self._wf_text.get(wf) or (self.store.read_text_or_none(wf) or "")
        try:
            new_text = ce.replace_cron(old_text, old_expr, new_expr)
        except ValueError as e:
            QMessageBox.warning(self, "替換失敗", str(e)); return
        # 確認：顯示前後 cron（不需 git diff）
        preview = (f"檔案：{Path(wf).name}\n\n"
                   f"原本：{old_expr}\n新值：{new_expr}\n\n"
                   f"按「確認 commit」會直接寫回 GitHub（不需本機 clone）。")
        dlg = DiffDialog(f"將更新排程：{Path(wf).name}", preview, self)
        if dlg.exec() != QDialog.Accepted:
            return
        from admin_gui.services.action_log import LOG
        with LOG.action("修改排程 cron", ctx=getattr(self, "repo_slug", "")) as a:
            a.step("變更", "ok", f"{Path(wf).name}: {old_expr} → {new_expr}")
            try:
                msg = self.store.write_text(
                    wf, new_text, f"chore(schedule): {Path(wf).name} cron → {new_expr}")
                a.step("寫回 GitHub", "ok", msg)
                QMessageBox.information(self, "完成", msg)
            except Exception as e:  # noqa: BLE001
                a.step("寫回 GitHub", "fail", f"{type(e).__name__}: {str(e)[:160]}")
                QMessageBox.warning(self, "寫入失敗", str(e))
        self.refresh()
