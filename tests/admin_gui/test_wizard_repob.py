"""精靈 Ⓐ建立 Repo B / Ⓑ更新引擎（兩 repo GUI G3）。外部 gh/服務全 mock。"""
import base64, os, sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]
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
    return wz, wz.SetupWizard(cfg), cfg


def _yes(monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)


def test_new_steps_exist_alongside_fork(qapp, monkeypatch, tmp_path):
    _, w, _ = _wizard(monkeypatch, tmp_path)
    # 新步驟
    assert hasattr(w, "repob_row") and hasattr(w, "engine_row")
    assert callable(w._do_build_repob) and callable(w._do_update_engine)
    # 舊 fork 步驟仍在（向後相容，G5 才做 mode 偵測切換）
    assert hasattr(w, "fork_row") and hasattr(w, "pages_row") and hasattr(w, "actions_row")


def test_build_repob_calls_provision(qapp, monkeypatch, tmp_path):
    wz, w, cfg = _wizard(monkeypatch, tmp_path)
    _yes(monkeypatch)
    from admin_gui.services import engine_release as er
    from admin_gui.services import repo_b_provisioner as pv
    monkeypatch.setattr(er, "list_versions", lambda repo: ["v1.0.4", "v1.0.3"])

    def fake_dl(version, dest, repo):
        (Path(dest) / "tech_rebalance-1.0.4-py3-none-any.whl").write_bytes(b"WHEEL")
        return "tech_rebalance-1.0.4-py3-none-any.whl"
    monkeypatch.setattr(er, "download_wheel", fake_dl)
    captured = {}
    monkeypatch.setattr(pv, "provision",
                        lambda slug, files, **k: captured.update(slug=slug, files=files) or {"ok": True})
    w._do_build_repob()
    assert captured["slug"] == "alice/tech-rebalance-data"
    assert ".github/workflows/daily.yml" in captured["files"]
    assert "vendor/tech_rebalance-1.0.4-py3-none-any.whl" in captured["files"]
    assert cfg.get("repob_slug") == "alice/tech-rebalance-data"   # 記住 Repo B


def test_build_repob_aborts_when_declined(qapp, monkeypatch, tmp_path):
    wz, w, _ = _wizard(monkeypatch, tmp_path)
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.No)
    from admin_gui.services import repo_b_provisioner as pv
    called = {"n": 0}
    monkeypatch.setattr(pv, "provision", lambda *a, **k: called.update(n=called["n"] + 1))
    w._do_build_repob()
    assert called["n"] == 0       # 使用者拒絕 → 不建


def test_build_repob_no_versions_warns(qapp, monkeypatch, tmp_path):
    wz, w, _ = _wizard(monkeypatch, tmp_path)
    _yes(monkeypatch)
    from admin_gui.services import engine_release as er, repo_b_provisioner as pv
    monkeypatch.setattr(er, "list_versions", lambda repo: [])
    called = {"n": 0}
    monkeypatch.setattr(pv, "provision", lambda *a, **k: called.update(n=called["n"] + 1))
    w._do_build_repob()
    assert called["n"] == 0       # 列不到版本 → 不繼續


def test_update_engine_pushes_new_wheel(qapp, monkeypatch, tmp_path):
    wz, w, cfg = _wizard(monkeypatch, tmp_path)
    cfg.set("repob_slug", "alice/tech-rebalance-data")
    _yes(monkeypatch)
    from admin_gui.services import engine_release as er
    monkeypatch.setattr(er, "list_versions", lambda repo: ["v1.0.5"])

    def fake_dl(version, dest, repo):
        (Path(dest) / "tech_rebalance-1.0.5-py3-none-any.whl").write_bytes(b"W")
        return "tech_rebalance-1.0.5-py3-none-any.whl"
    monkeypatch.setattr(er, "download_wheel", fake_dl)
    daily_b64 = base64.b64encode(
        b"run: pip install vendor/tech_rebalance-1.0.4-py3-none-any.whl").decode()
    calls = []
    def fake_gh(args, inp=None, **k):
        calls.append((args, inp))
        if "--jq" in args and ".content" in args:
            return (0, daily_b64, "")
        if "--jq" in args and ".sha" in args:
            return (0, "deadbeef", "")
        return (0, "", "")
    monkeypatch.setattr(wz, "_gh", fake_gh)
    w._do_update_engine()
    puts = [a for a, _ in calls if "PUT" in a]
    assert any("vendor/tech_rebalance-1.0.5" in " ".join(a) for a in puts)
    assert any("daily.yml" in " ".join(a) for a in puts)
