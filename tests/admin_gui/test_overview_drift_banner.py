"""OverviewView 相容性警告橫幅的端到端接線測試（fork 相容性 §6.1 ⑨）。

證明：_refresh_drift_banner() 依 fork schemas/ 版本，正確顯示/隱藏頂部紅色橫幅。
外部 gh/網路全 mock。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

pytest.importorskip("PySide6", reason="PySide6 未安裝")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

SLUG = "itemhsu/tech-rebalance"


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def no_net(monkeypatch):
    from admin_gui.services.gh_client import GhClient
    monkeypatch.setattr(GhClient, "list_secret_names", lambda self: {"EMAIL_SENDER"})
    monkeypatch.setattr(GhClient, "auth_ok", lambda self: True)
    import admin_gui.services.probes as pr
    monkeypatch.setattr(pr, "probe_gh", lambda *a, **k: (True, "gh 已登入"))
    monkeypatch.setattr(pr, "gh_login", lambda *a, **k: "itemhsu")


class _Store:
    def __init__(self, names):
        self._names = names

    def list_dir(self, path):
        return self._names if path == "schemas" else []


def _patch_store(monkeypatch, names):
    import admin_gui.services.repo_store as rs
    monkeypatch.setattr(rs, "make_store", lambda *a, **k: _Store(names))


def test_banner_hidden_when_compatible(qapp, no_net, monkeypatch):
    _patch_store(monkeypatch, ["data-schema-v1.json", "accounts-schema-v1.json"])
    from admin_gui.views.overview_view import OverviewView
    v = OverviewView(SLUG)
    v._refresh_drift_banner()
    assert v.drift_banner.isHidden() is True


def test_banner_shown_when_engine_newer(qapp, no_net, monkeypatch):
    _patch_store(monkeypatch, ["data-schema-v1.json", "data-schema-v2.json"])
    from admin_gui.views.overview_view import OverviewView
    v = OverviewView(SLUG)
    v._refresh_drift_banner()
    assert v.drift_banner.isHidden() is False
    assert "v2" in v.drift_banner.text()


def test_banner_hidden_when_store_fails(qapp, no_net, monkeypatch):
    import admin_gui.services.repo_store as rs

    def _boom(*a, **k):
        raise RuntimeError("network down")
    monkeypatch.setattr(rs, "make_store", _boom)
    from admin_gui.views.overview_view import OverviewView
    v = OverviewView(SLUG)
    v._refresh_drift_banner()
    assert v.drift_banner.isHidden() is True     # 讀不到→不打擾
