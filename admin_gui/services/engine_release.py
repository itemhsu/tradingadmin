"""admin_gui/services/engine_release.py — 引擎版本管理（兩 repo GUI G2）。

列引擎 Release 版本、下載 wheel、計算 vendor/daily.yml 對應檔名。runner 可注入。
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Callable, List, Optional

ENGINE_REPO = "itemhsu/tech-rebalance-pub"
_WHEEL_RE = re.compile(r"tech_rebalance-([0-9][0-9.]*)-py3-none-any\.whl")


def wheel_name(version: str) -> str:
    return f"tech_rebalance-{version.lstrip('v')}-py3-none-any.whl"


def list_versions(repo: str = ENGINE_REPO, runner: Callable = subprocess.run,
                  limit: int = 30) -> List[str]:
    r = runner(["gh", "release", "list", "--repo", repo,
                "--json", "tagName", "--limit", str(limit)],
               capture_output=True, text=True)
    if getattr(r, "returncode", 1) != 0:
        return []
    try:
        return [d["tagName"] for d in json.loads(r.stdout or "[]")]
    except (ValueError, KeyError):
        return []


def download_wheel(version: str, dest_dir: str, repo: str = ENGINE_REPO,
                   runner: Callable = subprocess.run) -> Optional[str]:
    """下載指定版本 wheel 到 dest_dir，回 wheel 檔名；失敗 None。"""
    r = runner(["gh", "release", "download", version, "--repo", repo,
                "--pattern", "*.whl", "--dir", dest_dir],
               capture_output=True, text=True)
    if getattr(r, "returncode", 1) != 0:
        return None
    whls = list(Path(dest_dir).glob("*.whl"))
    return whls[0].name if whls else None


def pinned_version(daily_yml_text: str) -> Optional[str]:
    """從 daily.yml 的 vendor wheel 檔名解析目前釘的引擎版本。"""
    m = _WHEEL_RE.search(daily_yml_text)
    return m.group(1) if m else None


def bump_daily(daily_yml_text: str, new_version: str) -> str:
    """把 daily.yml 內的 wheel 檔名換成新版本。"""
    return _WHEEL_RE.sub(wheel_name(new_version), daily_yml_text)


_GIT_PIN_RE = re.compile(r"tech-rebalance-pub@(v?[0-9][0-9.]*)")


def pinned_git_version(daily_yml_text: str):
    """從 daily.yml 的 git+ 安裝行解析釘的引擎版本（如 v1.0.6）。"""
    m = _GIT_PIN_RE.search(daily_yml_text)
    return m.group(1) if m else None


def bump_git_version(daily_yml_text: str, new_version: str) -> str:
    """把 daily.yml git+ 安裝行的 @vX 換成新版本。"""
    return _GIT_PIN_RE.sub(f"tech-rebalance-pub@{new_version}", daily_yml_text)
