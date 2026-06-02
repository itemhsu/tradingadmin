"""admin_gui/views/wizard.py — 首次啟動精靈（純 API 模式，不 clone）。

只需兩件事：① gh 登入（取得 GitHub 存取權）② 指定要管理的 repo（owner/repo）。
不下載任何代碼。完成後寫 setup_done 旗標，下次不再跳。
"""
from __future__ import annotations

import subprocess

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QMessageBox, QWidget,
)

from admin_gui.services.probes import probe_gh
from admin_gui.services.global_config import GlobalConfig

_DEFAULT_SLUG = "itemhsu/tech-rebalance"


def is_first_run(config: GlobalConfig) -> bool:
    return not config.load().get("setup_done", False)


class SetupWizard(QDialog):
    """逐步引導；完成回傳使用者選定的 repo slug（owner/repo）。"""

    def __init__(self, config: GlobalConfig, parent=None):
        super().__init__(parent)
        self.config = config
        self.chosen_repo = ""
        self.setWindowTitle("首次設定精靈")
        self.resize(560, 300)
        lay = QVBoxLayout(self)

        lay.addWidget(QLabel(
            "<b>歡迎！</b>本工具用 GitHub API 直接管理你的交易設定，"
            "<b>不會下載任何代碼到你的電腦</b>。只需兩步："))

        # 1) gh 登入
        self.gh_lbl = QLabel("①GitHub 登入：檢查中…")
        lay.addWidget(self.gh_lbl)
        gh_btn = QPushButton("執行 gh auth login（開瀏覽器授權）")
        gh_btn.clicked.connect(self._gh_login)
        lay.addWidget(gh_btn)

        # 2) 指定 repo slug
        lay.addWidget(QLabel("②要管理的 GitHub repo（格式 owner/repo）："))
        srow = QWidget(); sl = QHBoxLayout(srow); sl.setContentsMargins(0, 0, 0, 0)
        self.slug_edit = QLineEdit(config.get("repo_slug") or _DEFAULT_SLUG)
        self.slug_edit.setPlaceholderText("例如 itemhsu/tech-rebalance")
        check_btn = QPushButton("檢查")
        check_btn.clicked.connect(self._check_repo)
        sl.addWidget(self.slug_edit); sl.addWidget(check_btn)
        lay.addWidget(srow)
        self.repo_lbl = QLabel(""); lay.addWidget(self.repo_lbl)

        lay.addStretch()
        brow = QWidget(); bl = QHBoxLayout(brow)
        skip = QPushButton("略過精靈"); skip.clicked.connect(self.reject)
        done = QPushButton("完成，開始使用 →"); done.clicked.connect(self._finish)
        bl.addWidget(skip); bl.addStretch(); bl.addWidget(done)
        lay.addWidget(brow)

        self._refresh_gh()

    def _refresh_gh(self):
        ok, msg = probe_gh()
        self.gh_lbl.setText(("✅ " if ok else "❌ ") + "①GitHub 登入：" + msg)

    def _gh_login(self):
        try:
            subprocess.Popen(["gh", "auth", "login", "--web"])
            QMessageBox.information(self, "授權中",
                "已開啟 gh 登入流程，請依終端機/瀏覽器指示完成，再回來按重新整理。")
        except FileNotFoundError:
            QMessageBox.warning(self, "找不到 gh", "請先安裝 GitHub CLI（gh）。")
        self._refresh_gh()

    def _check_repo(self) -> bool:
        slug = self.slug_edit.text().strip()
        if "/" not in slug:
            self.repo_lbl.setText("❌ 格式應為 owner/repo"); return False
        try:
            r = subprocess.run(["gh", "api", f"repos/{slug}", "--jq", ".full_name"],
                               capture_output=True, text=True, timeout=20)
            if r.returncode == 0 and r.stdout.strip():
                self.repo_lbl.setText(f"✅ 找到 repo：{r.stdout.strip()}")
                return True
            self.repo_lbl.setText(f"❌ 找不到或無權限：{slug}")
            return False
        except Exception as e:  # noqa: BLE001
            self.repo_lbl.setText(f"❌ 檢查失敗：{str(e)[:120]}")
            return False

    def _finish(self):
        slug = self.slug_edit.text().strip()
        if "/" not in slug:
            QMessageBox.warning(self, "格式錯", "repo 應為 owner/repo 格式。"); return
        self.chosen_repo = slug
        self.config.set("setup_done", True)
        self.config.set("repo_slug", slug)
        self.accept()
