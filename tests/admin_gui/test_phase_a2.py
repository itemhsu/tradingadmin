"""Phase A-2 service 測試（G-14, G-19, G-20, G-21, G-24, G-26, G-27, G-28）。

純邏輯 + mock，不啟動 GUI、不打真網路、不需真金鑰。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from admin_gui.services.account_factory import build_account, next_id
from admin_gui.services.audit_log import AuditLog
from admin_gui.services.accounts_repo import AccountsRepo
from admin_gui.services import log_reader, probes


# ── G-14 / G-19：自動產生 id / prefix / data_dir ─────────────────────────
def test_G19_id_auto_assigned():
    assert next_id(["1", "2", "3"]) == "4"
    assert next_id([]) == "1"


def test_G14_factory_autofills_hidden_fields():
    a = build_account("我的科技股", "alpaca", "paper", "top10", existing_ids=["1", "2"])
    assert a["id"] == "3"
    assert a["secret_prefix"] == "ACC3"
    assert a["data_dir"] == "data/3"
    assert a["use_new_runner"] is True
    assert a["label"] == "我的科技股"


# ── G-20：帳戶名稱（label）必填 ──────────────────────────────────────────
def test_G20_label_required():
    with pytest.raises(ValueError, match="必填"):
        build_account("", "alpaca", "paper", "top10", existing_ids=[])


# ── G-21：操作日誌記錄 create/edit/delete/enable ─────────────────────────
def test_G21_audit_records_actions(tmp_path):
    acc_path = tmp_path / "accounts.json"
    acc_path.write_text(json.dumps({"accounts": []}), encoding="utf-8")
    audit = AuditLog(tmp_path / "audit.jsonl")
    repo = AccountsRepo(tmp_path, audit=audit)
    repo.add(build_account("帳A", "alpaca", "paper", "top10", existing_ids=[]))
    repo.update("1", {"label": "帳A改名"})
    repo.set_enabled("1", False)
    repo.delete("1")
    events = audit.read()
    actions = [e["action"] for e in events]
    assert "create" in actions and "edit" in actions
    assert "disable" in actions and "delete" in actions
    # 不含金鑰值（detail 只有欄位名）
    assert all("PK" not in (e.get("detail") or "") for e in events)


def test_G21_audit_filter_and_order(tmp_path):
    a = AuditLog(tmp_path / "a.jsonl")
    a.record("create", "#1"); a.record("delete", "#1", result="fail")
    assert a.read(limit=1)[0]["action"] == "delete"        # 倒序
    assert len(a.read(result="fail")) == 1


# ── G-24：Email 測試（無金鑰立即失敗，不打網路）──────────────────────────
def test_G24_email_probe_requires_creds():
    ok, msg = probes.probe_email("", "", "x@y.com")
    assert ok is False and "缺" in msg


# ── G-24b：測試發信「給自己」——recipient 留空時自動 = sender ─────────────
def test_G24b_email_probe_sends_to_self(monkeypatch):
    sent = {}
    class FakeSMTP:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def starttls(self, **k): pass
        def login(self, u, p): sent["login"] = u
        def sendmail(self, frm, to, body): sent["to"] = to
    monkeypatch.setattr(probes.smtplib, "SMTP", FakeSMTP)
    ok, msg = probes.probe_email("me@gmail.com", "apppw", "")   # recipient 空
    assert ok
    assert sent["to"] == ["me@gmail.com"]   # 自己寄給自己


# ── 需求 22：測試發信 = 觸發雲端 workflow（無需密碼）+ 讀結果 ───────────
def test_req22_trigger_test_email(monkeypatch):
    calls = {}
    def fake(cmd, **kw):
        calls["cmd"] = cmd
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
    ok, msg = probes.trigger_test_email(runner=fake)
    assert ok
    assert calls["cmd"][:4] == ["gh", "workflow", "run", "test_email.yml"]


def test_req22_read_result_success():
    import json
    payload = json.dumps([{"status": "completed", "conclusion": "success"}])
    fake = lambda *a, **k: type("R", (), {"returncode": 0, "stdout": payload, "stderr": ""})()
    status, concl = probes.last_test_email_result(runner=fake)
    assert status == "completed" and concl == "success"


def test_req22_read_result_inprogress():
    import json
    payload = json.dumps([{"status": "in_progress", "conclusion": ""}])
    fake = lambda *a, **k: type("R", (), {"returncode": 0, "stdout": payload, "stderr": ""})()
    status, concl = probes.last_test_email_result(runner=fake)
    assert status == "in_progress"


# ── G-30：EMAIL_SENDER 非機密，存 GlobalConfig 可讀回明文 ─────────────────
def test_G30_email_sender_is_plaintext_config(tmp_path):
    from admin_gui.services.global_config import GlobalConfig
    cfg = GlobalConfig(tmp_path / "config.json")
    cfg.set_email_sender("you@gmail.com")
    assert cfg.email_sender() == "you@gmail.com"   # 可讀回實際值（非「已設/未設」）


# ── G-29：SendGrid 已從 GUI 全域 secret 清單移除 ─────────────────────────
def test_G29_no_sendgrid_in_overview_globals():
    import admin_gui.views.overview_view as ov
    assert "SENDGRID_API_KEY" not in ov._GLOBAL_SECRETS
    assert "EMAIL_SENDER" not in ov._GLOBAL_SECRETS   # 非機密，不在遮罩清單
    assert "DASHBOARD_PUSH_TOKEN" not in ov._GLOBAL_SECRETS  # 幽靈設定已移除
    assert ov._GLOBAL_SECRETS == ["EMAIL_PASSWORD"]   # 一般使用者只需這一個


# ── 純 API 模式：GhContentsStore 透過 gh api 讀寫，不需 clone ─────────────
def test_gh_store_read_decodes_base64():
    import base64
    from admin_gui.services.repo_store import GhContentsStore
    content = base64.b64encode("hello".encode()).decode()
    payload = json.dumps({"content": content, "sha": "abc"})
    fake = lambda *a, **k: type("R", (), {"returncode": 0, "stdout": payload, "stderr": ""})()
    s = GhContentsStore("o/r", runner=fake)
    assert s.read_text("x.txt") == "hello"


def test_gh_store_missing_returns_none():
    from admin_gui.services.repo_store import GhContentsStore
    fake = lambda *a, **k: type("R", (), {"returncode": 1, "stdout": "", "stderr": "HTTP 404 Not Found"})()
    s = GhContentsStore("o/r", runner=fake)
    assert s.read_text_or_none("nope.txt") is None
    assert s.exists("nope.txt") is False


def test_gh_store_write_sends_base64_put():
    import base64
    from admin_gui.services.repo_store import GhContentsStore
    calls = []
    def fake(cmd, **kw):
        calls.append((cmd, kw.get("input")))
        # 第一次 GET 取 sha（回 404＝新檔），第二次 PUT
        if "-X" in cmd and "PUT" in cmd:
            return type("R", (), {"returncode": 0, "stdout": "{}", "stderr": ""})()
        return type("R", (), {"returncode": 1, "stdout": "", "stderr": "404 Not Found"})()
    s = GhContentsStore("o/r", runner=fake)
    s.write_text("accounts.json", '{"a":1}', "msg")
    put = [c for c in calls if "-X" in c[0]][0]
    body = json.loads(put[1])
    assert base64.b64decode(body["content"]).decode() == '{"a":1}'
    assert body["message"] == "msg"


# ── G-32：首啟旗標 — setup_done 後不再視為首次 ───────────────────────────
def test_G32_first_run_flag(tmp_path):
    from admin_gui.services.global_config import GlobalConfig
    from admin_gui.views import wizard
    cfg = GlobalConfig(tmp_path / "config.json")
    assert wizard.is_first_run(cfg) is True
    cfg.set("setup_done", True)
    assert wizard.is_first_run(cfg) is False


# ── G-27：全域 log（cron 執行歷史 mock）──────────────────────────────────
def test_G27_cron_runs_parses(monkeypatch):
    payload = json.dumps([{"workflowName": "Daily", "status": "completed",
                           "conclusion": "success", "createdAt": "2026-06-02"}])
    fake = lambda *a, **k: type("R", (), {"returncode": 0, "stdout": payload, "stderr": ""})()
    runs = log_reader.cron_runs(runner=fake)
    assert runs and runs[0]["conclusion"] == "success"


def test_G27b_cron_runs_failure_returns_empty():
    fake = lambda *a, **k: type("R", (), {"returncode": 1, "stdout": "", "stderr": "x"})()
    assert log_reader.cron_runs(runner=fake) == []


# ── G-28：帳戶 log（缺檔不丟例外）────────────────────────────────────────
def test_G28_account_log_missing_returns_empty(tmp_path):
    acc = {"id": "9", "data_dir": "data/9"}
    assert log_reader.account_trade_events(acc, root=tmp_path) == []
    assert log_reader.account_nav_history(acc, root=tmp_path) == []


def test_G28b_account_log_reads(tmp_path):
    d = tmp_path / "data" / "9"; d.mkdir(parents=True)
    (d / "trade_events.jsonl").write_text(
        '{"type":"ORDER","symbol":"AAPL"}\n{"type":"FILL","symbol":"AAPL"}\n')
    (d / "portfolio_state_history.json").write_text(
        json.dumps([{"date": "2026-06-01", "nav": 100}, {"date": "2026-06-02", "nav": 101}]))
    acc = {"id": "9", "data_dir": "data/9"}
    ev = log_reader.account_trade_events(acc, root=tmp_path)
    assert len(ev) == 2 and ev[0]["type"] == "FILL"   # 倒序
    nav = log_reader.account_nav_history(acc, root=tmp_path)
    assert nav[0]["date"] == "2026-06-02"
