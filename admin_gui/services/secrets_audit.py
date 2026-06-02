"""admin_gui/services/secrets_audit.py — 推導「該有哪些 GitHub Secret」+ 比對存在狀態。

GitHub Secret 的正規命名（run_account 讀的名稱）：
  alpaca  : {prefix}_ALPACA_KEY / {prefix}_ALPACA_SECRET
  tradier : {prefix}_TRADIER_TOKEN / {prefix}_TRADIER_ACCOUNT  （docs/env-vars.md）
全域：EMAIL_SENDER / EMAIL_PASSWORD（SMTP 寄信，SendGrid 已棄用移除）

註：workflow 對舊命名有 fallback 鏈，但本工具只推「正規名」鼓勵使用者設正規 Secret。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Set

# 每家券商需要的 GitHub Secret 模板（{prefix} 會被帳戶的 secret_prefix 取代）
BROKER_SECRET_TEMPLATES = {
    "alpaca":  ["{prefix}_ALPACA_KEY", "{prefix}_ALPACA_SECRET"],
    "tradier": ["{prefix}_TRADIER_TOKEN", "{prefix}_TRADIER_ACCOUNT"],
}

# 全域 Secret：(名稱, 是否必填)
GLOBAL_SECRETS = [
    ("EMAIL_SENDER",    True),
    ("EMAIL_PASSWORD",  True),
]


@dataclass
class SecretRow:
    name: str
    source: str          # 帳戶 #N / 全域
    required: bool
    exists: bool

    @property
    def status(self) -> str:
        if self.exists:
            return "ok"
        return "missing_required" if self.required else "missing_optional"


def account_required_secrets(account: dict) -> List[str]:
    """單一帳戶需要的 GitHub Secret 名稱（正規命名）。"""
    prefix = account.get("secret_prefix") or account.get("alpaca_secret_prefix") or ""
    broker = account.get("broker", "alpaca")
    templates = BROKER_SECRET_TEMPLATES.get(broker, [])
    return [t.replace("{prefix}", prefix) for t in templates if prefix]


def audit(accounts: List[dict], existing: Set[str]) -> List[SecretRow]:
    """產生整體 Secret 稽核表（帳戶 + 全域）。"""
    rows: List[SecretRow] = []
    seen: Set[str] = set()
    for a in accounts:
        for name in account_required_secrets(a):
            if name in seen:
                continue
            seen.add(name)
            rows.append(SecretRow(name=name, source=f"帳戶 #{a.get('id')}",
                                  required=True, exists=name in existing))
    for name, required in GLOBAL_SECRETS:
        if name in seen:
            continue
        seen.add(name)
        rows.append(SecretRow(name=name, source="全域",
                              required=required, exists=name in existing))
    return rows


def accounts_missing_secrets(accounts: List[dict], existing: Set[str]) -> List[str]:
    """回傳「因缺必填 Secret 而無法執行」的帳戶 id 清單。"""
    bad = []
    for a in accounts:
        need = account_required_secrets(a)
        if need and any(n not in existing for n in need):
            bad.append(str(a.get("id")))
    return bad
