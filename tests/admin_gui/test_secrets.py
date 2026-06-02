"""Phase B 測試：Secrets service（G-03b 已在 Phase A；此處 G-05/06 + audit）。

含安全測試：設 Secret 的值只走 stdin、不進命令列、程式無「值→檔/log」路徑。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from admin_gui.services.gh_client import GhClient, GhError
from admin_gui.services import secrets_audit as audit


# ── gh_client（mock runner，不打真 gh）────────────────────────────────────
class FakeRun:
    def __init__(self, stdout="", returncode=0, stderr=""):
        self.calls = []
        self._stdout, self._rc, self._stderr = stdout, returncode, stderr

    def __call__(self, cmd, **kw):
        self.calls.append({"cmd": cmd, "kw": kw})
        class R:  # noqa: N801
            pass
        r = R(); r.returncode = self._rc; r.stdout = self._stdout; r.stderr = self._stderr
        return r


def test_list_secret_names_parses_json():
    fake = FakeRun(stdout='[{"name":"ACC3_ALPACA_KEY"},{"name":"EMAIL_PASSWORD"}]')
    gh = GhClient("o/r", runner=fake)
    assert gh.list_secret_names() == {"ACC3_ALPACA_KEY", "EMAIL_PASSWORD"}


# ── G-05：設 Secret 的值走 stdin，不進命令列參數 ─────────────────────────
def test_G05_set_secret_value_via_stdin_not_argv():
    fake = FakeRun()
    gh = GhClient("o/r", runner=fake)
    gh.set_secret("ACC9_ALPACA_KEY", "SUPER_SECRET_VALUE")
    call = fake.calls[-1]
    # 值必須在 stdin（input=），絕不在 cmd list
    assert call["kw"].get("input") == "SUPER_SECRET_VALUE"
    assert "SUPER_SECRET_VALUE" not in call["cmd"]
    assert "--body" in call["cmd"] and "-" in call["cmd"]   # body 從 stdin


def test_set_secret_raises_on_failure():
    fake = FakeRun(returncode=1, stderr="boom")
    gh = GhClient("o/r", runner=fake)
    with pytest.raises(GhError):
        gh.set_secret("X", "v")


# ── G-06：靜態掃描 — 設 secret 的程式無「secret 值寫檔/log」 ──────────────
def test_G06_no_secret_written_to_file_or_log():
    # gh_client 是唯一寫 secret 的路徑：值只走 stdin，不寫檔/不 log
    src = (ROOT / "admin_gui/services/gh_client.py").read_text(encoding="utf-8")
    assert ".write_text(" not in src, "gh_client 不該寫檔"
    assert "open(" not in src, "gh_client 不該開檔寫入"
    # set_secret 前不得 log value
    assert "value" not in src.split("def set_secret")[0] or "logger" not in src


# ── audit 邏輯 ────────────────────────────────────────────────────────────
def test_account_required_secrets_alpaca():
    secs = audit.account_required_secrets(
        {"id": "1", "broker": "alpaca", "secret_prefix": "ACC1"})
    assert secs == ["ACC1_ALPACA_KEY", "ACC1_ALPACA_SECRET"]


def test_account_required_secrets_tradier():
    secs = audit.account_required_secrets(
        {"id": "6", "broker": "tradier", "secret_prefix": "ACC6"})
    assert secs == ["ACC6_TRADIER_TOKEN", "ACC6_TRADIER_ACCOUNT"]


def test_audit_marks_missing_and_global():
    accounts = [{"id": "1", "broker": "alpaca", "secret_prefix": "ACC1"}]
    existing = {"ACC1_ALPACA_KEY", "EMAIL_SENDER", "EMAIL_PASSWORD"}
    rows = audit.audit(accounts, existing)
    by_name = {r.name: r for r in rows}
    assert by_name["ACC1_ALPACA_KEY"].exists is True
    assert by_name["ACC1_ALPACA_SECRET"].exists is False   # 缺
    assert by_name["ACC1_ALPACA_SECRET"].status == "missing_required"
    # SendGrid 已移除，不再出現在稽核清單
    assert "SENDGRID_API_KEY" not in by_name
    assert by_name["EMAIL_PASSWORD"].exists is True


def test_accounts_missing_secrets():
    accounts = [
        {"id": "1", "broker": "alpaca", "secret_prefix": "ACC1"},
        {"id": "2", "broker": "alpaca", "secret_prefix": "ACC2"},
    ]
    existing = {"ACC1_ALPACA_KEY", "ACC1_ALPACA_SECRET"}   # ACC2 全缺
    bad = audit.accounts_missing_secrets(accounts, existing)
    assert bad == ["2"]
