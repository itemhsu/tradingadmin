"""帳戶改進測試（A-2 ~ A-4 / G-65 ~ G-67）。純邏輯 + mock，不啟動 GUI。"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from admin_gui.services.catalog import Catalog
from admin_gui.services import broker_creds, probes

CAT = Catalog(ROOT)
ALPACA = CAT.broker_spec("alpaca")
TRADIER = CAT.broker_spec("tradier")


# ── G-65：使用者要輸入的金鑰欄位依券商 ──────────────────────────────────
def test_credential_inputs_alpaca():
    keys = [k for k, _, _ in broker_creds.credential_inputs(ALPACA)]
    assert keys == ["API_KEY", "API_SECRET"]


def test_credential_inputs_tradier_single_token():
    fields = broker_creds.credential_inputs(TRADIER)
    keys = [k for k, _, _ in fields]
    assert keys == ["API_KEY"]                 # 只一個，ACCOUNT_ID 自動取得
    assert fields[0][1] == "API Token"         # bearer → 標籤是 Token
    assert broker_creds.needs_account_discovery(TRADIER) is True
    assert broker_creds.needs_account_discovery(ALPACA) is False


# ── G-66：寫入 Secret 名稱依券商 ────────────────────────────────────────
def test_secret_writes_alpaca_keeps_engine_names():
    out = broker_creds.secret_writes("alpaca", ALPACA, "ACC7",
                                     {"API_KEY": "PK1", "API_SECRET": "s1"})
    assert out == {"ACC7_ALPACA_KEY": "PK1", "ACC7_ALPACA_SECRET": "s1"}


def test_secret_writes_tradier_uses_required_env():
    out = broker_creds.secret_writes("tradier", TRADIER, "ACC8",
                                     {"API_KEY": "tok", "ACCOUNT_ID": "VA123"})
    assert out == {"ACC8_API_KEY": "tok", "ACC8_ACCOUNT_ID": "VA123"}


# ── G-67：Tradier 用 token 自動取回 account_id（mock HTTP）─────────────────
def test_fetch_account_id_tradier(monkeypatch):
    payload = {"profile": {"account": {"account_number": "VA9999999"}}}

    class _Resp:
        def read(self): return json.dumps(payload).encode()
        def __enter__(self): return self
        def __exit__(self, *a): return False

    monkeypatch.setattr(probes.urllib.request, "urlopen", lambda *a, **k: _Resp())
    ok, acc = probes.fetch_account_id(TRADIER, "sandbox", "tok")
    assert ok and acc == "VA9999999"


def test_fetch_account_id_handles_list(monkeypatch):
    # Tradier 多帳號時 account 是 list → 取第一個
    payload = {"profile": {"account": [{"account_number": "VA1"}, {"account_number": "VA2"}]}}

    class _Resp:
        def read(self): return json.dumps(payload).encode()
        def __enter__(self): return self
        def __exit__(self, *a): return False

    monkeypatch.setattr(probes.urllib.request, "urlopen", lambda *a, **k: _Resp())
    ok, acc = probes.fetch_account_id(TRADIER, "sandbox", "tok")
    assert ok and acc == "VA1"
