"""admin_gui/services/account_factory.py — 從極簡輸入產出完整帳戶 dict（需求 1,2,7,8）。

使用者只給：name(label) / broker / environment / strategy。
系統自動補：id（下一個可用號）/ secret_prefix=ACC{id} / data_dir=data/{id} / use_new_runner=true。
"""
from __future__ import annotations

from typing import List, Optional


def next_id(existing_ids: List[str]) -> str:
    """回傳下一個可用的數字 id（字串）。"""
    nums = []
    for i in existing_ids:
        try:
            nums.append(int(i))
        except (ValueError, TypeError):
            pass
    return str((max(nums) + 1) if nums else 1)


def build_account(name: str, broker: str, environment: str, strategy: str,
                  existing_ids: List[str], enabled: bool = True,
                  email_recipients: Optional[List[str]] = None) -> dict:
    """組出完整 accounts.json 帳戶 dict。name(label) 必填。"""
    if not (name or "").strip():
        raise ValueError("帳戶名稱（label）必填")
    if not (strategy or "").strip():
        raise ValueError("策略必填")
    acc_id = next_id(existing_ids)
    return {
        "id": acc_id,
        "label": name.strip(),
        "strategy": strategy,
        "broker": broker or "alpaca",
        "environment": environment or "paper",
        "enabled": bool(enabled),
        "secret_prefix": f"ACC{acc_id}",
        "data_dir": f"data/{acc_id}",
        "use_new_runner": True,
        "email_recipients": email_recipients or [],
    }
