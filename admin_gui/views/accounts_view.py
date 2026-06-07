"""admin_gui/views/accounts_view.py — 帳戶分頁。

使用者只填 帳戶名稱 / 券商 / 環境 / 策略 + 金鑰；金鑰欄位<b>依券商動態</b>：
  - Alpaca → API Key + API Secret
  - Tradier → 只一個 API Token（account_id 由 GUI 自動取得）
系統自動補 id/secret_prefix/data_dir。測試連線成功才寫 accounts.json + GitHub Secrets。
表格不顯示內部 id。
"""
from __future__ import annotations

from typing import Dict, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QHeaderView, QMessageBox, QDialog, QFormLayout, QLineEdit,
    QComboBox, QCheckBox, QDialogButtonBox, QLabel, QGroupBox, QPlainTextEdit,
)

from admin_gui.services.accounts_repo import AccountsRepo
from admin_gui.services.catalog import Catalog
from admin_gui.services.state_reader import StateReader
from admin_gui.services.account_factory import build_account
from admin_gui.services.gh_client import GhClient, GhError
from admin_gui.services import probes, log_reader, broker_creds

# A-1：移除「id」欄（系統內部碼，使用者無須看見）
_HEADERS = ["帳戶名稱", "啟用", "券商", "環境", "策略", "最後 NAV", "日期"]
_ENV_COL = 3   # 「環境」欄索引（用於 live 標紅）


def publish_accounts_to_dashboard(repo_b_slug: str, accounts: list, logger=None) -> None:
    """把公開可見的帳戶清單寫到 dashboard repo 的 accounts.json。

    為什麼需要：GUI 把 accounts.json 存到「私有 repo B」，但 dashboard 讀的是
    「公開 dashboard repo」的 accounts.json —— 兩者不同檔，不同步 dashboard 就會
    顯示「accounts.json 中沒有帳戶」。此函式在每次帳戶異動後把清單推到 dashboard。
    只放公開安全欄位（id/label/strategy/enabled）；密鑰另存 GitHub Secrets，永不入此檔。
    """
    import json
    from admin_gui.services.repo_store import make_store
    dash_slug = f"{repo_b_slug}-dashboard"
    pub = {"accounts": [
        {"id": a.get("id"), "label": a.get("label", ""),
         "strategy": a.get("strategy", ""), "enabled": bool(a.get("enabled", True))}
        for a in accounts]}
    store = make_store(repo_slug=dash_slug)
    store.write_text("accounts.json", json.dumps(pub, ensure_ascii=False),
                     "chore: sync accounts.json from admin GUI")
    if logger is not None:
        logger.step("同步 accounts.json → dashboard", "ok",
                    f"{dash_slug}（{len(pub['accounts'])} 個帳戶）")


