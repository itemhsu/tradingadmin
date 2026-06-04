"""admin_gui/services/mode_detect.py — 偵測 repo 是 fork 還是 repo_b（兩 repo GUI G5）。

向後相容關鍵：舊系統（fork 模式，含引擎碼）顯示舊 UI；新薄殼（repo_b，引擎以 git+
從公開 repo 安裝）顯示新 UI。二者並存、互不影響。store 為 repo_store 介面（可注入測試）。
"""
from __future__ import annotations

FORK = "fork"
REPO_B = "repo_b"
UNKNOWN = "unknown"


def detect_mode(store) -> str:
    """判斷 repo 模式（向後相容核心）。

    repo_b（薄殼，引擎在外）任一成立即是：
      - daily.yml 用 git+ 安裝公開引擎（含 'tech-rebalance-pub@'）── 新版
      - 有 vendor/*.whl ── 舊版 vendored wheel 薄殼
      - 有 accounts.json 但「無」runner.py（引擎碼不在 repo 內）
    fork（含引擎碼）：有 runner.py。
    皆無 → unknown（精靈全顯）。
    """
    # 新版薄殼：daily.yml 以 git+ 釘公開引擎
    try:
        daily = store.read_text_or_none(".github/workflows/daily.yml")
    except Exception:  # noqa: BLE001（含 store 無此方法 / 網路錯誤）
        daily = None
    if daily and "tech-rebalance-pub@" in daily:
        return REPO_B
    # 舊版薄殼：vendored wheel
    try:
        vendor = store.list_dir("vendor")
    except Exception:  # noqa: BLE001
        vendor = []
    if any(str(n).endswith(".whl") for n in vendor):
        return REPO_B
    # 有引擎碼 → fork
    try:
        if store.exists("runner.py"):
            return FORK
    except Exception:  # noqa: BLE001
        pass
    # 無引擎碼但有設定檔 → 薄殼
    try:
        if store.exists("accounts.json"):
            return REPO_B
    except Exception:  # noqa: BLE001
        pass
    return UNKNOWN
