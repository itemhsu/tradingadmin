"""admin_gui/services/mode_detect.py — 偵測 repo 是 fork 還是 repo_b（兩 repo GUI G5）。

向後相容關鍵：舊系統（fork 模式，含引擎碼）顯示舊 UI；新薄殼（repo_b，含 vendored
wheel）顯示新 UI。二者並存、互不影響。store 為 repo_store 介面（可注入測試）。
"""
from __future__ import annotations

FORK = "fork"
REPO_B = "repo_b"
UNKNOWN = "unknown"


def detect_mode(store) -> str:
    """repo_b：有 vendor/*.whl；fork：有 runner.py（引擎碼）。皆無 → unknown。"""
    try:
        vendor = store.list_dir("vendor")
    except Exception:  # noqa: BLE001
        vendor = []
    if any(str(n).endswith(".whl") for n in vendor):
        return REPO_B
    try:
        if store.exists("runner.py"):
            return FORK
    except Exception:  # noqa: BLE001
        pass
    return UNKNOWN
