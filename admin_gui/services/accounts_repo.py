"""admin_gui/services/accounts_repo.py — accounts.json 讀寫（含驗證）。

設計原則：
  - round-trip 無損：保留每個帳戶的未知欄位與鍵順序，只改使用者編輯的欄位。
  - 透過 store 後端讀寫：本機（LocalStore，原子寫）或 GitHub API（GhContentsStore，
    直接 commit，不需 clone）。
  - 純邏輯、不依賴 GUI → 可單測。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

from admin_gui.models.account import validate_account
from admin_gui.services.repo_store import LocalStore

_DEFAULT_ROOT = Path(__file__).resolve().parent.parent.parent
_PATH = "accounts.json"


class AccountsRepo:
    def __init__(self, root=None, audit=None, store=None) -> None:
        # store 優先；否則用 root（Path）→ LocalStore（向後相容測試）
        if store is not None:
            self.store = store
            self.root = getattr(store, "root", _DEFAULT_ROOT)
        else:
            self.root = Path(root) if root else _DEFAULT_ROOT
            self.store = LocalStore(self.root)
        # 操作日誌（需求 10 / G-21）。本機 store → 把 audit 放 root 下（測試不污染家目錄）；
        # 遠端（GitHub API）store → 存使用者家目錄預設位置。
        if audit is None:
            try:
                from admin_gui.services.audit_log import AuditLog
                if isinstance(self.store, LocalStore):
                    audit = AuditLog(Path(self.store.root) / "admin_gui" / "data" / "audit.jsonl")
                else:
                    audit = AuditLog()
            except Exception:
                audit = None
        self.audit = audit

    def _log(self, action: str, account: dict, result: str = "ok", detail: str = "") -> None:
        if not self.audit:
            return
        name = account.get("label") or ""
        target = f"{name}(#{account.get('id')})" if name else f"#{account.get('id')}"
        self.audit.record(action, target, result, detail)

    # ── 讀 ────────────────────────────────────────────────────────────
    def load(self) -> List[dict]:
        """回傳帳戶 dict list（保留原始欄位與順序）。檔案不存在/壞掉/讀取失敗 → 回 []。"""
        try:
            text = self.store.read_text_or_none(_PATH)
        except Exception:  # noqa: BLE001（網路/權限問題不該讓 GUI 崩）
            return []
        if not text:
            return []
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return []
        return data.get("accounts", [])

    def ids(self) -> List[str]:
        return [str(a.get("id")) for a in self.load()]

    def get(self, account_id: str) -> Optional[dict]:
        for a in self.load():
            if str(a.get("id")) == str(account_id):
                return a
        return None

    # ── 寫（本機原子 / 遠端 commit，由 store 決定）───────────────────────
    def save(self, accounts: List[dict], message: str = "") -> None:
        payload = {"accounts": accounts}
        text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        self.store.write_text(_PATH, text,
                              message or "chore(admin): update accounts.json")

    # ── CRUD ──────────────────────────────────────────────────────────
    def add(self, account: dict) -> None:
        accounts = self.load()
        errors = validate_account(account, existing_ids=[str(a.get("id")) for a in accounts])
        if errors:
            raise ValueError("；".join(errors))
        accounts.append(account)
        self.save(accounts, f"feat(account): add {account.get('label') or account.get('id')}")
        self._log("create", account)

    def update(self, account_id: str, changes: dict) -> None:
        accounts = self.load()
        idx = next((i for i, a in enumerate(accounts)
                    if str(a.get("id")) == str(account_id)), None)
        if idx is None:
            raise KeyError(f"找不到帳戶 id={account_id}")
        merged = {**accounts[idx], **changes}
        # 改 id 時要檢查新 id 不與其他人衝突
        other_ids = [str(a.get("id")) for j, a in enumerate(accounts) if j != idx]
        errors = validate_account(merged, existing_ids=other_ids)
        if errors:
            raise ValueError("；".join(errors))
        accounts[idx] = merged
        self.save(accounts, f"chore(account): update {merged.get('label') or account_id}")
        # enable/disable 視為獨立動作，其餘記 edit
        if set(changes.keys()) == {"enabled"}:
            self._log("enable" if changes["enabled"] else "disable", merged)
        else:
            self._log("edit", merged, detail="、".join(changes.keys()))

    def delete(self, account_id: str) -> None:
        """從 accounts.json 移除帳戶。注意：不刪 data/ 目錄（歷史保留）。"""
        accounts = self.load()
        gone = next((a for a in accounts if str(a.get("id")) == str(account_id)), None)
        remaining = [a for a in accounts if str(a.get("id")) != str(account_id)]
        if len(remaining) == len(accounts):
            raise KeyError(f"找不到帳戶 id={account_id}")
        self.save(remaining, f"chore(account): remove {(gone or {}).get('label') or account_id}")
        self._log("delete", gone or {"id": account_id})

    def set_enabled(self, account_id: str, enabled: bool) -> None:
        self.update(account_id, {"enabled": bool(enabled)})