class AccountDialog(QDialog):
    """新增/編輯帳戶（金鑰欄位依券商動態 + 測試才存）。"""

    def __init__(self, catalog: Catalog, gh: GhClient, repo: AccountsRepo,
                 account: Optional[dict] = None, parent=None):
        super().__init__(parent)
        self.catalog, self.gh, self.repo = catalog, gh, repo
        self.original = account
        self.setWindowTitle("編輯帳戶" if account else "新增帳戶")
        a = account or {}

        outer = QVBoxLayout(self)
        form = QFormLayout()
        outer.addLayout(form)

        self.name_edit = QLineEdit(a.get("label", ""))
        self.name_edit.setPlaceholderText("例如：我的科技股（必填）")
        self.broker_cmb = QComboBox(); self.broker_cmb.addItems(catalog.list_brokers())
        if a.get("broker"):
            self.broker_cmb.setCurrentText(a["broker"])
        self.env_cmb = QComboBox()
        self.env_warn = QLabel(""); self.env_warn.setStyleSheet("color:#fca5a5;font-size:11px;")
        self.strategy_cmb = QComboBox(); self.strategy_cmb.addItems(catalog.list_strategies())
        if a.get("strategy"):
            self.strategy_cmb.setCurrentText(a["strategy"])
        self.enabled_chk = QCheckBox("啟用後每日自動交易（關閉＝暫停這個帳戶不下單）")
        self.enabled_chk.setChecked(bool(a.get("enabled", True)))
        self.email_edit = QLineEdit("; ".join(a.get("email_recipients", [])))

        form.addRow("帳戶名稱", self.name_edit)
        form.addRow("券商", self.broker_cmb)
        form.addRow("環境", self.env_cmb)
        form.addRow("", self.env_warn)
        form.addRow("策略", self.strategy_cmb)
        form.addRow("", self.enabled_chk)
        form.addRow("email 收件人", self.email_edit)

        # 金鑰區（依券商動態重繪）
        self.cred_box = QGroupBox("API 金鑰")
        self.cred_form = QFormLayout(self.cred_box)
        self.cred_edits: Dict[str, QLineEdit] = {}
        outer.addWidget(self.cred_box)

        self.status = QLabel(""); self.status.setWordWrap(True)
        outer.addWidget(self.status)

        btns = QDialogButtonBox(QDialogButtonBox.Cancel)
        self.save_btn = btns.addButton("測試連線並儲存", QDialogButtonBox.AcceptRole)
        self.save_btn.clicked.connect(self._test_and_save)
        btns.rejected.connect(self.reject)
        outer.addWidget(btns)

        # 券商/環境連動
        self.broker_cmb.currentTextChanged.connect(self._on_broker_changed)
        self.env_cmb.currentTextChanged.connect(self._env_changed)
        self._on_broker_changed()   # 初次填入 env + 金鑰欄
        if a.get("environment"):
            self.env_cmb.setCurrentText(a["environment"])

    # ── 券商連動：重建環境選項 + 金鑰欄位（A-2 / A-5）────────────────────
    def _on_broker_changed(self):
        broker = self.broker_cmb.currentText()
        spec = self.catalog.broker_spec(broker)
        # 環境（paper/live 或 sandbox/live）來自 schema，不自由輸入
        envs = self.catalog.broker_environments(broker) or ["paper", "live"]
        self.env_cmb.blockSignals(True)
        self.env_cmb.clear(); self.env_cmb.addItems(envs)
        self.env_cmb.blockSignals(False)
        self._env_changed()
        # 金鑰欄位：清掉舊的、依 schema 重建
        while self.cred_form.rowCount():
            self.cred_form.removeRow(0)
        self.cred_edits.clear()
        for key, label, masked in broker_creds.credential_inputs(spec):
            edit = QLineEdit()
            if masked:
                edit.setEchoMode(QLineEdit.Password)
            edit.setPlaceholderText(f"{label}（存進 GitHub，不留本機）")
            self.cred_edits[key] = edit
            self.cred_form.addRow(label, edit)
        if broker_creds.needs_account_discovery(spec):
            hint = QLabel("Account ID 由系統用 Token 自動取得，無需輸入")
            hint.setStyleSheet("color:#94a3b8;font-size:11px;")
            self.cred_form.addRow("", hint)

    def _env_changed(self):
        self.env_warn.setText(
            "⚠ 真錢帳戶：每日 cron 會用真錢下單" if self.env_cmb.currentText() == "live" else "")

    def _test_and_save(self):
        """測試連線並儲存：驗證/真錢確認在主執行緒；連線測試+寫入+同步在背景（不凍結）。"""
        name = self.name_edit.text().strip()
        broker = self.broker_cmb.currentText()
        env = self.env_cmb.currentText()
        if not name:
            self.status.setText("❌ 帳戶名稱必填"); return
        spec = self.catalog.broker_spec(broker)
        strat = self.strategy_cmb.currentText()
        values = {k: e.text().strip() for k, e in self.cred_edits.items()}
        has_input = any(values.values())
        if not has_input and not self.original:
            self.status.setText("❌ 新帳戶需輸入 API 金鑰並測試（未儲存）"); return
        if env == "live":
            if QMessageBox.question(self, "真錢確認",
                f"帳戶「{name}」將以【真錢 live】每日自動交易。確定？") != QMessageBox.Yes:
                return

        from PySide6.QtWidgets import QProgressDialog
        from PySide6.QtCore import Qt, QTimer
        from admin_gui.services.async_task import run_async
        from admin_gui.services.action_log import LOG
        dlg = QProgressDialog("測試連線中…", None, 0, 0, self)   # 無取消鈕
        dlg.setWindowTitle("測試連線並儲存"); dlg.setWindowModality(Qt.WindowModal)
        dlg.setMinimumWidth(380); dlg.setMinimumDuration(0); dlg.setAutoClose(False); dlg.show()
        self._save_step = "測試連線中…"; self._save_secs = 0
        timer = QTimer(self); timer.setInterval(1000)
        def _tick():
            self._save_secs += 1
            dlg.setLabelText(f"{self._save_step}（{self._save_secs}s）")
        timer.timeout.connect(_tick); timer.start()
        def _on_step(rec):
            if isinstance(rec, dict) and rec.get("kind") == "step":
                self._save_step = rec.get("name", "")
        LOG.subscribe(_on_step)
        def _cleanup():
            timer.stop(); dlg.close()
            try:
                LOG._listeners.remove(_on_step)
            except (ValueError, AttributeError):
                pass
        def _finish(res):
            _cleanup()
            ok, msg = res
            self.status.setText(("✅ " if ok else "❌ ") + msg)
            if ok:
                self.accept()
        def _failed(err):
            _cleanup(); self.status.setText(f"❌ {err[:160]}")
        run_async(self,
                  lambda report: self._test_and_save_core(
                      name, broker, env, spec, strat, values, has_input),
                  on_done=_finish, on_failed=_failed)

    def _test_and_save_core(self, name, broker, env, spec, strat, values, has_input):
        """背景執行緒：連線測試 + 寫 accounts.json + 寫 Secrets + 同步 dashboard。
        回 (ok, msg)。"""
        from admin_gui.services.action_log import LOG, half_mask
        with LOG.action("測試連線並儲存", ctx=getattr(self, "repo_slug", "")) as a:
            a.step("輸入", "ok", f"label={name} broker={broker} env={env}")
            a.step("金鑰形狀", "ok", " ".join(
                f"{k}▸{half_mask(v)}" for k, v in values.items()) or "(無)")
            account_id = ""
            if has_input:
                if broker_creds.needs_account_discovery(spec) and values.get("API_KEY"):
                    ok, res = probes.fetch_account_id(spec, env, values["API_KEY"])
                    a.step("自動取得 account_id", "ok" if ok else "fail", res)
                    if not ok:
                        return (False, f"{res}（未儲存）")
                    account_id = res
                    values["ACCOUNT_ID"] = res
                ok, msg = probes.probe_broker(
                    spec, env, values.get("API_KEY", ""), values.get("API_SECRET", ""), account_id)
                a.step("券商連線測試", "ok" if ok else "fail", msg)
                if not ok:
                    return (False, f"{msg}（未儲存）")
                conn_msg = msg + (f"（帳號 {account_id}）" if account_id else "")
            else:
                conn_msg = "已儲存"
            try:
                if self.original:
                    acc_id = self.original["id"]
                    prefix = self.original.get("secret_prefix") or f"ACC{acc_id}"
                    self.repo.update(acc_id, {
                        "label": name, "broker": broker, "environment": env,
                        "strategy": strat, "enabled": self.enabled_chk.isChecked(),
                        "email_recipients": [s.strip() for s in self.email_edit.text().split(";") if s.strip()],
                    })
                    a.step("更新 accounts.json", "ok", f"id={acc_id}")
                else:
                    acc = build_account(name, broker, env, strat,
                                        existing_ids=self.repo.ids(),
                                        enabled=self.enabled_chk.isChecked(),
                                        email_recipients=[s.strip() for s in self.email_edit.text().split(";") if s.strip()])
                    self.repo.add(acc)
                    acc_id = acc["id"]
                    prefix = acc.get("secret_prefix") or f"ACC{acc_id}"
                    a.step("新增 accounts.json", "ok", f"id={acc_id} prefix={prefix}")
                if has_input:
                    written = broker_creds.secret_writes(broker, spec, prefix, values)
                    for sname, sval in written.items():
                        self.gh.set_secret(sname, sval)
                    a.step("寫入 GitHub Secrets", "ok", "、".join(written.keys()))
            except (ValueError, GhError) as e:
                a.step("儲存", "fail", f"{type(e).__name__}: {str(e)[:160]}")
                return (False, f"{e}（未完成）")
            try:
                publish_accounts_to_dashboard(self.gh.repo, self.repo.load(), a)
            except Exception as e:   # noqa: BLE001  同步失敗不擋帳戶儲存
                a.step("同步 accounts.json → dashboard", "fail", str(e)[:160])
        return (True, conn_msg)


