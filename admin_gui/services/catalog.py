"""admin_gui/services/catalog.py — broker / strategy 選項來源。

優先序：
  1. manifest（明確傳入）
  2. store 目錄（repo 的 brokers/ strategies/，fork 模式）
  3. pub engine manifest 自動 fetch（store 為空時，薄殼 Repo B 模式）
  4. 靜態預設值（網路不通時保底，確保下拉選單永不空白）
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from admin_gui.services import manifest as mf
from admin_gui.services.repo_store import LocalStore

_DEFAULT_ROOT = Path(__file__).resolve().parent.parent.parent

# 保底預設值——pub engine 支援的最小集合（網路不通時使用）
_FALLBACK_BROKERS = ["alpaca", "tradier"]
_FALLBACK_STRATEGIES = [
    "top10", "d2p2t6", "mom_6m_t20", "weekly_top10",
    "us100_mom_6m_t10", "tech100_mom_6m_t10",
]
_FALLBACK_ENVS = {"alpaca": ["paper", "live"], "tradier": ["paper", "live"]}


def _stems(names: List[str], exclude: str) -> List[str]:
    out = []
    for n in names:
        if n.endswith(".json") and exclude not in n:
            out.append(n[:-len(".json")])
    return sorted(out)


class Catalog:
    def __init__(self, root=None, store=None, manifest: Optional[dict] = None) -> None:
        self.manifest = manifest          # 給了就用 manifest（repo_b 模式）
        self._cached_pub: Optional[dict] = None   # pub engine manifest 快取
        if store is not None:
            self.store = store
            self.root = getattr(store, "root", _DEFAULT_ROOT)
        else:
            self.root = Path(root) if root else _DEFAULT_ROOT
            self.store = LocalStore(self.root)

    def _fetch_pub_manifest(self) -> Optional[dict]:
        """從 pub engine 最新 release 取 manifest（快取，只請求一次）。"""
        if self._cached_pub is not None:
            return self._cached_pub
        try:
            from admin_gui.services import engine_release as er
            versions = er.list_versions()
            if versions:
                m = mf.fetch_manifest(versions[0], use_cache=True)
                if m:
                    self._cached_pub = m
                    return m
        except Exception:   # noqa: BLE001
            pass
        return None

    # ── 策略 / 券商清單 ──────────────────────────────────────────────────
    def list_brokers(self) -> List[str]:
        if self.manifest is not None:
            return mf.brokers(self.manifest)
        result = _stems(self.store.list_dir("brokers"), "broker-schema")
        if result:
            return result
        # store 為空（薄殼 Repo B）→ 從 pub engine manifest 取
        m = self._fetch_pub_manifest()
        if m:
            return mf.brokers(m)
        return _FALLBACK_BROKERS

    def list_strategies(self) -> List[str]:
        if self.manifest is not None:
            return mf.strategies(self.manifest)
        result = _stems(self.store.list_dir("strategies"), "schema")
        if result:
            return result
        m = self._fetch_pub_manifest()
        if m:
            return mf.strategies(m)
        return _FALLBACK_STRATEGIES

    def broker_environments(self, broker_id: str) -> List[str]:
        if self.manifest is not None:
            return mf.broker_environments(self.manifest, broker_id)
        envs = sorted((self.broker_spec(broker_id).get("environments") or {}).keys())
        if envs:
            return envs
        m = self._fetch_pub_manifest()
        if m:
            e = mf.broker_environments(m, broker_id)
            if e:
                return e
        return _FALLBACK_ENVS.get(broker_id, ["paper", "live"])

    def required_secrets(self, secret_prefix: str, broker_id: str) -> List[str]:
        """該帳戶應設的 Secret 名稱。"""
        if self.manifest is not None:
            return mf.required_secrets(self.manifest, broker_id, secret_prefix)
        auth = self.broker_spec(broker_id).get("auth", {}) or {}
        secrets = [tpl.replace("{PREFIX}", secret_prefix)
                   for tpl in (auth.get("required_env") or [])]
        if secrets:
            return secrets
        m = self._fetch_pub_manifest()
        if m:
            s = mf.required_secrets(m, broker_id, secret_prefix)
            if s:
                return s
        return []

    # ── 舊 fork 模式才用（讀 repo 目錄）─────────────────────────────────
    def broker_spec(self, broker_id: str) -> dict:
        return self.store.read_json(f"brokers/{broker_id}.json")
