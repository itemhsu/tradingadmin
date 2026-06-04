"""admin_gui/services/catalog.py — broker / strategy 選項來源。

兩種來源（兩 repo 架構）：
  - manifest（新，repo_b 模式）：引擎 Release 的 manifest.json，因 Repo B 不含
    strategies/ brokers/ 目錄。
  - store 目錄（舊，fork 模式）：repo 的 brokers/ strategies/。
manifest 優先；沒給 manifest 才退回讀目錄。純讀取、可單測。
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from admin_gui.services import manifest as mf
from admin_gui.services.repo_store import LocalStore

_DEFAULT_ROOT = Path(__file__).resolve().parent.parent.parent


def _stems(names: List[str], exclude: str) -> List[str]:
    out = []
    for n in names:
        if n.endswith(".json") and exclude not in n:
            out.append(n[:-len(".json")])
    return sorted(out)


class Catalog:
    def __init__(self, root=None, store=None, manifest: Optional[dict] = None) -> None:
        self.manifest = manifest          # 給了就用 manifest（repo_b 模式）
        if store is not None:
            self.store = store
            self.root = getattr(store, "root", _DEFAULT_ROOT)
        else:
            self.root = Path(root) if root else _DEFAULT_ROOT
            self.store = LocalStore(self.root)

    # ── 策略 / 券商清單 ──────────────────────────────────────────────────
    def list_brokers(self) -> List[str]:
        if self.manifest is not None:
            return mf.brokers(self.manifest)
        return _stems(self.store.list_dir("brokers"), "broker-schema")

    def list_strategies(self) -> List[str]:
        if self.manifest is not None:
            return mf.strategies(self.manifest)
        return _stems(self.store.list_dir("strategies"), "schema")

    def broker_environments(self, broker_id: str) -> List[str]:
        if self.manifest is not None:
            return mf.broker_environments(self.manifest, broker_id)
        return sorted((self.broker_spec(broker_id).get("environments") or {}).keys())

    def required_secrets(self, secret_prefix: str, broker_id: str) -> List[str]:
        """該帳戶應設的 Secret 名稱。"""
        if self.manifest is not None:
            return mf.required_secrets(self.manifest, broker_id, secret_prefix)
        auth = self.broker_spec(broker_id).get("auth", {}) or {}
        return [tpl.replace("{PREFIX}", secret_prefix)
                for tpl in (auth.get("required_env") or [])]

    # ── 舊 fork 模式才用（讀 repo 目錄）─────────────────────────────────
    def broker_spec(self, broker_id: str) -> dict:
        return self.store.read_json(f"brokers/{broker_id}.json")
