"""GUI 層冒煙（只在有裝 PySide6 時跑；無則 skip）。Phase A-2：3 分頁。

外部 I/O（gh / 網路）全 mock。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

pytest.importorskip("PySide6", reason="PySide6 未安裝（pip install PySide6）")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def no_net(monkeypatch):
    """擋掉 overview/accounts 的 gh / 網路呼叫。"""
    from admin_gui.services.gh_client import GhClient
    monkeypatch.setattr(GhClient, "list_secret_names", lambda self: {"EMAIL_SENDER"})
    monkeypatch.setattr(GhClient, "auth_ok", lambda self: True)
    import admin_gui.services.log_reader as lr
    monkeypatch.setattr(lr, "cron_runs", lambda *a, **k: [])
    import admin_gui.services.probes as pr
    monkeypatch.setattr(pr, "probe_gh", lambda *a, **k: (True, "gh 已登入"))


SLUG = "itemhsu/tech-rebalance"


def _local_store():
    from admin_gui.services.repo_store import LocalStore
    return LocalStore(ROOT)


def test_overview_global_settings_builds(qapp, no_net):
    from admin_gui.views.overview_view import OverviewView
    v = OverviewView(SLUG)
    # 寄件人是明文可編輯欄；機密只剩 EMAIL_PASSWORD（無 SendGrid、無 EMAIL_SENDER、無幽靈 DASHBOARD_PUSH_TOKEN）
    assert v.sender_edit is not None
    assert "EMAIL_PASSWORD" in v.sec_labels
    assert "SENDGRID_API_KEY" not in v.sec_labels
    assert "EMAIL_SENDER" not in v.sec_labels
    assert "DASHBOARD_PUSH_TOKEN" not in v.sec_labels


def test_accounts_view_builds_and_lists(qapp, no_net):
    from admin_gui.views.accounts_view import AccountsView
    v = AccountsView(SLUG, store=_local_store())
    assert v.table.rowCount() >= 4
    assert v.table.columnCount() == 8   # id/名稱/啟用/券商/環境/策略/NAV/日期


def test_schedule_view_builds(qapp):
    from admin_gui.views.schedule_view import ScheduleView
    v = ScheduleView(SLUG, store=_local_store())
    # 此公開 repo 不含可執行的 workflow（避免被 GitHub Actions 觸發），
    # 故只驗證 view 能建起來；實際 cron 行數視目標 repo 而定。
    assert v.table.columnCount() == 4


def test_mainwindow_is_four_tabs(qapp, no_net):
    from admin_gui.app import MainWindow
    w = MainWindow(SLUG, store=_local_store())
    assert w.centralWidget().count() == 4   # 總覽 / 帳戶 / 排程 / 日誌


def test_wizard_builds(qapp, monkeypatch, tmp_path):
    import admin_gui.views.wizard as wz
    monkeypatch.setattr(wz, "probe_gh", lambda *a, **k: (True, "gh 已登入"))
    from admin_gui.services.global_config import GlobalConfig
    w = wz.SetupWizard(GlobalConfig(tmp_path / "config.json"))
    assert "登入" in w.gh_lbl.text()
    # Fork 範本協助：範本欄與狀態標籤存在，且 _do_fork 可被呼叫（gh 未真的執行）
    assert w.template_edit.text()           # 預設帶範本 slug
    assert hasattr(w, "fork_lbl")
    assert callable(w._do_fork)
