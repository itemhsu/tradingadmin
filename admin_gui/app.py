"""admin_gui/app.py — 交易系統管理控制台（PySide6 桌面 GUI）進入點。

純 API 模式：不需 clone repo，只透過 GitHub API（gh CLI）讀寫 accounts.json、
workflow yml 與少數資料檔。只要 gh 已登入 + 指定一個 repo（owner/repo）即可。

執行：
    pip install PySide6
    python -m admin_gui.app                       # 用 config 記住的 repo
    python -m admin_gui.app itemhsu/tech-rebalance # 指定 repo slug
"""
from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication, QMainWindow, QTabWidget

from admin_gui.views.overview_view import OverviewView
from admin_gui.views.accounts_view import AccountsView
from admin_gui.views.schedule_view import ScheduleView
from admin_gui.views.log_view import LogView

_DEFAULT_SLUG = "itemhsu/tech-rebalance"
_DISCARDED_REPOB_NAME = "tech-rebalance-data"  # 廢棄；如殘留快取須忽略


def _sanitize_slug(slug: str) -> str:
    """若 slug 指向已廢棄的 tech-rebalance-data，回 _DEFAULT_SLUG。"""
    if slug and slug.endswith(f"/{_DISCARDED_REPOB_NAME}"):
        return _DEFAULT_SLUG
    return slug


class MainWindow(QMainWindow):
    def __init__(self, repo_slug: str, store=None):
        super().__init__()
        self.repo_slug = repo_slug
        self.setWindowTitle(f"交易系統管理控制台 — {repo_slug}")
        self.resize(960, 620)

        if store is None:
            from admin_gui.services.repo_store import make_store
            store = make_store(repo_slug=repo_slug)

        # 4 分頁（總覽=全域設定 / 帳戶 / 排程 / 日誌）
        tabs = QTabWidget()
        tabs.addTab(OverviewView(repo_slug), "📊 總覽")
        tabs.addTab(AccountsView(repo_slug, store=store), "👥 帳戶")
        tabs.addTab(ScheduleView(repo_slug, store=store), "⏰ 排程")
        tabs.addTab(LogView(repo_slug), "📜 日誌")
        self.setCentralWidget(tabs)


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv

    # macOS 從 Finder/DMG 啟動不繼承 shell PATH → 補上 Homebrew 等路徑，才找得到 gh
    from admin_gui.services.env_fix import ensure_path
    ensure_path()

    app = QApplication(argv[:1])

    # 立刻顯示 splash —— 讓使用者第一時間看到畫面（後面的 import/建構才慢）
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtGui import QPixmap, QColor, QPainter, QFont
    from PySide6.QtWidgets import QSplashScreen
    _pix = QPixmap(380, 130); _pix.fill(QColor("#0f172a"))
    _p = QPainter(_pix); _p.setPen(QColor("#e2e8f0"))
    _p.setFont(QFont("", 16, QFont.Bold)); _p.drawText(_pix.rect(), Qt.AlignCenter,
        "TradingAdmin\n啟動中…"); _p.end()
    splash = QSplashScreen(_pix)
    splash.show(); app.processEvents()       # 立刻畫出 splash

    from admin_gui.services.global_config import GlobalConfig
    from admin_gui.views.wizard import SetupWizard
    cfg = GlobalConfig()

    # 啟動 log（含 gh 探測，會連網）→ 排到事件迴圈、視窗顯示後才跑，不擋啟動畫面（P0）。
    def _startup_log():
        try:
            from admin_gui import __version__ as _ver
            from admin_gui.services.action_log import LOG
            with LOG.action("App 啟動") as _a:
                _a.step("版本", "ok", f"TradingAdmin v{_ver}")
        except Exception:   # noqa: BLE001  啟動記 log 失敗不可擋住開 App
            pass

    if len(argv) > 1:
        slug = argv[1]
    else:
        # W-1：每次啟動都顯示精靈（保留「略過」）；略過則用既有設定。
        # 精靈 UI 立刻出現；gh 檢查在背景（見 wizard._refresh_gh/_refresh_status）。
        wiz = SetupWizard(cfg)
        splash.finish(wiz)                   # splash 收掉，精靈接手
        QTimer.singleShot(0, _startup_log)   # 視窗顯示後才記啟動 log（不阻塞）
        wiz.exec()
        raw = wiz.chosen_repo or cfg.get("repob_slug") or cfg.get("repo_slug") or _DEFAULT_SLUG
        slug = _sanitize_slug(raw)

    win = MainWindow(slug)
    splash.finish(win)        # 指定 slug 的路徑（未開精靈）也要收掉 splash
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
