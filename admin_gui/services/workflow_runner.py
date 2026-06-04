"""admin_gui/services/workflow_runner.py — 觸發/查 Repo B 的 daily.yml（兩 repo GUI G2）。

執行按鈕的後端：dry-run / 強制再平衡 / 列 runs / 看 log。
live + force 需明確確認（防呆）。runner 可注入。
"""
from __future__ import annotations

import json
import subprocess
from typing import Callable, List


class LiveForceNotConfirmed(Exception):
    """live 環境下 force 再平衡未經確認 → 拒絕送出（防真錢誤觸）。"""


def run_workflow(repo: str, *, workflow: str = "daily.yml",
                 dry_run: bool = True, force: bool = False,
                 environment: str = "paper", confirmed: bool = False,
                 runner: Callable = subprocess.run) -> bool:
    """觸發 workflow_dispatch。live+force 未確認 → 拋 LiveForceNotConfirmed。"""
    if environment == "live" and force and not confirmed:
        raise LiveForceNotConfirmed("live 環境強制再平衡需明確確認")
    args = ["gh", "workflow", "run", workflow, "--repo", repo,
            "-f", f"dry_run={'true' if dry_run else 'false'}",
            "-f", f"force={'true' if force else 'false'}"]
    r = runner(args, capture_output=True, text=True)
    return getattr(r, "returncode", 1) == 0


def list_runs(repo: str, *, workflow: str = "daily.yml", limit: int = 10,
              runner: Callable = subprocess.run) -> List[dict]:
    r = runner(["gh", "run", "list", "--repo", repo, "--workflow", workflow,
                "--json", "databaseId,status,conclusion,createdAt,displayTitle",
                "--limit", str(limit)], capture_output=True, text=True)
    if getattr(r, "returncode", 1) != 0:
        return []
    try:
        return json.loads(r.stdout or "[]")
    except ValueError:
        return []


def view_log(repo: str, run_id, *, failed_only: bool = False,
             runner: Callable = subprocess.run) -> str:
    flag = "--log-failed" if failed_only else "--log"
    r = runner(["gh", "run", "view", str(run_id), "--repo", repo, flag],
               capture_output=True, text=True)
    return r.stdout if getattr(r, "returncode", 1) == 0 else ""
