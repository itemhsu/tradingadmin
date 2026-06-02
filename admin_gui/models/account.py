"""admin_gui/models/account.py — 帳戶資料模型 + 驗證規則。

對應 accounts.json 的單一帳戶。欄位定義與 run_account.py 一致。
驗證為純函式，不依賴 GUI，可單測。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

# accounts.json 已知欄位（驗證/表單用）；未知欄位由 repo 層保留以維持 round-trip。
KNOWN_FIELDS = [
    "id", "strategy", "label", "enabled", "broker", "environment",
    "secret_prefix", "alpaca_secret_prefix", "data_dir", "runner_sub_id",
    "email_recipients", "use_new_runner",
]


@dataclass
class Account:
    id: str
    strategy: str
    broker: str = "alpaca"
    environment: str = "paper"
    secret_prefix: str = ""
    data_dir: str = ""
    label: str = ""
    enabled: bool = True
    email_recipients: List[str] = field(default_factory=list)
    use_new_runner: bool = True

    @classmethod
    def from_dict(cls, d: dict) -> "Account":
        return cls(
            id=str(d.get("id", "")),
            strategy=str(d.get("strategy", "")),
            broker=str(d.get("broker", "alpaca")),
            environment=str(d.get("environment", "paper")),
            secret_prefix=str(d.get("secret_prefix") or d.get("alpaca_secret_prefix") or ""),
            data_dir=str(d.get("data_dir", "")),
            label=str(d.get("label", "")),
            enabled=bool(d.get("enabled", True)),
            email_recipients=list(d.get("email_recipients") or []),
            use_new_runner=bool(d.get("use_new_runner", True)),
        )


def validate_account(d: dict, existing_ids: Optional[List[str]] = None) -> List[str]:
    """回傳錯誤訊息 list（空 = 通過）。existing_ids 用於檢查 id 不重複。"""
    errors: List[str] = []
    acc_id = str(d.get("id", "")).strip()
    if not acc_id:
        errors.append("id 不可為空")
    elif existing_ids is not None and acc_id in existing_ids:
        errors.append(f"id '{acc_id}' 已存在（不可重複）")

    if not str(d.get("strategy", "")).strip():
        errors.append("strategy 不可為空")
    if not str(d.get("broker", "")).strip():
        errors.append("broker 不可為空")
    prefix = d.get("secret_prefix") or d.get("alpaca_secret_prefix")
    if not str(prefix or "").strip():
        errors.append("secret_prefix 不可為空")

    er = d.get("email_recipients")
    if er is not None and not isinstance(er, list):
        errors.append("email_recipients 必須是清單")
    return errors
