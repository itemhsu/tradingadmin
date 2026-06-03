"""精靈「⑧ 從上游同步引擎」按鈕測試（fork 相容性 §5：App 一鍵同步）。

驗證 handler 經 GitHub merge-upstream API 同步，且各回應給對的提示。
外部 gh / 對話框全 mock。
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


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _wizard(monkeypatch, tmp_path):
    import admin_gui.views.wizard as wz
    monkeypatch.setattr(wz, "probe_gh", lambda *a, **k: (False, "gh 未登入"))
    from admin_gui.services.global_config import GlobalConfig
    cfg = GlobalConfig(tmp_path / "config.json")
    cfg.set("repo_slug", "alice/tech-rebalance")
    return wz, wz.SetupWizard(cfg)


def _yes(monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)


def test_sync_button_exists(qapp, monkeypatch, tmp_path):
    _, w = _wizard(monkeypatch, tmp_path)
    assert callable(getattr(w, "_do_sync_upstream"))
    assert hasattr(w, "sync_row")


def test_sync_calls_merge_upstream_api(qapp, monkeypatch, tmp_path):
    wz, w = _wizard(monkeypatch, tmp_path)
    _yes(monkeypatch)
    calls = []
    monkeypatch.setattr(wz, "_gh", lambda args, **k: calls.append(args) or (0, "{}", ""))
    w._do_sync_upstream()
    assert calls, "未呼叫 gh"
    a = calls[-1]
    assert "merge-upstream" in " ".join(a)
    assert "repos/alice/tech-rebalance/merge-upstream" in " ".join(a)
    assert "branch=main" in " ".join(a)


def test_sync_aborts_when_user_declines(qapp, monkeypatch, tmp_path):
    wz, w = _wizard(monkeypatch, tmp_path)
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.No)
    calls = []
    monkeypatch.setattr(wz, "_gh", lambda args, **k: calls.append(args) or (0, "", ""))
    w._do_sync_upstream()
    assert not calls, "使用者拒絕時不應呼叫 API"


def test_sync_conflict_shows_manual_hint(qapp, monkeypatch, tmp_path):
    wz, w = _wizard(monkeypatch, tmp_path)
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    seen = {}
    monkeypatch.setattr(QMessageBox, "warning",
                        lambda *a, **k: seen.update(title=a[1], body=a[2]))
    monkeypatch.setattr(wz, "_gh", lambda args, **k: (1, "", "409 conflict"))
    w._do_sync_upstream()
    assert "手動" in seen.get("title", "")     # 409 → 提示手動處理
