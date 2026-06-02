"""admin_gui/services/global_config.py — 非機密的全域設定（可顯示明文）。

EMAIL_SENDER（寄件人 email）等不具機密性，存本機 config 並直接顯示，
不放進遮罩的 Secrets 清單。App 密碼等機密仍走 GitHub Secrets。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

# 存使用者家目錄（穩定）；打包後 bundle 內路徑是暫時的、每次開都不同會遺失設定
_DEFAULT = Path.home() / ".tradingadmin" / "config.json"


class GlobalConfig:
    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = Path(path) if path else _DEFAULT
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}

    def get(self, key: str, default: str = "") -> str:
        return str(self.load().get(key, default))

    def set(self, key: str, value: str) -> None:
        d = self.load()
        d[key] = value
        self.path.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n",
                             encoding="utf-8")

    # 便捷存取
    def email_sender(self) -> str:
        return self.get("email_sender")

    def set_email_sender(self, v: str) -> None:
        self.set("email_sender", v)
