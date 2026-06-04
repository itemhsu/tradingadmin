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


_REQ_RE = re.compile(
    r"(pip install\s+(?:-q\s+)?)-r\s+requirements\.txt",
    re.IGNORECASE,
)
_PUB_INSTALL = (
    'pip install "tech-rebalance'
    ' @ git+https://github.com/itemhsu/tech-rebalance-pub@{version}"'
)


_HARDCODED_DASH_RE = re.compile(
    r"(external_repository:\s*)[^\s/]+/tech-rebalance-dashboard",
)
# git clone URL: github.com/{owner}/tech-rebalance-dashboard.git
_HARDCODED_CLONE_RE = re.compile(
    r"(github\.com/)[^\s/]+(/tech-rebalance-dashboard(?:\.git)?)",
)


def fix_hardcoded_dashboard_owner(text: str) -> str:
    """把 workflow 裡兩處 hardcode 的 Dashboard repo owner 換成動態表達式。

    1. external_repository: itemhsu/tech-rebalance-dashboard
       → external_repository: ${{ github.repository_owner }}/tech-rebalance-dashboard

    2. github.com/itemhsu/tech-rebalance-dashboard.git（git clone URL）
       → github.com/${{ github.repository_owner }}/tech-rebalance-dashboard.git
    """
    text = _HARDCODED_DASH_RE.sub(
        r"\g<1>${{ github.repository_owner }}/tech-rebalance-dashboard",
        text,
    )
    text = _HARDCODED_CLONE_RE.sub(
        r"\g<1>${{ github.repository_owner }}\g<2>",
        text,
    )
    return text


def migrate_to_git_install(text: str, version: str) -> Optional[str]:
    """把 workflow 裡的引擎安裝方式遷移到 git+ 公開引擎。
    同時修正 hardcode 的 Dashboard repo owner（fix_hardcoded_dashboard_owner）。

    三種情況：
      1. 已有 git+ pin → 只 bump 版本，回傳新文字
      2. 有 pip install -r requirements.txt → 替換成 git+ 安裝，回傳新文字
      3. 兩者皆無 → 回 None（呼叫方顯示警告）
    """
    if _GIT_PIN_RE.search(text):
        result = bump_git_version(text, version)
    elif _REQ_RE.search(text):
        new_install = _PUB_INSTALL.format(version=version)
        result = _REQ_RE.sub(lambda m: m.group(1) + new_install, text)
    else:
        return None
    return fix_hardcoded_dashboard_owner(result)
