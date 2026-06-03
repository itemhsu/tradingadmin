"""admin_gui/services/compat.py — App ↔ 引擎 schema 版本相容檢查。

桌面 App 永遠是 itemhsu 最新版，但讀的是「使用者 fork」的引擎輸出；兩者版本可能錯位。
此模組提供純函式版本檢查，供 UI 在偵測到落差時顯示警告（fork 相容性計劃 §6.1 ⑨）。

對應引擎端常數：engine/data_writer.py 的 SCHEMA_VERSION、mvp_dashboard.html 的
SUPPORTED_SCHEMA_VERSION。三者須一致；本 App 支援集合在此宣告。
"""
from __future__ import annotations

from typing import Optional

# 本 App 支援的 data.json schema 版本（引擎 data_writer.SCHEMA_VERSION 的相容集合）
GUI_SUPPORTED_DATA_SCHEMA = {"1.0"}


def data_schema_warning(version: Optional[str]) -> Optional[str]:
    """回傳警告字串；None＝相容。

    version 取自引擎產出的 data.json 的 meta.schema_version。
    """
    if version is None or version == "":
        return None  # 無版本資訊（舊樣本/尚未產生）→ 不警告，交給其他流程
    if version in GUI_SUPPORTED_DATA_SCHEMA:
        return None
    supported = ", ".join(sorted(GUI_SUPPORTED_DATA_SCHEMA))
    return (f"⚠️ 引擎報告格式版本為 {version}，本 App 支援 {supported}。"
            "請更新 App（下載最新 DMG）或從上游同步引擎。")
