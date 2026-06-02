"""admin_gui/services/log_reader.py — 全域 log（需求15）+ 帳戶 log（需求16）讀取。

全域：操作日誌 audit.jsonl + cron 執行歷史（gh run list）。
帳戶：data/{id}/trade_events.jsonl + portfolio_state_history.json。
皆唯讀；缺檔回空，不丟例外。
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import List, Optional

_ROOT = Path(__file__).resolve().parent.parent.parent


def _read_jsonl(path: Path, limit: Optional[int], reverse: bool = True) -> List[dict]:
    if not path.exists():
        return []
    out: List[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    if reverse:
        out.reverse()
    return out[:limit] if limit else out


# ── 全域：cron 執行歷史 ─────────────────────────────────────────────────
def cron_runs(repo: str = "itemhsu/tech-rebalance", limit: int = 10,
              runner=None) -> List[dict]:
    """gh run list → [{workflow, status, conclusion, createdAt}]。失敗回空。"""
    run = runner or subprocess.run
    try:
        r = run(["gh", "run", "list", "--repo", repo, "--limit", str(limit),
                 "--json", "workflowName,status,conclusion,createdAt"],
                capture_output=True, text=True, timeout=15)
        if r.returncode != 0:
            return []
        return json.loads(r.stdout or "[]")
    except Exception:  # noqa: BLE001
        return []


def _jsonl_from_text(text: Optional[str], limit: Optional[int],
                     reverse: bool = True) -> List[dict]:
    if not text:
        return []
    out: List[dict] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    if reverse:
        out.reverse()
    return out[:limit] if limit else out


# ── 帳戶：交易事件 + NAV 歷史 ───────────────────────────────────────────
def account_trade_events(account: dict, limit: int = 50,
                         root: Optional[Path] = None, store=None) -> List[dict]:
    data_dir = account.get("data_dir") or f"data/{account.get('id')}"
    rel = f"{data_dir}/trade_events.jsonl"
    if store is not None:
        try:
            return _jsonl_from_text(store.read_text_or_none(rel), limit)
        except Exception:  # noqa: BLE001
            return []
    base = Path(root) if root else _ROOT
    return _read_jsonl(base / rel, limit)


def account_nav_history(account: dict, limit: int = 60,
                        root: Optional[Path] = None, store=None) -> List[dict]:
    data_dir = account.get("data_dir") or f"data/{account.get('id')}"
    rel = f"{data_dir}/portfolio_state_history.json"
    if store is not None:
        try:
            text = store.read_text_or_none(rel)
        except Exception:  # noqa: BLE001
            text = None
    else:
        base = Path(root) if root else _ROOT
        p = base / rel
        text = p.read_text(encoding="utf-8") if p.exists() else None
    if not text:
        return []
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    hist = data if isinstance(data, list) else data.get("history", [])
    hist = list(reversed(hist))
    return hist[:limit] if limit else hist
