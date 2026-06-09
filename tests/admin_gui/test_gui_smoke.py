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


def _local_manifest():
    """從本地 brokers/ + strategies/ fixture 組一個 manifest（取代 pub engine fetch）。"""
    import glob, json
    brokers = {}
    for f in glob.glob(str(ROOT / "brokers" / "*.json")):
        name = Path(f).stem
        if "schema" in name:
            continue
        spec = json.loads(Path(f).read_text(encoding="utf-8"))
        spec["environments"] = list((spec.get("environments") or {}).keys())
        spec["required_env"] = (spec.get("auth") or {}).get("required_env", [])
        brokers[name] = spec
    strategies = [Path(f).stem for f in glob.glob(str(ROOT / "strategies" / "*.json"))
                  if "schema" not in Path(f).stem]
    return {"brokers": brokers, "strategies": sorted(strategies)}


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
    monkeypatch.setattr(pr, "gh_login", lambda *a, **k: "itemhsu")
    # Catalog 改讀 pub engine manifest → 測試用本地 fixture 取代，離線且確定
    from admin_gui.services.catalog import Catalog
    monkeypatch.setattr(Catalog, "_fetch_pub_manifest", lambda self: _local_manifest())


SLUG = "itemhsu/tech-rebalance"


def _local_store():
    from admin_gui.services.repo_store import LocalStore
    return LocalStore(ROOT)


def test_overview_global_settings_builds(qapp, no_net):
    from admin_gui.views.overview_view import OverviewView
    v = OverviewView(SLUG)
    # EMAIL_SENDER 有自己的欄+「儲存寄件人」（不在遮罩列，避免重複窗格）；密碼才在遮罩列
    assert v.sender_edit is not None
    assert "EMAIL_PASSWORD" in v.sec_labels
    assert "EMAIL_SENDER" not in v.sec_labels
    assert "SENDGRID_API_KEY" not in v.sec_labels
    assert "DASHBOARD_PUSH_TOKEN" not in v.sec_labels


def test_overview_login_and_dashboard(qapp, no_net):
    """O-1/O-2/O-3：不顯示 repo slug、顯示登入名、回測分析連結。"""
    from admin_gui.views.overview_view import (
        OverviewView, dashboard_backtest_url, dashboard_mvp_url)
    v = OverviewView(SLUG)
    v.refresh()
    # G-70：登入名
    assert "itemhsu" in v.user_lbl.text()
    # G-71：回測分析連結依登入名「合成」（非寫死），文字改為「前往回測分析」
    assert dashboard_backtest_url("itemhsu") == \
        "https://itemhsu.github.io/tech-rebalance-dashboard/momentum/"
    assert "前往回測分析" in v.dash_lbl.text() and "itemhsu.github.io" in v.dash_lbl.text()
    # 新增：持倉 Dashboard 連結，URL 由登入名 + 帳戶「合成」
    assert dashboard_mvp_url("itemhsu", "1") == \
        "https://itemhsu.github.io/tech-rebalance-dashboard/mvp_dashboard.html?a=1"
    assert "前往持倉 Dashboard" in v.mvp_lbl.text() and "mvp_dashboard.html?a=1" in v.mvp_lbl.text()
    # G-69：不顯示 repo slug
    from PySide6.QtWidgets import QLabel
    blob = " ".join(lbl.text() for lbl in v.findChildren(QLabel))
    assert "itemhsu/tech-rebalance" not in blob


def test_accounts_view_builds_and_lists(qapp, no_net):
    from admin_gui.views.accounts_view import AccountsView, _HEADERS
    v = AccountsView(SLUG, store=_local_store())
    assert v.table.rowCount() >= 4
    # G-64：移除 id 欄；後續新增「操作」欄（Dashboard 按鈕）→ 8 欄，標頭不含 id
    assert v.table.columnCount() == 8
    assert "id" not in _HEADERS
    assert _HEADERS[-1] == "操作"


def test_account_dialog_fields_by_broker(qapp, no_net):
    """G-65/G-68：金鑰欄位依券商動態 —— Alpaca 2 欄、Tradier 1 欄（Token）。"""
    from admin_gui.views.accounts_view import AccountsView, AccountDialog
    v = AccountsView(SLUG, store=_local_store())
    dlg = AccountDialog(v.catalog, v.gh, v.repo, None)
    dlg.broker_cmb.setCurrentText("alpaca")
    assert set(dlg.cred_edits.keys()) == {"API_KEY", "API_SECRET"}
    dlg.broker_cmb.setCurrentText("tradier")
    assert set(dlg.cred_edits.keys()) == {"API_KEY"}   # 只一個 token，account_id 自動


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
    # 阻斷網路：probe_gh 未登入 → 不觸發 _detect_user 的 gh 呼叫
    monkeypatch.setattr(wz, "probe_gh", lambda *a, **k: (False, "gh 未登入"))
    from admin_gui.services.global_config import GlobalConfig
    cfg = GlobalConfig(tmp_path / "config.json")
    cfg.set("repo_slug", "itemhsu/tech-rebalance")
    w = wz.SetupWizard(cfg)
    # 只輸入帳號 → 內部組 {帳號}/tech-rebalance（Repo B）
    assert w.user_edit.text() == "itemhsu"        # 由 repo_slug 帶出帳號
    assert w._repob_slug() == "itemhsu/tech-rebalance"
    # 兩-repo 動作可呼叫；fork 路線已移除
    for fn in ("_do_build_repob", "_do_update_engine"):
        assert callable(getattr(w, fn))
    for gone in ("_do_fork", "_do_pages", "_do_actions", "_do_sync_upstream"):
        assert not hasattr(w, gone)
    # 精靈不含 Email/帳戶字樣、不揭露範本 slug
    texts = []
    for lbl in w.findChildren(type(w.gh_lbl)):
        texts.append(lbl.text())
    blob = " ".join(texts)
    assert "EMAIL" not in blob.upper() and "密碼" not in blob and "帳戶" not in blob


def test_publish_accounts_to_dashboard_public_only(qapp, monkeypatch):
    """bug4：帳戶異動同步到 dashboard repo 的 accounts.json，只含公開欄位。"""
    import json
    import admin_gui.services.repo_store as rs
    cap = {}
    class FakeStore:
        def write_text(self, path, text, message=""):
            cap.update(path=path, text=text)
    monkeypatch.setattr(rs, "make_store",
                        lambda repo_slug=None, **k: cap.update(slug=repo_slug) or FakeStore())
    from admin_gui.views.accounts_view import publish_accounts_to_dashboard
    accts = [{"id": "1", "label": "trade", "strategy": "mom_6m_t20",
              "enabled": True, "secret_prefix": "ACC1", "broker": "alpaca"}]
    publish_accounts_to_dashboard("o/tech-rebalance", accts)
    assert cap["slug"] == "o/tech-rebalance-dashboard"
    assert cap["path"] == "accounts.json"
    d = json.loads(cap["text"])
    assert d["accounts"][0] == {"id": "1", "label": "trade",
                                "strategy": "mom_6m_t20", "enabled": True}
    # 不得外洩內部/敏感欄位
    assert "secret_prefix" not in d["accounts"][0]
    assert "broker" not in d["accounts"][0]
