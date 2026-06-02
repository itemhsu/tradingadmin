"""Phase A 測試：admin_gui service 層（G-01 ~ G-04, G-10）。

純邏輯，不啟動 GUI、不需要 PySide6。
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from admin_gui.services.accounts_repo import AccountsRepo
from admin_gui.services.catalog import Catalog
from admin_gui.services.state_reader import StateReader
from admin_gui.models.account import validate_account


@pytest.fixture
def tmp_root(tmp_path):
    """複製真實 accounts.json + brokers/strategies 到臨時 root。"""
    (tmp_path / "brokers").mkdir()
    (tmp_path / "strategies").mkdir()
    shutil.copy(ROOT / "accounts.json", tmp_path / "accounts.json")
    for p in (ROOT / "brokers").glob("*.json"):
        shutil.copy(p, tmp_path / "brokers" / p.name)
    for name in ("top10.json", "d2p2t6.json"):
        src = ROOT / "strategies" / name
        if src.exists():
            shutil.copy(src, tmp_path / "strategies" / name)
    return tmp_path


# ── G-01 ─────────────────────────────────────────────────────────────────
def test_load_missing_file_returns_empty(tmp_path):
    """accounts.json 不存在時 load() 回 []（不崩潰）——打包後 skip 精靈的情境。"""
    repo = AccountsRepo(tmp_path)            # tmp_path 無 accounts.json
    assert repo.load() == []
    assert repo.ids() == []


def test_G01_load_save_roundtrip_lossless(tmp_root):
    repo = AccountsRepo(tmp_root)
    before = json.loads((tmp_root / "accounts.json").read_text(encoding="utf-8"))
    repo.save(repo.load())                       # 讀→寫
    after = json.loads((tmp_root / "accounts.json").read_text(encoding="utf-8"))
    assert before == after, "round-trip 應無損"


def test_G01b_unknown_fields_preserved(tmp_root):
    """更新一個欄位後，其他未知欄位（如 alpaca_secret_prefix/runner_sub_id）保留。"""
    repo = AccountsRepo(tmp_root)
    repo.update("2", {"label": "改名測試"})
    acc2 = repo.get("2")
    assert acc2["label"] == "改名測試"
    assert acc2.get("alpaca_secret_prefix") == "ACC2"   # 未動的舊欄位仍在
    assert acc2.get("runner_sub_id") == "1"


# ── G-02 ─────────────────────────────────────────────────────────────────
def test_G02_duplicate_id_rejected(tmp_root):
    repo = AccountsRepo(tmp_root)
    with pytest.raises(ValueError, match="已存在"):
        repo.add({"id": "1", "strategy": "top10", "broker": "alpaca",
                  "secret_prefix": "ACC1"})


def test_G02b_missing_required_rejected():
    errs = validate_account({"id": "", "strategy": "", "broker": ""})
    assert any("id" in e for e in errs)
    assert any("strategy" in e for e in errs)
    assert any("broker" in e for e in errs)


# ── G-03 ─────────────────────────────────────────────────────────────────
def test_G03_catalog_dropdowns_from_dirs(tmp_root):
    cat = Catalog(tmp_root)
    assert "alpaca" in cat.list_brokers()
    assert "tradier" in cat.list_brokers()
    assert "broker-schema-v1" not in cat.list_brokers()
    assert set(cat.broker_environments("tradier")) == {"sandbox", "live"}
    assert "top10" in cat.list_strategies()


def test_G03b_required_secrets_derived(tmp_root):
    cat = Catalog(tmp_root)
    secs = cat.required_secrets("ACC6", "tradier")
    assert "ACC6_API_KEY" in secs
    assert "ACC6_ACCOUNT_ID" in secs


# ── G-04 ─────────────────────────────────────────────────────────────────
def test_G04_delete_removes_entry_keeps_data(tmp_root):
    # 造一個假 data 目錄，刪帳戶後該目錄仍在
    (tmp_root / "data" / "1").mkdir(parents=True)
    (tmp_root / "data" / "1" / "portfolio_state.json").write_text("{}")
    repo = AccountsRepo(tmp_root)
    repo.delete("1")
    assert "1" not in repo.ids()
    assert (tmp_root / "data" / "1" / "portfolio_state.json").exists(), "data/ 不該被刪"


def test_G04b_add_then_delete(tmp_root):
    repo = AccountsRepo(tmp_root)
    repo.add({"id": "99", "strategy": "top10", "broker": "alpaca",
              "secret_prefix": "ACC99", "enabled": False})
    assert "99" in repo.ids()
    repo.delete("99")
    assert "99" not in repo.ids()


# ── G-10 ─────────────────────────────────────────────────────────────────
def test_G10_state_reader_missing_returns_not_exists(tmp_root):
    reader = StateReader(tmp_root)
    st = reader.read({"id": "3", "data_dir": "data/3"})
    assert st.exists is False
    assert st.nav is None


def test_G10b_state_reader_reads_existing(tmp_root):
    (tmp_root / "data" / "7").mkdir(parents=True)
    (tmp_root / "data" / "7" / "portfolio_state.json").write_text(
        json.dumps({"nav": 12345.0, "cash": 100.0, "date": "2026-06-01",
                    "positions": [{"symbol": "AAPL"}]}))
    reader = StateReader(tmp_root)
    st = reader.read({"id": "7", "data_dir": "data/7"})
    assert st.exists and st.nav == 12345.0 and st.n_positions == 1
