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

# 機密 Secret（遮罩、只顯示有無）。一般使用者只需要 EMAIL_PASSWORD（email App 密碼）。
# 移除：SendGrid（已棄用）、DASHBOARD_PUSH_TOKEN（幽靈設定，系統實際用 PAGES_TOKEN，
#       屬一次性基礎建設、非使用者該碰的東西）。EMAIL_SENDER 非機密 → 走 GlobalConfig 明文。
_GLOBAL_SECRETS = ["EMAIL_PASSWORD"]


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
        srow = QWidget(); sl = QHBoxLayout(srow); sl.setContentsMargins(0,0,0,0)
        sl.addWidget(self.sender_edit); sl.addWidget(save_snd)
        fm.addRow("寄件人 EMAIL_SENDER", srow)
        # 機密 Secret（遮罩）
        self.sec_labels = {}
        for k in _GLOBAL_SECRETS:
            row = QWidget(); rl = QHBoxLayout(row); rl.setContentsMargins(0,0,0,0)
            lbl = QLabel("…"); self.sec_labels[k] = lbl
            btn = QPushButton("設定/更新"); btn.clicked.connect(lambda _=False, n=k: self._set(n))
            rl.addWidget(lbl); rl.addStretch(); rl.addWidget(btn)
            fm.addRow(k, row)
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
        self.mvp_lbl = QLabel("…"); self.mvp_lbl.setOpenExternalLinks(True)
        fe.addRow("持倉 Dashboard", self.mvp_lbl)
        self.dash_lbl = QLabel("…"); self.dash_lbl.setOpenExternalLinks(True)
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
        """觸發 Repo B 的 dry-run（不下單）。"""
        from admin_gui.services import workflow_runner as wr
        slug = self.config.get("repob_slug")
        if not slug:
            QMessageBox.warning(self, "尚未建立", "請先在精靈用「建立交易系統」建立 Repo B。")
            return
        try:
            ok = wr.run_workflow(slug, dry_run=True)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "觸發失敗", str(e)); return
        if ok:
            QMessageBox.information(self, "已觸發",
                f"{slug} 的測試執行（dry-run）已送出。\n到該 repo 的 Actions 看結果。")
        else:
            QMessageBox.warning(self, "觸發失敗", "gh 觸發 workflow 失敗，請確認登入與權限。")

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
        """偵測 fork 引擎的 data-schema 版本是否與本 App 支援範圍錯位（fork 相容性 §6.1 ⑨）。"""
        from admin_gui.services import compat
        from admin_gui.services.repo_store import make_store
        warning = None
        try:
            files = make_store(self.repo_slug).list_dir("schemas")
            warning = compat.schema_drift_warning(files)
        except Exception:
            warning = None      # 讀不到（網路/權限）→ 不顯示，不打擾
        if warning:
            self.drift_banner.setText("⚠️ " + warning)
            self.drift_banner.setVisible(True)
        else:
            self.drift_banner.setVisible(False)

    def _set(self, name):
        dlg = _SetSecretDialog(name, self)
        if dlg.exec() != QDialog.Accepted or not dlg.v.text():
            return
        try:
            self.gh.set_secret(name, dlg.v.text())
            self.audit.record("set_secret", name)
            QMessageBox.information(self, "完成", f"{name} 已設定（不存本機）")
        except GhError as e:
            QMessageBox.warning(self, "失敗", str(e))
        self.refresh()

    def _save_sender(self):
        v = self.sender_edit.text().strip()
        self.config.set_email_sender(v)
        self.audit.record("edit", "EMAIL_SENDER", detail="寄件人")
        self._log_line(f"✅ 寄件人已存：{v}")

    def _log_line(self, text: str):
        self.email_log.appendPlainText(text)

    def _test_email(self):
        # 需求 22：不要密碼。觸發雲端 test_email.yml；之後自動輪詢顯示狀態。
        try:
            existing = self.gh.list_secret_names()
        except Exception:
            existing = set()
        if "EMAIL_PASSWORD" not in existing:
            self._log_line("❌ 尚未設定 EMAIL_PASSWORD，請先按上方「設定/更新」")
            return
        self.email_log.clear()
        ok, msg = probes.trigger_test_email()
        self.audit.record("test_email", "EMAIL_PASSWORD", "ok" if ok else "fail")
        if not ok:
            self._log_line("❌ " + msg); return
        self._log_line("⏳ 已觸發測試發信，自動追蹤狀態中…")
        self._poll_secs = 0
        self._poll.start()

    def _poll_tick(self):
        self._poll_secs += 4
        status, conclusion = probes.last_test_email_result()
        if conclusion == "success":
            self._poll.stop()
            self._log_line(f"✅ 正常（{self._poll_secs}s）— 測試信已寄出，請查收信箱")
        elif conclusion in ("failure", "cancelled", "timed_out"):
            self._poll.stop()
            self._log_line(f"❌ 失敗（{conclusion}）— 多半是 App 密碼錯，請重設 EMAIL_PASSWORD")
        elif self._poll_secs >= 120:
            self._poll.stop()
            self._log_line("⚠ 等待逾時（120s），請稍後重試或到 Actions 看 test_email")
        else:
            self._log_line(f"⏳ 執行中…（{self._poll_secs}s，狀態 {status or '排隊'}）")
