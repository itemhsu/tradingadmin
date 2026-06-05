"""杜絕安靜失敗：action_log + 發送/清除 log + 密度（L-01~L-20）。"""
import json

import pytest

from admin_gui.services import action_log as al


@pytest.fixture
def LOG(tmp_path):
    return al.ActionLog(path=tmp_path / "action_log.jsonl")


# ── L-01：start + end ────────────────────────────────────────────────────────
def test_l01_action_logs_start_and_end(LOG):
    with LOG.action("測試動作", ctx="u/r") as a:
        a.step("做事", "ok", "細節")
    kinds = [r["kind"] for r in LOG.tail()]
    assert "start" in kinds and "end" in kinds
    aids = {r["aid"] for r in LOG.tail() if r["aid"] != "-"}
    assert len(aids) == 1                              # L-10：同 aid 分群


# ── L-02：例外記 traceback 且重新拋出（不私吞）──────────────────────────────
def test_l02_exception_logged_and_reraised(LOG):
    with pytest.raises(ValueError):
        with LOG.action("會爆的動作") as a:
            a.step("before", "ok")
            raise ValueError("boom")
    recs = LOG.tail()
    fail = [r for r in recs if r["kind"] == "fail"]
    assert fail and "boom" in fail[0]["error"]
    assert "trace" in fail[0] and fail[0]["trace"]    # 有 traceback


# ── L-15：每個 action 第一筆是 env 快照（app/os/gh/repo）──────────────────────
def test_l15_first_step_is_env_snapshot(LOG):
    with LOG.action("動作", ctx="alice/tech-rebalance") as a:
        pass
    steps = [r for r in LOG.tail() if r["kind"] == "step"]
    assert steps[0]["name"] == "env"
    d = steps[0]["detail"]
    assert "app=" in d and "os=" in d and "repo=" in d


# ── note 併入進行中的 action（gh 失敗附到當前 action）────────────────────────
def test_note_attaches_to_current_action(LOG):
    with LOG.action("外層") as a:
        LOG.note("gh", "warn", "rc=1 boom")
    steps = [r for r in LOG.tail() if r["kind"] == "step"]
    assert any(s["name"] == "gh" and s["status"] == "warn" for s in steps)


def test_note_standalone_when_no_action(LOG):
    LOG.note("孤立 gh", "fail", "rc=1")
    notes = [r for r in LOG.tail() if r["kind"] == "note"]
    assert notes and notes[0]["status"] == "fail"


# ── L-09：problems() 反映真實，結果不假成功 ──────────────────────────────────
def test_l09_problems_detected(LOG):
    with LOG.action("有問題") as a:
        a.step("ok 步", "ok")
        a.step("壞步", "fail", "原因")
        assert a.has_problem()
        assert [p.name for p in a.problems()] == ["壞步"]


# ── L-12：mask_secrets 遮罩金鑰 ──────────────────────────────────────────────
def test_l12_mask_secrets():
    assert "***" in al.mask_secrets("token=ghp_abcdefghijklmnopqrstuvwxyz0123")
    assert "ABCD1234567890ABCD1234" not in al.mask_secrets("key ABCD1234567890ABCD1234")
    masked = al.mask_secrets("EMAIL_PASSWORD=supersecretvalue123")
    assert "supersecretvalue123" not in masked


# ── L-17/L-18/L-19：清除 log ─────────────────────────────────────────────────
def test_l17_clear_empties_log(LOG):
    with LOG.action("舊動作") as a:
        a.step("x", "ok")
    assert LOG.tail()                                  # 有東西
    n = LOG.clear()
    assert n > 0
    assert LOG.tail() == []                            # 清空


def test_l18_clear_itself_is_logged(LOG):
    with LOG.action("動作1") as a:
        a.step("x", "ok")
    LOG.clear()
    with LOG.action("清除 log") as a:                  # 模擬 handler 的記錄
        a.step("truncate", "ok", "清除 N 行")
    actions = [r["action"] for r in LOG.tail() if r["kind"] == "start"]
    assert actions == ["清除 log"]                     # 清空後只剩這筆


def test_l19_clear_only_touches_own_file(LOG, tmp_path):
    other = tmp_path / "important.txt"
    other.write_text("keep me")
    LOG.clear()
    assert other.read_text() == "keep me"              # 不誤刪其他檔


# ── L-20：超限自動 rotate ────────────────────────────────────────────────────
def test_l20_rotate_keeps_tail(LOG, monkeypatch):
    monkeypatch.setattr(al, "_MAX_LINES", 20)
    monkeypatch.setattr(al, "_KEEP_LINES", 5)
    for i in range(30):
        LOG.note(f"n{i}", "ok")
    LOG._rotate_if_needed()
    lines = LOG.tail()
    assert len(lines) <= 6                             # 保留尾段（不無限長）


# ── L-04：sync 把 skip-no-template 記成可見的 fail step ──────────────────────
def test_l04_sync_logs_skip_no_template(LOG):
    from admin_gui.services import repo_sync as rs
    mani = {"repo_b": [{"path": ".github/workflows/test_email.yml",
                        "policy": "render", "src": "templates/test_email.yml"}],
            "dashboard": []}
    gh = lambda args, inp=None, **k: (1, "", "404")     # repo 都不存在、抓檔失敗
    with LOG.action("建立") as a:
        rs.sync("repo_b", "u/r", "v1", gh=gh, manifest=mani, logger=a)
        probs = a.problems()
    # test_email.yml 抓不到範本 → 必為可見問題（非靜默）
    assert any("test_email.yml" in p.name for p in probs)


# ── L-11：發送 log 收件人寫死 itemhsu ────────────────────────────────────────
def test_l11_send_log_recipient_hardcoded(monkeypatch):
    from admin_gui.services import probes
    captured = {}
    class FakeSMTP:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def starttls(self, **k): pass
        def login(self, *a): pass
        def sendmail(self, sender, to, msg): captured["to"] = to
    monkeypatch.setattr(probes.smtplib, "SMTP", FakeSMTP)
    ok, msg = probes.send_log_to_dev("me@gmail.com", "pw", "body")
    assert ok and captured["to"] == ["itemhsu@gmail.com"]   # 寫死，不可覆寫


def test_l24_save_sender_sets_github_secret():
    """L-24：儲存寄件人必須把 EMAIL_SENDER 推成 GitHub secret（修本案根因）。"""
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from admin_gui.views.overview_view import OverviewView
    v = OverviewView("alice/tech-rebalance")
    captured = {}
    v.gh.set_secret = lambda name, val: captured.update({name: val})
    v.sender_edit.setText("alice@gmail.com")
    v.refresh = lambda: None                          # 擋副作用
    v._save_sender()
    assert captured.get("EMAIL_SENDER") == "alice@gmail.com"   # 有推成 secret
