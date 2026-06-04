"""mode 偵測 + 精靈依模式切步驟（兩 repo GUI G5，向後相容核心）。"""
import os, sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from admin_gui.services import mode_detect as md


class _Store:
    def __init__(self, vendor=None, files=None, daily=None):
        self._vendor = vendor or []
        self._files = set(files or [])
        self._daily = daily
    def list_dir(self, p):
        return self._vendor if p == "vendor" else []
    def exists(self, p):
        return p in self._files
    def read_text_or_none(self, p):
        if p == ".github/workflows/daily.yml":
            return self._daily
        return None


def test_fork_detected_by_runner():
    assert md.detect_mode(_Store(files={"runner.py"})) == md.FORK


def test_repob_detected_by_vendor_wheel():
    assert md.detect_mode(_Store(vendor=["tech_rebalance-1.0.4-py3-none-any.whl"])) == md.REPO_B


def test_repob_detected_by_git_pin_in_daily():
    daily = ('run: pip install "tech-rebalance @ '
             'git+https://github.com/itemhsu/tech-rebalance-pub@v1.0.6"')
    assert md.detect_mode(_Store(daily=daily)) == md.REPO_B


def test_repob_detected_by_accounts_without_runner():
    # 薄殼：有 accounts.json、無 runner.py（引擎以 pip 安裝在外）
    assert md.detect_mode(_Store(files={"accounts.json"})) == md.REPO_B


def test_fork_wins_when_runner_and_accounts_both_present():
    # 過渡期 private repo：引擎碼還在（runner.py）+ accounts.json → 仍視為 fork
    assert md.detect_mode(_Store(files={"runner.py", "accounts.json"})) == md.FORK


def test_unknown_when_neither():
    assert md.detect_mode(_Store()) == md.UNKNOWN


def test_store_errors_degrade_to_unknown():
    class Boom:
        def list_dir(self, p): raise RuntimeError("net")
        def exists(self, p): raise RuntimeError("net")
        def read_text_or_none(self, p): raise RuntimeError("net")
    assert md.detect_mode(Boom()) == md.UNKNOWN


def test_store_missing_read_text_method_degrades():
    # 舊 store 無 read_text_or_none → 不應炸，退回看 vendor/runner
    class Old:
        def list_dir(self, p): return []
        def exists(self, p): return p == "runner.py"
    assert md.detect_mode(Old()) == md.FORK


def test_repob_takes_precedence_over_runner():
    # 同時有 wheel + runner（不該發生）→ 以 repo_b 優先
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
