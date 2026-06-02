"""admin_gui/services/state_reader.py — 讀各帳戶 portfolio_state（顯示用）。

只讀；缺檔回 None（不丟例外），讓 GUI 顯示「待產生」。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from admin_gui.services.repo_store import LocalStore

_DEFAULT_ROOT = Path(__file__).resolve().parent.parent.parent


@dataclass
class AccountState:
    nav: Optional[float] = None
    cash: Optional[float] = None
    date: Optional[str] = None
    n_positions: int = 0
    exists: bool = False


class StateReader:
    def __init__(self, root=None, store=None) -> None:
        if store is not None:
            self.store = store
            self.root = getattr(store, "root", _DEFAULT_ROOT)
        else:
            self.root = Path(root) if root else _DEFAULT_ROOT
            self.store = LocalStore(self.root)

    def read(self, account: dict) -> AccountState:
        data_dir = account.get("data_dir") or f"data/{account.get('id')}"
        try:
            text = self.store.read_text_or_none(f"{data_dir}/portfolio_state.json")
        except Exception:  # noqa: BLE001
            return AccountState(exists=False)
        if not text:
            return AccountState(exists=False)
        try:
            s = json.loads(text)
        except Exception:
            return AccountState(exists=False)
        return AccountState(
            nav=s.get("nav"),
            cash=s.get("cash"),
            date=s.get("date"),
            n_positions=len(s.get("positions") or []),
            exists=True,
        )
