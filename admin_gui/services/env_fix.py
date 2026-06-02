"""admin_gui/services/env_fix.py — 修正 GUI App 的 PATH。

macOS 從 Finder/DMG 啟動的 App 不會繼承 shell 的 PATH（只有
/usr/bin:/bin:/usr/sbin:/sbin），導致找不到用 Homebrew 安裝的 `gh`。
啟動時呼叫 ensure_path() 把常見安裝路徑與登入 shell 的 PATH 補進來。
"""
from __future__ import annotations

import os
import subprocess

# 常見 CLI 安裝位置（Apple Silicon / Intel Homebrew、MacPorts、使用者本地）
_EXTRA_DIRS = [
    "/opt/homebrew/bin",
    "/opt/homebrew/sbin",
    "/usr/local/bin",
    "/usr/local/sbin",
    "/opt/local/bin",
    os.path.join(os.path.expanduser("~"), ".local", "bin"),
    "/usr/bin", "/bin", "/usr/sbin", "/sbin",
]


def _login_shell_paths() -> list[str]:
    """問使用者的登入 shell 取得真正的 PATH（涵蓋非標準安裝）。"""
    shell = os.environ.get("SHELL")
    if not shell:
        return []
    try:
        r = subprocess.run([shell, "-lic", "echo __PATH__:$PATH"],
                           capture_output=True, text=True, timeout=6)
        if r.returncode != 0:
            return []
        for line in r.stdout.splitlines():
            if line.startswith("__PATH__:"):
                return [p for p in line[len("__PATH__:"):].split(os.pathsep) if p]
    except Exception:  # noqa: BLE001
        pass
    return []


def ensure_path() -> str:
    """把缺少的常見 bin 目錄補進 os.environ['PATH']（去重、保序）。回傳新 PATH。"""
    current = [p for p in os.environ.get("PATH", "").split(os.pathsep) if p]
    seen = set(current)
    additions = []
    for d in _login_shell_paths() + _EXTRA_DIRS:
        if d and d not in seen and os.path.isdir(d):
            additions.append(d)
            seen.add(d)
    if additions:
        # 補的路徑放前面，確保 gh 等工具找得到
        os.environ["PATH"] = os.pathsep.join(additions + current)
    return os.environ["PATH"]
