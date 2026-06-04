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


def test_only_two_repo_steps_remain(qapp, monkeypatch, tmp_path):
    _, w, _ = _wizard(monkeypatch, tmp_path)
    # 兩-repo 步驟
    assert hasattr(w, "repob_row") and hasattr(w, "engine_row")
    assert callable(w._do_build_repob) and callable(w._do_update_engine)
    # 舊 fork 步驟已完全移除（不再支援 fork）
    for gone in ("fork_row", "pages_row", "actions_row", "sync_row"):
        assert not hasattr(w, gone)
    for fn in ("_do_fork", "_do_pages", "_do_actions", "_do_sync_upstream"):
        assert not hasattr(w, fn)


def test_build_repob_calls_provision(qapp, monkeypatch, tmp_path):
    wz, w, cfg = _wizard(monkeypatch, tmp_path)
    _yes(monkeypatch)
    from admin_gui.services import engine_release as er
    from admin_gui.services import repo_b_provisioner as pv
    monkeypatch.setattr(er, "list_versions", lambda repo: ["v1.0.6", "v1.0.5"])
    captured = {}
    monkeypatch.setattr(pv, "provision",
                        lambda slug, files, **k: captured.update(slug=slug, files=files) or {"ok": True})
    w._do_build_repob()
    assert captured["slug"] == "alice/tech-rebalance"
    assert ".github/workflows/daily.yml" in captured["files"]
    # git+ 安裝公開引擎：不再 vendor wheel
    assert not any(p.startswith("vendor/") for p in captured["files"])
    daily = captured["files"][".github/workflows/daily.yml"].decode("utf-8")
    assert "git+https://github.com/itemhsu/tech-rebalance-pub@v1.0.6" in daily
    assert cfg.get("repob_slug") == "alice/tech-rebalance"   # 記住 Repo B


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


def _make_update_fake_gh(wf_name: str, wf_content: str):
    """_do_update_engine 用：先列 workflows，再讀內容+sha，最後 PUT。"""
    import json as _json
    daily_b64 = base64.b64encode(wf_content.encode()).decode()
    calls = []
    def fake_gh(args, inp=None, **k):
        calls.append((args, inp))
        joined = " ".join(args)
        if "[.[].name]" in joined:                            # 列 workflows
            return (0, _json.dumps([wf_name]), "")
        if wf_name in joined and ".content" in joined:        # 讀內容
            return (0, daily_b64, "")
        if wf_name in joined and ".sha" in joined:            # 讀 sha
            return (0, "deadbeef", "")
        if "repos/" in joined and "--jq" in joined and ".full_name" in joined:  # refresh
            return (0, "alice/tech-rebalance", "")
        return (0, "", "")
    return fake_gh, calls


def test_update_engine_bumps_git_pin(qapp, monkeypatch, tmp_path):
    wz, w, cfg = _wizard(monkeypatch, tmp_path)
    cfg.set("repob_slug", "alice/tech-rebalance")
    _yes(monkeypatch)
    from admin_gui.services import engine_release as er
    monkeypatch.setattr(er, "list_versions", lambda repo: ["v1.0.6"])
    wf_content = ('run: pip install "tech-rebalance @ '
                  'git+https://github.com/itemhsu/tech-rebalance-pub@v1.0.5"')
    fake_gh, calls = _make_update_fake_gh("daily.yml", wf_content)
    monkeypatch.setattr(wz, "_gh", fake_gh)
    w._do_update_engine()
    puts = [(a, inp) for a, inp in calls if "PUT" in a]
    assert len(puts) == 1                                   # 只動一個檔，不推 wheel
    assert "daily.yml" in " ".join(puts[0][0])
    pushed = base64.b64decode(__import__("json").loads(puts[0][1])["content"]).decode()
    assert "tech-rebalance-pub@v1.0.6" in pushed
    assert "v1.0.5" not in pushed


def test_update_engine_migrates_requirements_txt(qapp, monkeypatch, tmp_path):
    """舊式 pip install -r requirements.txt → 自動遷移成 git+ 安裝。"""
    wz, w, cfg = _wizard(monkeypatch, tmp_path)
    cfg.set("repob_slug", "alice/tech-rebalance")
    _yes(monkeypatch)
    from admin_gui.services import engine_release as er
    monkeypatch.setattr(er, "list_versions", lambda repo: ["v1.0.6"])
    wf_content = "        run: pip install -r requirements.txt\n"
    fake_gh, calls = _make_update_fake_gh("daily_all_accounts.yml", wf_content)
    monkeypatch.setattr(wz, "_gh", fake_gh)
    w._do_update_engine()
    puts = [(a, inp) for a, inp in calls if "PUT" in a]
    assert len(puts) == 1
    assert "daily_all_accounts.yml" in " ".join(puts[0][0])
    pushed = base64.b64decode(__import__("json").loads(puts[0][1])["content"]).decode()
    assert "tech-rebalance-pub@v1.0.6" in pushed
    assert "requirements.txt" not in pushed


