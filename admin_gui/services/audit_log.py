"""admin_gui/services/audit_log.py — 操作日誌（需求 10 / G-21）。

記錄所有帳戶管理動作；每行一筆 JSON。永不寫入任何金鑰值。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

# 存使用者家目錄（穩定，打包後仍持久）
_DEFAULT = Path.home() / ".tradingadmin" / "audit.jsonl"

# 允許的動作（白名單，避免亂寫）
ACTIONS = {"create", "edit", "delete", "enable", "disable",
           "set_secret", "cron_change", "test_connection", "test_email", "fork"}


class AuditLog:
    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = Path(path) if path else _DEFAULT
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, action: str, target: str, result: str = "ok",
               detail: str = "") -> None:
        """寫一筆。detail 由呼叫者保證不含金鑰值。"""
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "action": action,
            "target": target,
            "result": result,
            "detail": detail,
        }
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def read(self, limit: Optional[int] = None,
             action: Optional[str] = None,
             result: Optional[str] = None) -> List[dict]:
        """倒序回傳事件（最新在前），可依 action / result 篩選。"""
        if not self.path.exists():
            return []
        out: List[dict] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            if action and e.get("action") != action:
                continue
            if result and e.get("result") != result:
                continue
            out.append(e)
        out.reverse()
        return out[:limit] if limit else out
