"""G4：catalog 改讀 manifest、compat 引擎漂移、Overview 執行按鈕。"""
import os, sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from admin_gui.services.catalog import Catalog
from admin_gui.services import compat

_MANIFEST = {
    "engine_version": "1.0.4",
    "strategies": ["top10", "mom_6m_t20"],
    "brokers": {"alpaca": {"required_env": ["{PREFIX}_ALPACA_KEY", "{PREFIX}_ALPACA_SECRET"],
                           "environments": ["paper", "live"]}},
}


class _FakeStore:
    root = "/x"
    def list_dir(self, p): return []          # repo 無 strategies/brokers（repo_b）
    def read_json(self, p): raise FileNotFoundError(p)


# ── D. catalog from manifest ─────────────────────────────────────────────────
def test_catalog_strategies_from_manifest():
    c = Catalog(store=_FakeStore(), manifest=_MANIFEST)
    assert c.list_strategies() == ["top10", "mom_6m_t20"]   # 來自 manifest，非空目錄


def test_catalog_brokers_and_secrets_from_manifest():
    c = Catalog(store=_FakeStore(), manifest=_MANIFEST)
    assert c.list_brokers() == ["alpaca"]
    assert c.required_secrets("ACC1", "alpaca") == ["ACC1_ALPACA_KEY", "ACC1_ALPACA_SECRET"]
    assert c.broker_environments("alpaca") == ["paper", "live"]


def test_catalog_works_without_repo_dirs():
    """★ CAT-04：repo 沒有 strategies/brokers 目錄也能運作（核心回歸）。"""
    c = Catalog(store=_FakeStore(), manifest=_MANIFEST)
    assert c.list_strategies() and c.list_brokers()   # 不因空目錄而空


def test_catalog_static_fallback_when_no_manifest(monkeypatch):
    """無 manifest 且 pub fetch 失敗 → 用靜態保底清單（不讀 Repo B）。"""
    c = Catalog(manifest=None)
    monkeypatch.setattr(c, "_fetch_pub_manifest", lambda: None)
    assert "top10" in c.list_strategies()              # 靜態保底
    assert "alpaca" in c.list_brokers()


# ── E. engine drift from vendor ──────────────────────────────────────────────
def test_engine_version_from_vendor():
    assert compat.engine_version_from_vendor(
        ["tech_rebalance-1.0.4-py3-none-any.whl"]) == "1.0.4"
    assert compat.engine_version_from_vendor([]) is None


def test_engine_drift_match_silent():
    assert compat.engine_drift_warning(["tech_rebalance-1.0.4-py3-none-any.whl"]) is None


def test_engine_drift_newer_warns(monkeypatch):
    w = compat.engine_drift_warning(["tech_rebalance-2.0.0-py3-none-any.whl"])
    assert w and "2.0.0" in w and "DMG" in w


def test_engine_drift_older_warns(monkeypatch):
    monkeypatch.setattr(compat, "GUI_SUPPORTED_ENGINE_MAJORS", {2})
    w = compat.engine_drift_warning(["tech_rebalance-1.0.4-py3-none-any.whl"])
    assert w and "更新引擎" in w


def test_engine_drift_missing_silent():
    assert compat.engine_drift_warning([]) is None


# ── G. Overview dry-run button (headless) ────────────────────────────────────
def test_overview_dryrun_button():
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QMessageBox
    QApplication.instance() or QApplication([])
    import admin_gui.services.probes as pr
    from admin_gui.services.gh_client import GhClient
    import pytest as _pt
    mp = _pt.MonkeyPatch()
    mp.setattr(GhClient, "list_secret_names", lambda self: set())
    mp.setattr(pr, "probe_gh", lambda *a, **k: (True, "ok"))
    mp.setattr(pr, "gh_login", lambda *a, **k: "alice")
    from admin_gui.views.overview_view import OverviewView
    from admin_gui.services.global_config import GlobalConfig
    import admin_gui.services.workflow_runner as wr
    import admin_gui.services.preflight as pf_mod
    v = OverviewView("alice/tech-rebalance")
    v.config = GlobalConfig.__new__(GlobalConfig)  # minimal
    cap = {}
    try:
        # preflight 通過（測的是 handler 有呼叫 run_workflow，不測 preflight 本身）
        mp.setattr(pf_mod, "preflight", lambda *a, **k: True)
        mp.setattr(wr, "run_workflow", lambda slug, **k: cap.update(slug=slug, kw=k) or True)
        mp.setattr(QMessageBox, "information", lambda *a, **k: None)
        mp.setattr(QMessageBox, "warning", lambda *a, **k: None)
        mp.setattr(v.config, "get",
                   lambda key, default=None: "alice/tech-rebalance" if key == "repob_slug" else default)
        v._do_dryrun()
        assert cap["slug"] == "alice/tech-rebalance" and cap["kw"]["dry_run"] is True
    finally:
        mp.undo()          # 不論斷言成敗都還原，避免污染其他測試
