"""CT-GUI-CONTRACT — 桌面 App ↔ 引擎跨倉契約（fork 相容性計劃 §6.1 ⑨）。

確保 App 能解析「引擎產出的最小合法樣本」而不丟例外，且對未來未知欄位寬鬆；
並驗證版本落差時會給出警告（compat.data_schema_warning）。

樣本形狀對齊引擎端 schema（tech-rebalance/schemas/*-schema-v1）：
  accounts-schema-v1 require id+strategy；broker-schema-v2 的 auth.required_env；
  portfolio-state-schema-v1 require date/nav/cash/positions。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from admin_gui.models.account import Account, validate_account          # noqa: E402
from admin_gui.services.catalog import Catalog                          # noqa: E402
from admin_gui.services.state_reader import StateReader                 # noqa: E402
from admin_gui.services.accounts_repo import AccountsRepo               # noqa: E402
from admin_gui.services.compat import data_schema_warning              # noqa: E402

_FUTURE = "__future_field_from_newer_engine__"


# ── 假 store：模擬從 fork repo 經 API 讀檔 ─────────────────────────────────────
class FakeStore:
    root = "/fake"

    def __init__(self, files: dict, dirs: dict | None = None):
        self._files = files            # {path: text}
        self._dirs = dirs or {}        # {path: [names]}

    def read_text_or_none(self, path):
        return self._files.get(path)

    def read_text(self, path):
        return self._files[path]

    def read_json(self, path):
        import json
        return json.loads(self._files[path])

    def list_dir(self, path):
        return self._dirs.get(path, [])


# ── 帳戶模型解析最小合法樣本 ────────────────────────────────────────────────
def test_account_from_minimal_engine_sample():
    minimal = {"id": "1", "strategy": "top10", "broker": "alpaca", "secret_prefix": "ACC1"}
    a = Account.from_dict(minimal)
    assert a.id == "1" and a.strategy == "top10"
    assert validate_account(minimal) == []          # 通過驗證


def test_account_tolerates_future_fields():
    d = {"id": "1", "strategy": "top10", "broker": "alpaca",
         "secret_prefix": "ACC1", _FUTURE: {"x": 1}, "another_future": [1, 2]}
    a = Account.from_dict(d)                          # 不應拋例外
    assert a.id == "1"
    assert validate_account(d) == []                 # 未知欄位不應造成驗證錯誤


# ── Catalog 解析最小券商 spec ───────────────────────────────────────────────
def test_catalog_parses_minimal_broker_spec():
    import json
    spec = {"id": "alpaca", "version": "1.0",
            "auth": {"required_env": ["{PREFIX}_API_KEY", "{PREFIX}_API_SECRET"]},
            "environments": {"paper": {}, "live": {}},
            _FUTURE: "ignored"}
    store = FakeStore(
        files={"brokers/alpaca.json": json.dumps(spec)},
        dirs={"brokers": ["alpaca.json", "broker-schema-v2.json"],
              "strategies": ["top10.json", "strategy-schema-v3.json"]},
    )
    cat = Catalog(store=store)
    assert "alpaca" in cat.list_brokers()            # 排除 broker-schema
    assert "top10" in cat.list_strategies()          # 排除 schema
    assert cat.broker_environments("alpaca") == ["live", "paper"]
    assert cat.required_secrets("ACC9", "alpaca") == ["ACC9_API_KEY", "ACC9_API_SECRET"]


# ── StateReader 對最小/未來/壞掉的 state 寬鬆 ────────────────────────────────
def test_state_reader_minimal_and_future():
    import json
    state = {"date": "2026-06-03", "nav": 1000.0, "cash": 0.0,
             "positions": [{"symbol": "AAPL", "qty": 1}], _FUTURE: 1}
    store = FakeStore(files={"data/1/portfolio_state.json": json.dumps(state)})
    st = StateReader(store=store).read({"id": "1", "data_dir": "data/1"})
    assert st.exists and st.nav == 1000.0 and st.n_positions == 1


def test_state_reader_broken_json_does_not_crash():
    store = FakeStore(files={"data/1/portfolio_state.json": "{not json"})
    st = StateReader(store=store).read({"id": "1", "data_dir": "data/1"})
    assert st.exists is False                         # 壞檔→exists False，不崩


# ── AccountsRepo 對缺 accounts 鍵寬鬆 ───────────────────────────────────────
def test_accounts_repo_missing_key_returns_empty():
    store = FakeStore(files={"accounts.json": '{"__future_top__": 1}'})
    assert AccountsRepo(store=store).load() == []     # 缺 accounts → [] 不崩


# ── 版本落差警告 ────────────────────────────────────────────────────────────
def test_version_warning_none_when_compatible():
    assert data_schema_warning("1.0") is None
    assert data_schema_warning(None) is None          # 無版本資訊不警告


def test_version_warning_present_when_skewed():
    w = data_schema_warning("2.0")
    assert w and "2.0" in w and "1.0" in w


# ── schema 漂移偵測（從 fork schemas/ 檔名）────────────────────────────────────
def test_parse_data_schema_majors():
    from admin_gui.services.compat import parse_data_schema_majors
    files = ["data-schema-v1.json", "data-schema-v2.json",
             "broker-schema-v1.json", "accounts-schema-v1.json", "README.md"]
    assert parse_data_schema_majors(files) == {1, 2}


def test_schema_drift_none_when_supported():
    from admin_gui.services.compat import schema_drift_warning
    assert schema_drift_warning(["data-schema-v1.json", "accounts-schema-v1.json"]) is None
    assert schema_drift_warning([]) is None            # 讀不到→不警告


def test_schema_drift_warns_when_engine_newer():
    from admin_gui.services.compat import schema_drift_warning
    w = schema_drift_warning(["data-schema-v1.json", "data-schema-v2.json"])
    assert w and "v2" in w and "DMG" in w              # 引擎較新→提示更新 App


def test_schema_drift_warns_when_engine_older():
    from admin_gui.services.compat import (
        schema_drift_warning, GUI_SUPPORTED_DATA_SCHEMA_MAJORS)
    # 模擬 App 只支援 v2+，但 fork 引擎還是 v1
    import admin_gui.services.compat as c
    orig = set(GUI_SUPPORTED_DATA_SCHEMA_MAJORS)
    c.GUI_SUPPORTED_DATA_SCHEMA_MAJORS = {2}
    try:
        w = schema_drift_warning(["data-schema-v1.json"])
        assert w and "v1" in w and "同步" in w
    finally:
        c.GUI_SUPPORTED_DATA_SCHEMA_MAJORS = orig
