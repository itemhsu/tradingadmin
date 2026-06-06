"""admin_gui/views/overview_view.py — 總覽＝全域管理（Phase A-2 重設計）。

只放跟個別帳戶無關的：Email 發送、Dashboard 推送、環境/登入、全域 log。
帳戶 NAV/CRUD 全在「帳戶」分頁，總覽不再重複。
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox, QLabel,
    QPushButton, QLineEdit, QDialog, QDialogButtonBox, QMessageBox, QPlainTextEdit,
)
from PySide6.QtCore import QTimer, Qt

from admin_gui.services.gh_client import GhClient, GhError
from admin_gui.services.audit_log import AuditLog
from admin_gui.services.global_config import GlobalConfig
from admin_gui.services import probes

# 機密 Secret（遮罩、有「設定/更新」對話框）。EMAIL_SENDER 雖也必須是 repo secret，
# 但它有自己的「寄件人」欄 + 「儲存寄件人」按鈕（_save_sender 會推成 secret），
# 不放進這裡以免出現「重複的輸入窗格」；它的就緒狀態顯示在寄件人欄旁（見 refresh）。
_GLOBAL_SECRETS = ["EMAIL_PASSWORD", "PAGES_TOKEN"]


# 回測分析用共用 URL（momentum/index.html 讀 pub engine results/，資料通用）
_SHARED_BACKTEST_URL = "https://itemhsu.github.io/tech-rebalance-dashboard/momentum/"


def _dashboard_host(owner: str) -> str:
    """每個使用者有自己的 dashboard repo（個人 NAV 資料）。"""
    return f"https://{owner}.github.io/tech-rebalance-dashboard"


def dashboard_backtest_url(_owner: str = "") -> str:
    """回測分析：共用，所有用戶都指向同一個 viewer（資料來自 pub engine）。"""
    return _SHARED_BACKTEST_URL


def dashboard_mvp_url(owner: str, account: str = "1") -> str:
    """個人持倉 Dashboard：各用戶自己的 repo。"""
    return f"{_dashboard_host(owner)}/mvp_dashboard.html?a={account}"


_EMAIL_PASS_HELP = """<b>Gmail App 密碼（16 碼）取得步驟：</b><br>
1. 前往 <a href="https://myaccount.google.com/apppasswords">myaccount.google.com/apppasswords</a><br>
2. 登入你要用來寄信的 Gmail 帳號<br>
3. 「選擇應用程式」→ 其他 → 輸入名稱（如 TradingBot）<br>
4. 點「產生」→ 複製那 16 個字母（中間的空格不用複製）<br>
5. 貼到下方輸入框<br><br>
<small>⚠ 需先在 Gmail 啟用「兩步驟驗證」才能使用 App 密碼。<br>
如果你用的是 SendGrid，這裡填 SendGrid API Key。</small>"""


class _SetSecretDialog(QDialog):
    def __init__(self, name, parent=None):
        import webbrowser
        super().__init__(parent); self.setWindowTitle(f"設定 {name}")
        v_layout = QVBoxLayout(self)

        # EMAIL_PASSWORD 特別加說明
        if name == "EMAIL_PASSWORD":
            help_lbl = QLabel(_EMAIL_PASS_HELP)
            help_lbl.setOpenExternalLinks(True)
            help_lbl.setWordWrap(True)
            help_lbl.setStyleSheet("background:#f0f9ff;border:1px solid #bae6fd;"
                                   "border-radius:6px;padding:10px;font-size:12px;")
            v_layout.addWidget(help_lbl)

        f = QFormLayout()
        self.v = QLineEdit(); self.v.setEchoMode(QLineEdit.Password)
        self.v.setMinimumWidth(280)
        f.addRow(f"{name}：", self.v)
        f.addRow(QLabel("⚠ 經 gh 寫入 GitHub Secrets，不存本機檔。"))
        v_layout.addLayout(f)
        b = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        b.accepted.connect(self.accept); b.rejected.connect(self.reject)
        v_layout.addWidget(b)
        self.resize(420, 10)          # 寬一點，說明文字不換行太多


class OverviewView(QWidget):
    def __init__(self, repo_slug: str = "itemhsu/tech-rebalance", parent=None):
        super().__init__(parent)
        self.repo_slug = repo_slug
        self.gh = GhClient(repo_slug)
        self.audit = AuditLog()
        self.config = GlobalConfig()

        # 最外層：頂部相容性警告橫幅（預設隱藏）+ 下方兩欄內容。
        outer = QVBoxLayout(self)
        self.drift_banner = QLabel("")
        self.drift_banner.setWordWrap(True)
        self.drift_banner.setVisible(False)
        self.drift_banner.setStyleSheet(
            "background:#7f1d1d;color:#fecaca;padding:8px 12px;border-radius:6px;"
            "font-size:12px;")
        outer.addWidget(self.drift_banner)

        # 兩欄佈局：左欄=Email 發送，右欄=環境/登入＋全域日誌；
        # 兩欄各佔一半、平均使用視窗寬度，右側不再留白。
        cols_w = QWidget(); cols = QHBoxLayout(cols_w); cols.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(cols_w)
        left_w = QWidget(); left = QVBoxLayout(left_w); left.setContentsMargins(0, 0, 0, 0)
        right_w = QWidget(); right = QVBoxLayout(right_w); right.setContentsMargins(0, 0, 0, 0)
        cols.addWidget(left_w, 1)
        cols.addWidget(right_w, 1)

        def _form(parent) -> QFormLayout:
            f = QFormLayout(parent)
            f.setFormAlignment(Qt.AlignLeft | Qt.AlignTop)
            f.setLabelAlignment(Qt.AlignLeft)   # 欄內標籤靠左，左緣整齊
            f.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
            return f

        # 📧 Email（寄件人明文 + App 密碼遮罩 + 測試發信給自己）
        gb = QGroupBox("📧 Email 發送")
        fm = _form(gb)
        # 寄件人 EMAIL_SENDER：非機密 → 直接顯示可編輯明文
        self.sender_edit = QLineEdit(self.config.email_sender())
        self.sender_edit.setPlaceholderText("you@gmail.com（會顯示，不是機密）")
        save_snd = QPushButton("儲存寄件人"); save_snd.clicked.connect(self._save_sender)
        # EMAIL_SENDER secret 就緒狀態（顯示在欄位旁，避免另開重複窗格）
        self.sender_status = QLabel("")
        self.sender_status.setStyleSheet("font-size:11px;")
        srow = QWidget(); sl = QHBoxLayout(srow); sl.setContentsMargins(0,0,0,0)
        sl.addWidget(self.sender_edit); sl.addWidget(self.sender_status); sl.addWidget(save_snd)
        fm.addRow("寄件人 EMAIL_SENDER", srow)
        # 機密 Secret（遮罩）
        self.sec_labels = {}
        for k in _GLOBAL_SECRETS:
            row = QWidget(); rl = QHBoxLayout(row); rl.setContentsMargins(0,0,0,0)
            lbl = QLabel("…"); self.sec_labels[k] = lbl
            btn = QPushButton("設定/更新"); btn.clicked.connect(lambda _=False, n=k: self._set(n))
            rl.addWidget(lbl); rl.addStretch(); rl.addWidget(btn)
            fm.addRow(k, row)
        # PAGES_TOKEN 指引：建 PAT（可寫 dashboard repo）才能把持倉資料發佈到 Dashboard
        pt_hint = QLabel(
            'PAGES_TOKEN＝可寫 <b>{帳號}/tech-rebalance-dashboard</b> 的權杖，'
            '每日才會把持倉資料推上 Dashboard。<br>'
            '建立：<a href="https://github.com/settings/personal-access-tokens/new">'
            'Fine-grained PAT</a> → Repository access 選該 dashboard repo → '
            'Permissions：Contents = Read and write → 產生後貼上方 PAGES_TOKEN。')
        pt_hint.setOpenExternalLinks(True)
        pt_hint.setWordWrap(True)
        pt_hint.setStyleSheet("color:#94a3b8;font-size:11px;")
        fm.addRow("", pt_hint)
        # 按鈕用自然寬度（不拉滿）：放 HBox + 右側留白
        test_btn = QPushButton("測試發信")
        test_btn.setFixedWidth(120)
        test_btn.clicked.connect(self._test_email)
        brow = QWidget(); bl = QHBoxLayout(brow); bl.setContentsMargins(0,0,0,0)
        bl.addWidget(test_btn); bl.addWidget(QLabel("給自己，無需密碼")); bl.addStretch()
        fm.addRow(brow)
        # 狀態 text 窗：較高、不要太寬，自動週期顯示
        self.email_log = QPlainTextEdit(); self.email_log.setReadOnly(True)
        self.email_log.setMinimumHeight(140)
        self.email_log.setMaximumHeight(180)
        self.email_log.setStyleSheet("font-family:monospace;font-size:11px;")
        fm.addRow(self.email_log)
        left.addWidget(gb)
        left.addStretch()

        # 測試發信輪詢計時器
        self._poll = QTimer(self)
        self._poll.setInterval(4000)   # 每 4 秒查一次
        self._poll.timeout.connect(self._poll_tick)
        self._poll_secs = 0

        # 🔧 環境 / 登入
        gb2 = QGroupBox("🔧 環境 / 登入")
        fe = _form(gb2)
        self.gh_lbl = QLabel("…"); fe.addRow("gh（GitHub CLI）", self.gh_lbl)
        # O-2：顯示 GitHub 登入名（不顯示 repo slug）
        self.user_lbl = QLabel("…"); fe.addRow("GitHub 登入", self.user_lbl)
        # O-3：Dashboard 回測分析網頁連結
        # 連結改用 linkActivated：點擊時先做相依檢查（寫進 log）再開瀏覽器
        self.mvp_lbl = QLabel("…"); self.mvp_lbl.setOpenExternalLinks(False)
        self.mvp_lbl.linkActivated.connect(
            lambda u: self._open_checked_link(u, "持倉 Dashboard"))
        fe.addRow("持倉 Dashboard", self.mvp_lbl)
        self.dash_lbl = QLabel("…"); self.dash_lbl.setOpenExternalLinks(False)
        self.dash_lbl.linkActivated.connect(
            lambda u: self._open_checked_link(u, "回測分析"))
        fe.addRow("回測分析", self.dash_lbl)
        mode = QLabel("純 API 模式（不需本機 clone）"); mode.setStyleSheet("color:#888;")
        fe.addRow("存取方式", mode)
        # 重新開設定精靈
        wiz_btn = QPushButton("⚙️ 重新執行設定精靈…")
        wiz_btn.clicked.connect(self._open_wizard)
        fe.addRow("", wiz_btn)
        # 兩 repo 模式：測試執行（dry-run）按鈕
        self.dryrun_btn = QPushButton("▶ 測試執行（dry-run，不下單）")
        self.dryrun_btn.clicked.connect(self._do_dryrun)
        self.dryrun_btn.setVisible(bool(self.config.get("repob_slug")))
        fe.addRow("", self.dryrun_btn)
        right.addWidget(gb2)
        right.addStretch()
        self.refresh()

    def _do_dryrun(self):
        """觸發 Repo B 的 dry-run（不下單）。前置檢查 repo/workflow，失敗抓 run log。"""
        from admin_gui.services import workflow_runner as wr
        from admin_gui.services import preflight as pf
        from admin_gui.services.action_log import LOG
        slug = self.config.get("repob_slug")
        if not slug:
            QMessageBox.warning(self, "尚未建立", "請先在精靈用「建立交易系統」建立 Repo B。")
            return
        with LOG.action("測試執行 dry-run", ctx=slug) as a:
            ready = pf.preflight(a, [
                pf.GhAuth(),
                pf.RepoExists(slug),
                pf.WorkflowFile("daily.yml", slug),     # 薄殼用 daily.yml
            ])
            if not ready:
                QMessageBox.warning(self, "前置檢查未過",
                    "缺資源無法觸發（詳見日誌分頁，可📧發送 log）：\n"
                    + "\n".join(f"• {s.name}: {s.detail}" for s in a.problems()))
                return
            try:
                ok = wr.run_workflow(slug, dry_run=True)
                a.step("trigger run_workflow", "ok" if ok else "fail", f"slug={slug}")
            except Exception as e:  # noqa: BLE001
                a.step("trigger run_workflow", "fail", f"{type(e).__name__}: {str(e)[:160]}")
                QMessageBox.warning(self, "觸發失敗", str(e)); return
        if ok:
            QMessageBox.information(self, "已觸發",
                f"{slug} 的測試執行（dry-run）已送出。\n到該 repo 的 Actions 看結果。")
        else:
            QMessageBox.warning(self, "觸發失敗", "gh 觸發 workflow 失敗，請確認登入與權限。")

    def _open_checked_link(self, url: str, label: str):
        """點外部連結：先逐一檢查相依檔（寫進 log），再開瀏覽器。
        讓 dashboard 的 404/權限問題直接進 log，使用者不必回傳畫面。"""
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl
        from admin_gui.services.action_log import LOG
        from admin_gui.services import link_diagnostics as ld
        with LOG.action(f"開啟連結：{label}", ctx=self.repo_slug) as a:
            a.step("url", "ok", url)
            try:
                ld.diagnose_link(url, a)
            except Exception as e:   # noqa: BLE001  檢查失敗不擋開連結
                a.step("相依檢查", "fail", f"{type(e).__name__}: {str(e)[:120]}")
        QDesktopServices.openUrl(QUrl(url))

    def _open_wizard(self):
        """重新開首次設定精靈：可改 repo 或重新 gh 登入。"""
        from admin_gui.views.wizard import SetupWizard
        old_slug = self.config.get("repo_slug")
        dlg = SetupWizard(self.config, self)
        dlg.exec()
        new_slug = self.config.get("repo_slug")
        if new_slug and new_slug != old_slug:
            QMessageBox.information(
                self, "已更新 repo",
                f"目標 repo 已改為 {new_slug}。\n請重新啟動 App 以套用新 repo。")
        else:
            self.refresh()

    def refresh(self):
        try:
            existing = self.gh.list_secret_names(); gh_ok = True
        except Exception:
            existing = set(); gh_ok = False
        for k, lbl in self.sec_labels.items():
            lbl.setText("✅ 已設" if k in existing else "❌ 未設")
        # EMAIL_SENDER secret 就緒狀態（顯示在寄件人欄旁，不另開窗格）
        if "EMAIL_SENDER" in existing:
            self.sender_status.setText("✅ secret 已設")
            self.sender_status.setStyleSheet("font-size:11px;color:#16a34a;")
        else:
            self.sender_status.setText("❌ 未推 secret → 按「儲存寄件人」")
            self.sender_status.setStyleSheet("font-size:11px;color:#dc2626;")
        ok2, msg2 = probes.probe_gh()
        self.gh_lbl.setText(("✅ " if ok2 else "❌ ") + msg2)

        # O-2/O-3：登入名 + Dashboard 連結（每人各自的 dashboard repo）
        login = probes.gh_login()
        self.user_lbl.setText(login or "（未登入）")
        owner = self.repo_slug.split("/")[0] if "/" in self.repo_slug else (login or "")
        if owner:
            self.mvp_lbl.setText(
                f'<a href="{dashboard_mvp_url(owner)}">📊 前往持倉 Dashboard</a>')
            self.dash_lbl.setText(
                f'<a href="{dashboard_backtest_url(owner)}">📈 前往回測分析</a>')
        else:
            self.mvp_lbl.setText("（登入後顯示）")
            self.dash_lbl.setText("（登入後顯示）")

        self._refresh_drift_banner()

    def _refresh_drift_banner(self):
        """兩-repo 架構：schemas/ 在 pub engine、引擎以 git+ 釘版，不存在 fork 漂移。
        漂移由「更新引擎版本」管理，這裡不再讀 Repo B 的 schemas/。"""
        self.drift_banner.setVisible(False)

    def _set(self, name):
        from admin_gui.services.action_log import LOG
        dlg = _SetSecretDialog(name, self)
        if dlg.exec() != QDialog.Accepted or not dlg.v.text():
            return
        raw = dlg.v.text()
        value = "".join(raw.split())   # 去所有空白（App Password 顯示常含空格）
        with LOG.action(f"設定 secret {name}", ctx=self.repo_slug) as a:
            # 只記「形狀」診斷（長度/空白/換行），不記明碼，不記含值的指令。
            a.step("輸入診斷", "ok",
                   f"{name} 原始 len={len(raw)} 去空白後 len={len(value)} "
                   f"有空白={raw != value} 有換行={chr(10) in raw or chr(13) in raw}")
            a.step("gh 指令", "ok",
                   f"gh secret set {name} --repo {self.repo_slug}（值經 stdin，不入命令列）")
            # 半遮罩：露頭尾+長度，日後除錯可比對「值是否存對」（例：len=1 即被存成 -）
            from admin_gui.services.action_log import half_mask
            a.step("secret 值(半遮罩)", "ok", f"{name} ⇒ {half_mask(value)}")
            try:
                self.gh.set_secret(name, value)
                a.step("gh set_secret 結果", "ok", "rc=0 已寫入")
                self.audit.record("set_secret", name)
                QMessageBox.information(self, "完成",
                    f"{name} 已設定（{len(value)} 字元，已寫入 GitHub Secret）")
            except GhError as e:
                a.step("gh set_secret 結果", "fail", str(e)[:200])
                QMessageBox.warning(self, "失敗", str(e))
        self.refresh()

    def _save_sender(self):
        from admin_gui.services.action_log import LOG
        v = self.sender_edit.text().strip()
        if not v:
            self._log_line("❌ 寄件人不可空白"); return
        with LOG.action("儲存寄件人", ctx=self.repo_slug) as a:
            self.config.set_email_sender(v)              # 本機（給 UI 預填）
            a.step("save local config", "ok", v)
            # 關鍵：workflow 讀 secrets.EMAIL_SENDER，必須推成 GitHub secret，
            # 否則 test_email / daily 會「missing EMAIL_SENDER」失敗。
            try:
                self.gh.set_secret("EMAIL_SENDER", v)
                a.step("set GitHub secret EMAIL_SENDER", "ok", self.repo_slug)
                self.audit.record("set_secret", "EMAIL_SENDER")
                self._log_line(f"✅ 寄件人已存並推成 GitHub Secret：{v}")
            except GhError as e:
                a.step("set GitHub secret EMAIL_SENDER", "fail", str(e)[:160])
                self._log_line(f"❌ 本機已存，但推 GitHub Secret 失敗：{e}")
        self.refresh()

    def _log_line(self, text: str):
        self.email_log.appendPlainText(text)

    def _test_email(self):
        # 觸發雲端 test_email.yml 前，先做 preflight：依賴的 secret / workflow / auth
        # 都就緒才觸發（R8）。缺哪個 → log 直接寫明、不觸發（本案：EMAIL_SENDER 缺）。
        from admin_gui.services.action_log import LOG
        from admin_gui.services import preflight as pf
        self.email_log.clear()
        with LOG.action("測試發信", ctx=self.repo_slug) as a:
            ready = pf.preflight(a, [
                pf.GhAuth(),
                pf.Secret("EMAIL_SENDER", self.repo_slug),
                pf.Secret("EMAIL_PASSWORD", self.repo_slug),
                pf.WorkflowFile("test_email.yml", self.repo_slug),
            ])
            if not ready:
                miss = [s.detail and s.name for s in a.problems()]
                # 對使用者用白話列出缺什麼
                lines = [f"❌ {s.name.replace('preflight ','')}：{s.detail}"
                         for s in a.problems() if s.name.startswith("preflight ")
                         and s.detail == "MISSING"]
                self._log_line("無法測試發信，前置檢查未過：")
                for ln in (lines or ["（見日誌分頁細節）"]):
                    self._log_line("  " + ln)
                if any("EMAIL_SENDER" in (s.name or "") for s in a.problems()):
                    self._log_line("  → 請在上方填寄件人並按「儲存寄件人」（會自動設成 GitHub Secret）")
                return
            ok, msg = probes.trigger_test_email(repo=self.repo_slug)
            a.step("trigger test_email.yml", "ok" if ok else "fail", msg)
            self.audit.record("test_email", "EMAIL_PASSWORD", "ok" if ok else "fail")
            if not ok:
                self._log_line("❌ 觸發失敗：" + msg); return
        self._log_line("⏳ 已觸發測試發信，自動追蹤狀態中…")
        self._poll_secs = 0
        self._poll.start()

    def _poll_tick(self):
        self._poll_secs += 4
        status, conclusion = probes.last_test_email_result(repo=self.repo_slug)
        if conclusion == "success":
            self._poll.stop()
            self._log_line(f"✅ 正常（{self._poll_secs}s）— 測試信已寄出，請查收信箱")
        elif conclusion in ("failure", "cancelled", "timed_out"):
            self._poll.stop()
            # 杜絕安靜失敗：抓 run log 撈出真正原因，不再猜「多半是密碼錯」
            reason = probes.last_test_email_failure_reason(repo=self.repo_slug)
            from admin_gui.services.action_log import LOG
            LOG.note("test_email run", "fail", f"{conclusion}: {reason or '(讀不到 log)'}")
            if reason:
                self._log_line(f"❌ 失敗（{conclusion}）真正原因：{reason}")
            else:
                self._log_line(f"❌ 失敗（{conclusion}）— 到 Actions 看 test_email 的 log；"
                               "若是 App 密碼錯請重設 EMAIL_PASSWORD")
        elif self._poll_secs >= 120:
            self._poll.stop()
            self._log_line("⚠ 等待逾時（120s），請稍後重試或到 Actions 看 test_email")
        else:
            self._log_line(f"⏳ 執行中…（{self._poll_secs}s，狀態 {status or '排隊'}）")