class AccountsView(QWidget):
    def __init__(self, repo_slug: str = "itemhsu/tech-rebalance", store=None, parent=None):
        super().__init__(parent)
        if store is None:
            from admin_gui.services.repo_store import make_store
            store = make_store(repo_slug=repo_slug)
        self.store = store
        self.repo_slug = repo_slug
        self.repo = AccountsRepo(store=store)
        self.catalog = Catalog(store=store)
        self.state = StateReader(store=store)
        self.gh = GhClient(repo_slug)
        # 即時 NAV：雲端查詢的快照 {id: {nav,cash,ts}|{error}} + 進行中狀態
        self._nav_snap: dict = {}
        self._nav_pending = False
        self._nav_secs = 0
        self._nav_started = False   # 只在分頁首次顯示時自動觸發一次

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
                         ("🗑 刪除", self._delete), ("↻ 更新 NAV", self._start_nav_refresh)]:
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
        """先顯示「載入中…」，accounts.json + 每帳戶 state 在背景讀（P3：不卡頓）。"""
        self.table.setRowCount(1)
        self.table.setItem(0, 0, QTableWidgetItem("載入帳戶中…"))
        from admin_gui.services.async_task import run_async
        run_async(self, lambda report: self._compute_accounts(), on_done=self._apply_accounts)

    def _compute_accounts(self):
        """背景：讀 accounts.json + 每個帳戶的 state。回 [(account, state), ...]。"""
        return [(a, self.state.read(a)) for a in self.repo.load()]

    def _apply_accounts(self, rows):
        self.table.setRowCount(len(rows))
        for r, (a, st) in enumerate(rows):
            env = a.get("environment", "")
            cells = [a.get("label", ""),
                     "✅" if a.get("enabled", True) else "⛔", a.get("broker", ""),
                     ("🔴 LIVE" if env == "live" else env),
                     a.get("strategy", ""),
                     self._nav_text(a.get("id", ""), st), st.date or "—"]
            for c, text in enumerate(cells):
                it = QTableWidgetItem(text)
                if c == 0:
                    it.setData(Qt.UserRole, str(a.get("id", "")))   # id 藏在第一欄資料
                if c == _ENV_COL and env == "live":
                    it.setForeground(Qt.red)
                self.table.setItem(r, c, it)

    # ── 即時 NAV（雲端查詢；金鑰不留本機）──────────────────────────────────
    _NAV_COL = 5

    def _nav_text(self, acc_id: str, st) -> str:
        """NAV 欄文字：優先雲端即時快照 → 查詢中（含秒數）→ 不顯示舊的 state。"""
        s = self._nav_snap.get(str(acc_id))
        if s and "nav" in s:
            return f"${s['nav']:,.0f}"
        if s and "error" in s:
            return f"⚠ {str(s['error'])[:18]}"
        if self._nav_pending:
            return f"⏳ 查詢中… {self._nav_secs}s"
        return "—"   # 不顯示「待產生」/舊資料；等查詢

    def showEvent(self, e):   # noqa: N802  分頁首次顯示時：查即時 NAV + 檢查 init page
        super().showEvent(e)
        if not self._nav_started:
            self._nav_started = True
            self._start_nav_refresh()
            self._ensure_init_pages(force=False)   # 系統啟動檢查：缺 init page 就發佈

    def _ensure_init_pages(self, force: bool = False):
        """確保每個帳戶在 dashboard 有 init page。
        force=True（新增帳號）→ 直接觸發發佈；
        force=False（啟動檢查）→ 任一帳戶的 data.json 缺，才觸發（避免每次都打 workflow）。"""
        from admin_gui.services import probes
        from admin_gui.services.action_log import LOG
        owner = self.gh.repo.split("/")[0]
        base = f"https://{owner}.github.io/tech-rebalance-dashboard/"
        try:
            need = force
            if not force:
                from admin_gui.services import link_diagnostics as ld
                for a in self.repo.load():
                    if not a.get("enabled", True):
                        continue
                    code, _ = ld.http_status(base + f"{a.get('id')}/data.json")
                    if code != 200:
                        need = True
                        break
            if not need:
                return
            with LOG.action("產生 Dashboard init page", ctx=self.gh.repo) as act:
                ok, msg = probes.trigger_publish_dashboard(self.gh.repo)
                act.step("觸發 publish_dashboard.yml", "ok" if ok else "fail", msg)
        except Exception as e:   # noqa: BLE001  檢查失敗不影響使用
            LOG.note("產生 Dashboard init page", "warn", f"{type(e).__name__}: {str(e)[:120]}")

    def _start_nav_refresh(self):
        from PySide6.QtCore import QTimer
        from admin_gui.services import probes
        from admin_gui.services.action_log import LOG
        if self._nav_pending:
            return
        with LOG.action("查詢即時 NAV", ctx=self.repo_slug) as a:
            ok, msg = probes.trigger_refresh_nav(self.gh.repo)
            a.step("觸發 refresh_nav.yml", "ok" if ok else "fail", msg)
        if not ok:
            QMessageBox.information(self, "即時 NAV", msg)
            return
        self._nav_pending = True
        self._nav_secs = 0
        self._nav_snap = {}
        self.refresh()                                   # 立刻顯示「查詢中… 0s」
        self._nav_counter = QTimer(self); self._nav_counter.setInterval(1000)
        self._nav_counter.timeout.connect(self._nav_tick); self._nav_counter.start()
        self._nav_poller = QTimer(self); self._nav_poller.setInterval(4000)
        self._nav_poller.timeout.connect(self._nav_poll); self._nav_poller.start()

    def _nav_tick(self):
        """每秒更新「查詢中… Ns」（只動 NAV 欄文字，不重建整表）。"""
        self._nav_secs += 1
        for r in range(self.table.rowCount()):
            it = self.table.item(r, self._NAV_COL)
            if it and it.text().startswith("⏳"):
                it.setText(f"⏳ 查詢中… {self._nav_secs}s")

    def _nav_poll(self):
        from admin_gui.services import probes
        from admin_gui.services.action_log import LOG
        status, concl = probes.last_refresh_nav_result(self.gh.repo)
        if concl == "success":
            self._nav_stop()
            self._nav_snap = probes.read_nav_snapshot(self.gh.repo)
            LOG.note("即時 NAV", "ok", f"完成（{self._nav_secs}s），{len(self._nav_snap)} 帳戶")
            self.refresh()
        elif concl in ("failure", "cancelled", "timed_out"):
            self._nav_stop()
            LOG.note("即時 NAV", "fail", f"workflow {concl}")
            self.refresh()
        elif self._nav_secs >= 150:
            self._nav_stop()
            LOG.note("即時 NAV", "warn", "查詢逾時（150s）")
            self.refresh()

    def _nav_stop(self):
        self._nav_pending = False
        for t in ("_nav_counter", "_nav_poller"):
            tm = getattr(self, t, None)
            if tm:
                tm.stop()

    def _selected_id(self) -> Optional[str]:
        row = self.table.currentRow()
        if row < 0:
            return None
        it = self.table.item(row, 0)
        return it.data(Qt.UserRole) if it else None

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
            self._start_nav_refresh()       # 新增成功 → 立刻查即時 NAV，讓使用者感受連上了
            self._ensure_init_pages(force=True)   # 新增帳號 → 產生 dashboard init page

    def _edit(self):
        acc_id = self._selected_id()
        if not acc_id:
            return
        dlg = AccountDialog(self.catalog, self.gh, self.repo, self.repo.get(acc_id), self)
        if dlg.exec() == QDialog.Accepted:
            self.refresh()

    def _delete(self):
        from admin_gui.services.action_log import LOG
        acc_id = self._selected_id()
        if not acc_id:
            return
        acc = self.repo.get(acc_id) or {}
        if QMessageBox.question(self, "刪除確認",
            f"刪除「{acc.get('label')}」？\n• 從 accounts.json 移除\n"
            f"• 保留 {acc.get('data_dir')}/ 歷史") != QMessageBox.Yes:
            return
        with LOG.action("刪除帳戶", ctx=getattr(self, "repo_slug", "")) as a:
            a.step("目標", "ok", f"id={acc_id} label={acc.get('label')}")
            self.repo.delete(acc_id)
            a.step("從 accounts.json 移除", "ok", f"id={acc_id}（保留 {acc.get('data_dir')}/）")
            try:
                publish_accounts_to_dashboard(self.gh.repo, self.repo.load(), a)
            except Exception as e:  # noqa: BLE001
                a.step("同步 accounts.json → dashboard", "fail", str(e)[:160])
        self.refresh()
