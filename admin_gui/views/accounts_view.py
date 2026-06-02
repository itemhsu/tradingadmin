"""admin_gui/views/accounts_view.py — 帳戶分頁（Phase A-2 重設計）。

極簡表單：使用者只填 帳戶名稱 / 券商 / 環境 / 策略 + API 金鑰。
系統自動補 id/secret_prefix/data_dir/use_new_runner。
「測試連線並儲存」：金鑰先試打券商 API，成功才寫 accounts.json + 設 GitHub Secrets + 記 log。
選一列可看該帳戶交易 log。
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QHeaderView, QMessageBox, QDialog, QFormLayout, QLineEdit,
    QComboBox, QCheckBox, QDialogButtonBox, QLabel, QRadioButton, QButtonGroup,
    QPlainTextEdit,
)

from admin_gui.services.accounts_repo import AccountsRepo
from admin_gui.services.catalog import Catalog
from admin_gui.services.state_reader import StateReader
from admin_gui.services.account_factory import build_account
from admin_gui.services.gh_client import GhClient, GhError
from admin_gui.services import probes, log_reader

_HEADERS = ["id", "帳戶名稱", "啟用", "券商", "環境", "策略", "最後 NAV", "日期"]


class AccountDialog(QDialog):
    """新增/編輯帳戶（極簡 + 內嵌金鑰 + 測試才存）。"""

    def __init__(self, catalog: Catalog, gh: GhClient, repo: AccountsRepo,
                 account: Optional[dict] = None, parent=None):
        super().__init__(parent)
        self.catalog, self.gh, self.repo = catalog, gh, repo
        self.original = account
        self.setWindowTitle("編輯帳戶" if account else "新增帳戶")
        form = QFormLayout(self)

        a = account or {}
        self.name_edit = QLineEdit(a.get("label", ""))
        self.name_edit.setPlaceholderText("例如：我的科技股（必填）")
        self.broker_cmb = QComboBox(); self.broker_cmb.addItems(catalog.list_brokers())
        if a.get("broker"): self.broker_cmb.setCurrentText(a["broker"])
        # 環境：radio（paper/live），live 變紅
        self.env_paper = QRadioButton("模擬 paper")
        self.env_live = QRadioButton("真錢 live")
        self.env_group = QButtonGroup(self)
        self.env_group.addButton(self.env_paper); self.env_group.addButton(self.env_live)
        env_row = QWidget(); el = QHBoxLayout(env_row); el.setContentsMargins(0,0,0,0)
        el.addWidget(self.env_paper); el.addWidget(self.env_live)
        (self.env_live if a.get("environment") == "live" else self.env_paper).setChecked(True)
        self.env_warn = QLabel(""); self.env_warn.setStyleSheet("color:#fca5a5;font-size:11px;")
        self.env_live.toggled.connect(self._env_changed); self._env_changed()
        self.strategy_cmb = QComboBox(); self.strategy_cmb.addItems(catalog.list_strategies())
        if a.get("strategy"): self.strategy_cmb.setCurrentText(a["strategy"])
        self.enabled_chk = QCheckBox("啟用後每日自動交易（關閉＝暫停這個帳戶不下單）")
        self.enabled_chk.setChecked(bool(a.get("enabled", True)))
        self.email_edit = QLineEdit("; ".join(a.get("email_recipients", [])))

        self.key_edit = QLineEdit(); self.key_edit.setEchoMode(QLineEdit.Password)
        self.sec_edit = QLineEdit(); self.sec_edit.setEchoMode(QLineEdit.Password)
        self.key_edit.setPlaceholderText("API Key（存進 GitHub，不留本機）")
        self.sec_edit.setPlaceholderText("API Secret")

        form.addRow("帳戶名稱", self.name_edit)
        form.addRow("券商", self.broker_cmb)
        form.addRow("環境", env_row)
        form.addRow("", self.env_warn)
        form.addRow("策略", self.strategy_cmb)
        form.addRow("", self.enabled_chk)
        form.addRow("email 收件人", self.email_edit)
        form.addRow("API Key", self.key_edit)
        form.addRow("API Secret", self.sec_edit)
        self.status = QLabel(""); self.status.setWordWrap(True)
        form.addRow(self.status)

        btns = QDialogButtonBox(QDialogButtonBox.Cancel)
        self.save_btn = btns.addButton("測試連線並儲存", QDialogButtonBox.AcceptRole)
        self.save_btn.clicked.connect(self._test_and_save)
        btns.rejected.connect(self.reject)
        form.addRow(btns)

    def _env_changed(self):
        if self.env_live.isChecked():
            self.env_warn.setText("⚠ 真錢帳戶：每日 cron 會用真錢下單")
        else:
            self.env_warn.setText("")

    def _env(self) -> str:
        return "live" if self.env_live.isChecked() else "paper"

    def _test_and_save(self):
        name = self.name_edit.text().strip()
        if not name:
            self.status.setText("❌ 帳戶名稱必填"); return
        broker = self.broker_cmb.currentText()
        env = self._env()
        strat = self.strategy_cmb.currentText()
        key, sec = self.key_edit.text().strip(), self.sec_edit.text().strip()

        # live 二次確認
        if env == "live":
            if QMessageBox.question(self, "真錢確認",
                f"帳戶「{name}」將以【真錢 live】每日自動交易。確定？") != QMessageBox.Yes:
                return

        # 既有帳戶若沒重填金鑰，跳過試打（只改其他欄位）
        if key and sec:
            self.status.setText("⏳ 測試連線中…"); self.repaint()
            spec = self.catalog.broker_spec(broker)
            ok, msg = probes.probe_broker(spec, env, key, sec)
            if not ok:
                self.status.setText(f"❌ {msg}（未儲存）"); return
            self.status.setText(f"✅ {msg}")

        try:
            if self.original:   # 編輯
                acc_id = self.original["id"]
                self.repo.update(acc_id, {
                    "label": name, "broker": broker, "environment": env,
                    "strategy": strat, "enabled": self.enabled_chk.isChecked(),
                    "email_recipients": [s.strip() for s in self.email_edit.text().split(";") if s.strip()],
                })
            else:               # 新增（系統指定 id 等）
                acc = build_account(name, broker, env, strat,
                                    existing_ids=self.repo.ids(),
                                    enabled=self.enabled_chk.isChecked(),
                                    email_recipients=[s.strip() for s in self.email_edit.text().split(";") if s.strip()])
                self.repo.add(acc)
                acc_id = acc["id"]
            # 金鑰一併寫進 GitHub Secrets（免切分頁）
            if key and sec:
                prefix = f"ACC{acc_id}"
                self.gh.set_secret(f"{prefix}_ALPACA_KEY", key)
                self.gh.set_secret(f"{prefix}_ALPACA_SECRET", sec)
        except (ValueError, GhError) as e:
            self.status.setText(f"❌ {e}（未完成）"); return
        self.accept()


class AccountsView(QWidget):
    def __init__(self, repo_slug: str = "itemhsu/tech-rebalance", store=None, parent=None):
        super().__init__(parent)
        if store is None:
            from admin_gui.services.repo_store import make_store
            store = make_store(repo_slug=repo_slug)
        self.store = store
        self.repo = AccountsRepo(store=store)
        self.catalog = Catalog(store=store)
        self.state = StateReader(store=store)
        self.gh = GhClient(repo_slug)

        layout = QVBoxLayout(self)
        self.table = QTableWidget(0, len(_HEADERS))
        self.table.setHorizontalHeaderLabels(_HEADERS)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.doubleClicked.connect(lambda *_: self._edit())
        self.table.itemSelectionChanged.connect(self._show_log)
        layout.addWidget(self.table)

        bar = QHBoxLayout()
        for text, fn in [("＋ 新增", self._add), ("✎ 編輯", self._edit),
                         ("🗑 刪除", self._delete), ("↻ 重新整理", self.refresh)]:
            b = QPushButton(text); b.clicked.connect(fn); bar.addWidget(b)
        bar.addStretch()
        layout.addLayout(bar)

        layout.addWidget(QLabel("帳戶交易日誌（選一列）"))
        self.log_box = QPlainTextEdit(); self.log_box.setReadOnly(True)
        self.log_box.setMaximumHeight(140)
        self.log_box.setStyleSheet("font-family:monospace;font-size:11px;")
        layout.addWidget(self.log_box)
        self.refresh()

    def refresh(self):
        accounts = self.repo.load()
        self.table.setRowCount(len(accounts))
        for r, a in enumerate(accounts):
            st = self.state.read(a)
            env = a.get("environment", "")
            cells = [str(a.get("id", "")), a.get("label", ""),
                     "✅" if a.get("enabled", True) else "⛔", a.get("broker", ""),
                     ("🔴 LIVE" if env == "live" else env),
                     a.get("strategy", ""),
                     f"${st.nav:,.0f}" if st.nav else "待產生", st.date or "—"]
            for c, text in enumerate(cells):
                it = QTableWidgetItem(text)
                if c == 4 and env == "live":
                    it.setForeground(Qt.red)
                self.table.setItem(r, c, it)

    def _selected_id(self) -> Optional[str]:
        row = self.table.currentRow()
        return self.table.item(row, 0).text() if row >= 0 else None

    def _show_log(self):
        acc_id = self._selected_id()
        if not acc_id:
            return
        acc = self.repo.get(acc_id) or {}
        ev = log_reader.account_trade_events(acc, limit=20, store=self.store)
        if not ev:
            self.log_box.setPlainText("（尚無交易紀錄）"); return
        import json as _j
        self.log_box.setPlainText("\n".join(_j.dumps(e, ensure_ascii=False) for e in ev))

    def _add(self):
        dlg = AccountDialog(self.catalog, self.gh, self.repo, None, self)
        if dlg.exec() == QDialog.Accepted:
            self.refresh()

    def _edit(self):
        acc_id = self._selected_id()
        if not acc_id:
            return
        dlg = AccountDialog(self.catalog, self.gh, self.repo, self.repo.get(acc_id), self)
        if dlg.exec() == QDialog.Accepted:
            self.refresh()

    def _delete(self):
        acc_id = self._selected_id()
        if not acc_id:
            return
        acc = self.repo.get(acc_id) or {}
        if QMessageBox.question(self, "刪除確認",
            f"刪除「{acc.get('label')}」(#{acc_id})？\n• 從 accounts.json 移除\n"
            f"• 保留 {acc.get('data_dir')}/ 歷史") == QMessageBox.Yes:
            self.repo.delete(acc_id)
            self.refresh()
