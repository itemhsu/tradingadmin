"""admin_gui/services/catalog.py — 從 repo 動態列出 broker / strategy 選項。

GUI 下拉選單的資料來源，重用既有的 brokers/ 與 strategies/ 目錄。
純讀取、可單測。
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from admin_gui.services.repo_store import LocalStore

_DEFAULT_ROOT = Path(__file__).resolve().parent.parent.parent


def _stems(names: List[str], exclude: str) -> List[str]:
    out = []
    for n in names:
        if n.endswith(".json") and exclude not in n:
            out.append(n[:-len(".json")])
    return sorted(out)


class Catalog:
    def __init__(self, root=None, store=None) -> None:
        if store is not None:
            self.store = store
            self.root = getattr(store, "root", _DEFAULT_ROOT)
        else:
            self.root = Path(root) if root else _DEFAULT_ROOT
            self.store = LocalStore(self.root)

    def list_brokers(self) -> List[str]:
        return _stems(self.store.list_dir("brokers"), "broker-schema")

    def broker_spec(self, broker_id: str) -> dict:
        return self.store.read_json(f"brokers/{broker_id}.json")

    def broker_environments(self, broker_id: str) -> List[str]:
        return sorted((self.broker_spec(broker_id).get("environments") or {}).keys())

    def list_strategies(self) -> List[str]:
        return _stems(self.store.list_dir("strategies"), "schema")

    def required_secrets(self, secret_prefix: str, broker_id: str) -> List[str]:
        """依 broker spec 的 auth.required_env 推導該帳戶應有的 Secret 名稱。"""
        auth = self.broker_spec(broker_id).get("auth", {}) or {}
        out: List[str] = []
        for tpl in (auth.get("required_env") or []):
            out.append(tpl.replace("{PREFIX}", secret_prefix))
        return out