def _b64yml(text: str) -> str:
    return base64.b64encode(text.encode()).decode()


def _gh_for(daily_text: str, wf_name: str = "daily.yml",
            dash_exists: bool = True):
    """造一個 fake _gh：Repo B（alice/tech-rebalance）存在；
    workflow 目錄回 [wf_name]，該 workflow 內容回 daily_text。
    dash_exists 控制 dashboard repo 是否存在（預設存在）。"""
    import json as _json
    def fake_gh(args, inp=None, **k):
        joined = " ".join(args)
        if joined.endswith("--jq .full_name"):
            if "tech-rebalance-dashboard" in joined:
                return (0, "alice/tech-rebalance-dashboard", "") if dash_exists else (1, "", "")
            return (0, "alice/tech-rebalance", "")
        # 列 workflow 目錄
        if ".github/workflows" in joined and "[.[].name]" in joined:
            return (0, _json.dumps([wf_name]), "")
        # 讀 workflow 內容
        if wf_name in joined and ".content" in joined:
            return (0, _b64yml(daily_text), "")
        return (0, "", "")
    return fake_gh


def test_refresh_engine_row_status_never_blank_when_not_uptodate(qapp, monkeypatch, tmp_path):
    """回歸：未完成的『更新引擎』列必須顯示狀態文字（曾被 _set_done 清空成空白）。"""
    wz, w, _ = _wizard(monkeypatch, tmp_path)
    w.user_edit.setText("alice")
    from admin_gui.services import engine_release as er
    monkeypatch.setattr(er, "list_versions", lambda repo: ["v1.0.6"])
    daily = ('run: pip install "tech-rebalance @ '
             'git+https://github.com/itemhsu/tech-rebalance-pub@v1.0.4"')
    monkeypatch.setattr(wz, "_gh", _gh_for(daily))

    w._refresh_status()
    # 兩個 repo 都存在 → 顯示 "已建立 · tech-rebalance + dashboard"
    assert "已建立" in w.repob_row["status"].text()
    assert "dashboard" in w.repob_row["status"].text()
    note = w.engine_row["status"].text()
    assert note and "v1.0.4" in note and "v1.0.6" in note      # 可更新 v1.0.4→v1.0.6


def test_refresh_engine_row_note_when_no_git_pin(qapp, monkeypatch, tmp_path):
    """舊式 vendored wheel 的 daily.yml（無 git+ 釘版）→ 給明確指引，不空白。"""
    wz, w, _ = _wizard(monkeypatch, tmp_path)
    w.user_edit.setText("alice")
    from admin_gui.services import engine_release as er
    monkeypatch.setattr(er, "list_versions", lambda repo: ["v1.0.6"])
    legacy = "run: pip install vendor/tech_rebalance-1.0.3-py3-none-any.whl"
    monkeypatch.setattr(wz, "_gh", _gh_for(legacy))

    w._refresh_status()
    note = w.engine_row["status"].text()
    assert note and "git+" in note                              # 明確提示切換


def test_repob_slug_ignores_discarded_data_cache(qapp, monkeypatch, tmp_path):
    """config 殘留已廢棄的 *-data 快取 → 一律忽略，回到 {帳號}/tech-rebalance。"""
    wz, w, cfg = _wizard(monkeypatch, tmp_path)
    w.user_edit.setText("itemhsu")
    cfg.set("repob_slug", "itemhsu/tech-rebalance-data")   # 舊版殘留
    assert w._repob_slug() == "itemhsu/tech-rebalance"     # 不依賴 -data


def test_refresh_finds_git_pin_in_daily_all_accounts_yml(qapp, monkeypatch, tmp_path):
    """回歸：workflow 叫 daily_all_accounts.yml（非 daily.yml）也能正確偵測 git+ 釘版。"""
    wz, w, _ = _wizard(monkeypatch, tmp_path)
    w.user_edit.setText("itemhsu")
    from admin_gui.services import engine_release as er
    monkeypatch.setattr(er, "list_versions", lambda repo: ["v1.0.6"])
    daily = ('run: pip install "tech-rebalance @ '
             'git+https://github.com/itemhsu/tech-rebalance-pub@v1.0.6"')
    monkeypatch.setattr(wz, "_gh", _gh_for(daily, wf_name="daily_all_accounts.yml"))

    w._refresh_status()
    note = w.engine_row["status"].text()
    assert "v1.0.6" in note and "已是最新" in note   # 找到 pin，且已是最新
