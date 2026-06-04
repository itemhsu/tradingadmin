"""admin_gui/services/catalog.py — broker / strategy 選項來源。

架構原則：brokers / strategies / schemas 是 pub engine 的公開資源，
**不在 Repo B**。Catalog 一律從 pub engine manifest 取，不讀 Repo B。

來源優先序：
  1. manifest（明確傳入，測試或快取用）
  2. pub engine manifest（自動 fetch，快取一次）
  3. 靜態預設值（網路不通時保底，確保下拉永不空白）
"""
from __future__ import annotations

from typing import List, Optional

from admin_gui.services import manifest as mf

# 保底預設值——pub engine 支援的最小集合（網路不通時使用）
_FALLBACK_BROKERS = ["alpaca", "tradier"]
_FALLBACK_STRATEGIES = [
    "top10", "d2p2t6", "mom_6m_t20", "weekly_top10",
    "us100_mom_6m_t10", "tech100_mom_6m_t10",
]
_FALLBACK_ENVS = {"alpaca": ["paper", "live"], "tradier": ["paper", "live"]}


class Catalog:
    def __init__(self, root=None, store=None, manifest: Optional[dict] = None) -> None:
        # store / root 保留供相容（catalog 已不讀 Repo B，但呼叫端仍傳入）
        self.manifest = manifest
        self._cached_pub: Optional[dict] = None

    # ── manifest 來源 ────────────────────────────────────────────────────
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

    def _effective_manifest(self) -> dict:
        """有效 manifest：明確傳入 > pub engine auto-fetch > {}。"""
        if self.manifest is not None:
            return self.manifest
        return self._fetch_pub_manifest() or {}

    # ── 券商 / 策略清單（全部讀 manifest，不讀 Repo B）──────────────────
    def list_brokers(self) -> List[str]:
        m = self._effective_manifest()
        return mf.brokers(m) if m.get("brokers") else _FALLBACK_BROKERS

    def list_strategies(self) -> List[str]:
        m = self._effective_manifest()
        return mf.strategies(m) if m.get("strategies") else _FALLBACK_STRATEGIES

    def broker_spec(self, broker_id: str) -> dict:
        m = self._effective_manifest()
        return (m.get("brokers") or {}).get(broker_id, {})

    def broker_environments(self, broker_id: str) -> List[str]:
        m = self._effective_manifest()
        if m.get("brokers"):
            envs = mf.broker_environments(m, broker_id)
            if envs:
                return envs
        return _FALLBACK_ENVS.get(broker_id, ["paper", "live"])

    def required_secrets(self, secret_prefix: str, broker_id: str) -> List[str]:
        """該帳戶應設的 Secret 名稱（manifest 的 required_env 模板）。"""
        m = self._effective_manifest()
        if m.get("brokers"):
            secrets = mf.required_secrets(m, broker_id, secret_prefix)
            if secrets:
                return secrets
        # fallback：alpaca 的標準雙金鑰
        spec = self.broker_spec(broker_id)
        return [t.replace("{PREFIX}", secret_prefix)
                for t in (spec.get("required_env") or [])]
