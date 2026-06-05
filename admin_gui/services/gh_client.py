"""admin_gui/services/gh_client.py — 封裝 gh CLI（Secrets / auth）。

安全核心：
  - 設 Secret 的「值」一律經 stdin 餵 `gh secret set NAME`（不帶 --body），
    絕不放進命令列參數（避免 ps / shell history / log 外洩）。
  - 本模組不寫任何檔、不 log secret 值。

⚠ 歷史 bug（2026-06 修正）：曾用 `gh secret set NAME --body -`，誤以為 `-`
  代表「從 stdin 讀」。實際上 gh 把 `--body -` 當成「值＝字面一個減號 -」，
  完全忽略 stdin → 所有 secret 都被存成 "-"，雲端拿 "-" 登入一律失敗（535 等）。
  正解：完全不要 --body，gh 沒有 --body 時就會從 stdin 讀值。

runner 可注入（預設 subprocess.run），方便單測不打真 gh。
"""
from __future__ import annotations

import json
import subprocess
from typing import Callable, List, Optional, Set


class GhError(Exception):
    pass


class GhClient:
    def __init__(self, repo: str, runner: Optional[Callable] = None) -> None:
        self.repo = repo
        self._run = runner or subprocess.run

    # ── auth ──────────────────────────────────────────────────────────
    def auth_ok(self) -> bool:
        try:
            r = self._run(["gh", "auth", "status"],
                          capture_output=True, text=True)
            return r.returncode == 0
        except FileNotFoundError:
            return False

    # ── secrets：讀存在狀態（拿不到值）────────────────────────────────
    def list_secret_names(self) -> Set[str]:
        r = self._run(["gh", "secret", "list", "--repo", self.repo,
                       "--json", "name"],
                      capture_output=True, text=True)
        if r.returncode != 0:
            raise GhError(f"gh secret list 失敗：{r.stderr[:200]}")
        try:
            data = json.loads(r.stdout or "[]")
        except json.JSONDecodeError:
            return set()
        return {item.get("name") for item in data if item.get("name")}

    # ── secrets：設定（值經 stdin，不落地）────────────────────────────
    def set_secret(self, name: str, value: str) -> None:
        """設一個 Secret。value 經 stdin 餵 gh，不出現在命令列。"""
        if not name:
            raise GhError("secret 名稱不可為空")
        # 注意：value 只放 input=（經 stdin），不放 cmd list。
        # 絕不加 --body：gh 把 `--body -` 當字面值 "-"，會吃掉真正的值。
        cmd = ["gh", "secret", "set", name, "--repo", self.repo]
        r = self._run(cmd, input=value, capture_output=True, text=True)
        if r.returncode != 0:
            # stderr 不會含我們的值；但保險起見仍只截短
            raise GhError(f"設定 {name} 失敗：{r.stderr[:200]}")
