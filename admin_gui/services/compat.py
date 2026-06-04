"""admin_gui/services/compat.py — App ↔ 引擎 schema 版本相容檢查。

桌面 App 永遠是 itemhsu 最新版，但讀的是「使用者 fork」的引擎輸出；兩者版本可能錯位。
此模組提供純函式版本檢查，供 UI 在偵測到落差時顯示警告（fork 相容性計劃 §6.1 ⑨）。

對應引擎端常數：engine/data_writer.py 的 SCHEMA_VERSION、mvp_dashboard.html 的
SUPPORTED_SCHEMA_VERSION。三者須一致；本 App 支援集合在此宣告。
"""
from __future__ import annotations

import re
from typing import List, Optional, Set

# 本 App 支援的 data.json schema 版本（引擎 data_writer.SCHEMA_VERSION 的相容集合）
GUI_SUPPORTED_DATA_SCHEMA = {"1.0"}

# 本 App 支援的 data-schema 主版本（對應引擎 schemas/data-schema-v{N}.json）
GUI_SUPPORTED_DATA_SCHEMA_MAJORS: Set[int] = {1}

# 本 App 支援的引擎主版本（兩 repo 模式：vendor wheel 的版本）
GUI_SUPPORTED_ENGINE_MAJORS: Set[int] = {1}

_DATA_SCHEMA_RE = re.compile(r"^data-schema-v(\d+)\.json$")
_WHEEL_RE = re.compile(r"tech_rebalance-(\d+)\.(\d+)\.(\d+)-py3-none-any\.whl")


def parse_data_schema_majors(filenames: List[str]) -> Set[int]:
    """從 schemas/ 目錄檔名取出 data-schema 的主版本集合。"""
    out: Set[int] = set()
    for name in filenames or []:
        m = _DATA_SCHEMA_RE.match(name.strip())
        if m:
            out.add(int(m.group(1)))
    return out


def schema_drift_warning(schema_filenames: List[str]) -> Optional[str]:
    """比對「fork 引擎的 data-schema 主版本」與本 App 支援範圍，回傳警告或 None。

    schema_filenames：fork repo `schemas/` 目錄的檔名清單（GUI 經 API 取得）。
    """
    majors = parse_data_schema_majors(schema_filenames)
    if not majors:
        return None                                   # 讀不到→不警告，交其他流程
    engine_major = max(majors)
    hi, lo = max(GUI_SUPPORTED_DATA_SCHEMA_MAJORS), min(GUI_SUPPORTED_DATA_SCHEMA_MAJORS)
    if engine_major > hi:
        return (f"引擎的報告格式為 v{engine_major}，比本 App 支援的 v{hi} 新。"
                "請下載最新版 App（DMG）以正確顯示。")
    if engine_major < lo:
        return (f"引擎的報告格式為 v{engine_major}，比本 App 支援的 v{lo} 舊。"
                "建議從上游同步引擎（scripts/sync_upstream.sh）。")
    return None


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


# ── 兩 repo 模式：引擎版本漂移（讀 vendor wheel）─────────────────────────────
def engine_version_from_vendor(vendor_filenames: List[str]) -> Optional[str]:
    """從 vendor/ 的 wheel 檔名解析引擎版本（如 1.0.4）。"""
    for name in vendor_filenames or []:
        m = _WHEEL_RE.search(name.strip())
        if m:
            return f"{m.group(1)}.{m.group(2)}.{m.group(3)}"
    return None


def engine_drift_warning(vendor_filenames: List[str]) -> Optional[str]:
    """vendor 引擎版本 vs App 支援主版本，回警告或 None。"""
    ver = engine_version_from_vendor(vendor_filenames)
    if not ver:
        return None                       # 讀不到（非 repo_b 或缺 wheel）→ 不警告
    major = int(ver.split(".")[0])
    hi, lo = max(GUI_SUPPORTED_ENGINE_MAJORS), min(GUI_SUPPORTED_ENGINE_MAJORS)
    if major > hi:
        return (f"引擎版本 {ver} 比本 App 支援的 v{hi} 新。"
                "請下載最新版 App（DMG）以正確顯示。")
    if major < lo:
        return (f"引擎版本 {ver} 比本 App 支援的 v{lo} 舊。"
                "建議在精靈用「更新引擎版本」升級。")
    return None
