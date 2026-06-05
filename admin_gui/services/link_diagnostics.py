"""admin_gui/services/link_diagnostics.py — 點擊外部連結前的相依檢查。

目標：「靠 log 就能除錯」。使用者按下 dashboard 等連結時，先用 HTTP 逐一檢查
該頁面依賴的檔案（accounts.json、{id}/index.json、{id}/data.json、頁面本身）
是否就緒（HTTP 200 / 404 / 權限），把結果寫進 action_log。如此 dashboard 的
「無法載入 1/data.json 404」這類問題會直接出現在 log，使用者不必回傳畫面截圖。
"""
from __future__ import annotations

import urllib.error
import urllib.parse
import urllib.request
from typing import Tuple


def http_status(url: str, timeout: int = 12) -> Tuple[int, str]:
    """GET 一個 URL，回 (status_code, 說明)。連不上回 (-1, 原因)。"""
    from admin_gui.services.probes import _ssl_ctx   # 共用 certifi SSL context
    try:
        req = urllib.request.Request(
            url, method="GET", headers={"User-Agent": "TradingAdmin-LinkCheck"})
        with urllib.request.urlopen(req, timeout=timeout, context=_ssl_ctx()) as resp:
            resp.read(256)                       # 讀一點點即可
            return getattr(resp, "status", 200) or 200, "OK"
    except urllib.error.HTTPError as e:
        return e.code, str(e.reason)
    except Exception as e:                        # noqa: BLE001
        return -1, f"{type(e).__name__}: {str(e)[:80]}"


def _status_word(code: int) -> str:
    return "ok" if code == 200 else "fail"


def diagnose_link(url: str, logger) -> None:
    """檢查 url 及其相依檔，逐項寫入 logger（_ActionScope）。

    - mvp_dashboard.html?a=N → 另查 accounts.json、N/index.json、N/data.json
    - 其他連結 → 只查頁面本身
    logger 需有 .step(name, status, detail)。
    """
    code, detail = http_status(url)
    logger.step("頁面 HTTP", _status_word(code), f"{code} {detail}  {url}")

    if "mvp_dashboard" not in url:
        return

    # 取 dashboard 目錄 base 與帳戶 id
    base = url.split("mvp_dashboard")[0]          # 例：https://x.github.io/tech-rebalance-dashboard/
    q = urllib.parse.urlparse(url).query
    acc = (urllib.parse.parse_qs(q).get("a") or ["1"])[0]

    deps = ["accounts.json", f"{acc}/index.json", f"{acc}/data.json"]
    missing = []
    for rel in deps:
        c, d = http_status(base + rel)
        logger.step(f"相依 {rel}", _status_word(c), f"{c} {d}")
        if c != 200:
            missing.append(f"{rel}({c})")

    if missing:
        # 把最可能的原因講白，讓 log 自帶結論
        hint = "；".join(missing)
        if any("data.json" in m or "index.json" in m for m in missing):
            logger.step("診斷結論", "warn",
                        f"帳戶資料未發佈到 dashboard：{hint}。"
                        "通常因每日 workflow 尚未把 mvp_data 推到 dashboard repo"
                        "（缺 migrate_to_mvp + PAGES_TOKEN 部署步驟，或尚未跑過正式（非 dry-run）執行）。")
        elif any("accounts.json" in m for m in missing):
            logger.step("診斷結論", "warn",
                        f"dashboard 的 accounts.json 異常：{hint}。"
                        "請在「帳戶」分頁新增/重存一個帳戶以同步。")
