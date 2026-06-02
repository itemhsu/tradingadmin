"""admin_gui/services/broker_creds.py — 依券商 schema 推導金鑰欄位與 Secret 命名。

純邏輯、可單測（不依賴 GUI）。對應計劃書 A-2 ~ A-4。

- credential_inputs(spec)  → 使用者需手動輸入的金鑰欄位（排除可自動取得的 ACCOUNT_ID）
- needs_account_discovery  → 該券商是否可用 token 自動取回 account_id
- secret_writes(...)       → 要寫進 GitHub Secrets 的 {名稱: 值}
                             （Alpaca 沿用引擎依賴的 _ALPACA_KEY/_ALPACA_SECRET）
"""
from __future__ import annotations

from typing import Dict, List, Tuple


def _plain_keys(spec: dict) -> List[str]:
    """required_env 去掉 {PREFIX}_ 後的名稱，如 API_KEY / API_SECRET / ACCOUNT_ID。"""
    auth = (spec or {}).get("auth", {}) or {}
    out = []
    for tpl in auth.get("required_env", []) or []:
        out.append(tpl.replace("{PREFIX}_", "").replace("{PREFIX}", ""))
    return out


def needs_account_discovery(spec: dict) -> bool:
    d = (spec or {}).get("account_discovery") or {}
    return bool(d.get("endpoint") and d.get("account_id_path"))


def credential_inputs(spec: dict) -> List[Tuple[str, str, bool]]:
    """回傳 (key, 顯示標籤, 是否遮罩) 清單 —— 使用者要手動輸入的金鑰欄。

    ACCOUNT_ID 若該券商支援自動取得（account_discovery）則<b>排除</b>，
    使用者就只需輸入一個 token。
    """
    method = ((spec or {}).get("auth") or {}).get("method", "")
    out: List[Tuple[str, str, bool]] = []
    for key in _plain_keys(spec):
        if key == "ACCOUNT_ID" and needs_account_discovery(spec):
            continue
        if key == "API_KEY":
            label = "API Token" if method == "bearer_token" else "API Key"
        elif key == "API_SECRET":
            label = "API Secret"
        elif key == "ACCOUNT_ID":
            label = "Account ID"
        else:
            label = key.replace("_", " ").title()
        out.append((key, label, True))
    return out


def secret_writes(broker_id: str, spec: dict, prefix: str,
                  values: Dict[str, str]) -> Dict[str, str]:
    """回傳要寫入 GitHub Secrets 的 {名稱: 值}。

    - Alpaca：沿用引擎 run_account.py 依賴的 {PFX}_ALPACA_KEY / {PFX}_ALPACA_SECRET。
    - 其他券商：依 broker.auth.required_env 模板（如 {PFX}_API_KEY / {PFX}_ACCOUNT_ID）。
    只寫有值的項目。
    """
    if broker_id == "alpaca":
        out = {}
        if values.get("API_KEY"):
            out[f"{prefix}_ALPACA_KEY"] = values["API_KEY"]
        if values.get("API_SECRET"):
            out[f"{prefix}_ALPACA_SECRET"] = values["API_SECRET"]
        return out

    auth = (spec or {}).get("auth", {}) or {}
    out = {}
    for tpl in auth.get("required_env", []) or []:
        name = tpl.replace("{PREFIX}", prefix)
        key = tpl.replace("{PREFIX}_", "").replace("{PREFIX}", "")
        if values.get(key):
            out[name] = values[key]
    return out
