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
        if store is None:
            from admin_gui.services.repo_store import make_store
            store = make_store(repo_slug=repo_slug)
        self.store = store

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("每個 workflow 的 cron 排程（時間為 UTC，下方換算台灣時間）"))

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Workflow", "cron", "可讀（含台灣時間）", "編輯"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(self.table)

        bar = QHBoxLayout()
        b = QPushButton("↻ 重新整理"); b.clicked.connect(self.refresh); bar.addWidget(b)
        bar.addStretch()
        layout.addLayout(bar)
        self._rows: List[tuple] = []
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
