"""mode 偵測 + 精靈依模式切步驟（兩 repo GUI G5，向後相容核心）。"""
import os, sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from admin_gui.services import mode_detect as md


class _Store:
    def __init__(self, vendor=None, files=None):
        self._vendor = vendor or []
        self._files = set(files or [])
    def list_dir(self, p):
        return self._vendor if p == "vendor" else []
    def exists(self, p):
        return p in self._files


def test_fork_detected_by_runner():
    assert md.detect_mode(_Store(files={"runner.py"})) == md.FORK


def test_repob_detected_by_vendor_wheel():
    assert md.detect_mode(_Store(vendor=["tech_rebalance-1.0.4-py3-none-any.whl"])) == md.REPO_B


def test_unknown_when_neither():
    assert md.detect_mode(_Store()) == md.UNKNOWN


def test_store_errors_degrade_to_unknown():
    class Boom:
        def list_dir(self, p): raise RuntimeError("net")
        def exists(self, p): raise RuntimeError("net")
    assert md.detect_mode(Boom()) == md.UNKNOWN


def test_repob_takes_precedence_over_runner():
    # 同時有（不該發生）→ 以 repo_b 優先
    s = _Store(vendor=["x.whl"], files={"runner.py"})
    assert md.detect_mode(s) == md.REPO_B


# ── 精靈依模式切步驟 ─────────────────────────────────────────────────────────
def test_wizard_apply_mode_hides_rows(monkeypatch, tmp_path):
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    import admin_gui.views.wizard as wz
    monkeypatch.setattr(wz, "probe_gh", lambda *a, **k: (False, "x"))
    from admin_gui.services.global_config import GlobalConfig
    cfg = GlobalConfig(tmp_path / "c.json"); cfg.set("repo_slug", "alice/tech-rebalance")
    w = wz.SetupWizard(cfg)

    w._apply_mode(md.FORK)
    assert w.fork_row["widget"].isHidden() is False        # fork 步驟顯示
    assert w.repob_row["widget"].isHidden() is True         # repo_b 步驟隱藏

    w._apply_mode(md.REPO_B)
    assert w.fork_row["widget"].isHidden() is True
    assert w.repob_row["widget"].isHidden() is False

    w._apply_mode(md.UNKNOWN)
    assert w.fork_row["widget"].isHidden() is False         # 未知→全顯
    assert w.repob_row["widget"].isHidden() is False
