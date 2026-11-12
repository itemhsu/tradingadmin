"""admin_gui/services/env_fix.py — 修正 GUI App 的 PATH。

macOS 從 Finder/DMG 啟動的 App（Windows 則補 GitHub CLI 安裝目錄、隱藏子程序主控台） 不會繼承 shell 的 PATH（只有
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

# Windows：gh 官方 MSI / winget / scoop 預設安裝位置
_WIN_EXTRA_DIRS = [
    os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "GitHub CLI"),
    os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), "GitHub CLI"),
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "GitHub CLI"),
    os.path.join(os.path.expanduser("~"), "scoop", "shims"),
]


def hide_subprocess_console() -> bool:
    """Windows GUI App（console=False）每次 subprocess 呼叫 gh 都會閃一個黑色主控台。
    全域把 Popen 預設 creationflags 加上 CREATE_NO_WINDOW（所有 subprocess.run 都經過 Popen）。
    非 Windows 不動。回傳是否有套用。"""
    if os.name != "nt":
        return False
    flag = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    orig = subprocess.Popen.__init__
    if getattr(orig, "_ta_no_window", False):
        return True

    def _init(self, *args, **kwargs):
        kwargs["creationflags"] = kwargs.get("creationflags", 0) | flag
        orig(self, *args, **kwargs)

    _init._ta_no_window = True  # type: ignore[attr-defined]
    subprocess.Popen.__init__ = _init  # type: ignore[method-assign]
    return True


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


def _merge(dirs) -> None:
    current = [p for p in os.environ.get("PATH", "").split(os.pathsep) if p]
    seen = set(current)
    additions = [d for d in dirs if d and d not in seen and os.path.isdir(d)]
    if additions:
        os.environ["PATH"] = os.pathsep.join(additions + current)


def ensure_path() -> str:
    """把缺少的常見 bin 目錄補進 PATH。

    啟動效能關鍵：先加 _EXTRA_DIRS（Homebrew 等，瞬間、無子程序）。若這樣已找得到
    gh（絕大多數情況）→ 直接返回，**不跑**會載入整個 shell profile 的登入 shell 探測
    （`shell -lic …`，常達數秒，正是「啟動空白」的元兇）。只有仍找不到 gh 才做慢探測。
    """
    import shutil
    if os.name == "nt":
        hide_subprocess_console()
        _merge(_WIN_EXTRA_DIRS)
        return os.environ["PATH"]      # Windows 無登入 shell 可探測
    _merge(_EXTRA_DIRS)
    if not shutil.which("gh"):
        _merge(_login_shell_paths())     # 後援：找不到 gh 才付出慢探測成本
    return os.environ["PATH"]
