"""admin_gui/services/repo_sync.py — manifest 驅動的 Repo B / Dashboard 同步。

讀 pub engine 的 repo_template.json（單一事實來源），對每個檔套用其 policy：
  render      → 從 templates/ 取內容、代入 {version}、覆蓋（版本要更新）
  placeholder → 缺則建（種子內容）、已存在不動
  protected   → 永不建、永不碰（用戶私有資料）

build（建立）與 repair（修復/綠燈卡死解法）共用同一個 sync —— 冪等。
manifest 缺失或不合 schema → 退回內建 fallback（App 不當機）。

抓取一律經 gh api（contents），不用 urllib —— 打包成 DMG 的 App 裡 urllib 的
SSL 憑證常失敗，gh CLI 則穩定。純邏輯，gh / getter 可注入測試。
"""
from __future__ import annotations

import base64
import json
from typing import Callable, Dict, Optional

_PUB_REPO = "itemhsu/tech-rebalance-pub"

# GUI 內建 fallback（pub manifest 抓不到時用，確保必要檔仍能建）
_FALLBACK_MANIFEST: dict = {
    "version": "1",
    "repo_b": [
        {"path": ".github/workflows/daily.yml",      "policy": "render", "src": "templates/daily.yml"},
        {"path": ".github/workflows/test_email.yml", "policy": "render", "src": "templates/test_email.yml"},
        {"path": "accounts.json",                    "policy": "protected"},
        {"path": "data/.gitkeep",                    "policy": "placeholder"},
    ],
    "dashboard": [
        {"path": ".nojekyll",     "policy": "placeholder"},
        {"path": "index.html",    "policy": "placeholder"},
        {"path": "accounts.json", "policy": "placeholder"},
    ],
}

_VALID_POLICIES = {"render", "placeholder", "protected"}


def _gh_get_content(gh: Callable, path: str) -> Optional[str]:
    """經 gh api 取 pub engine 某檔內容（base64 解碼）；失敗回 None。"""
    c, b64, _ = gh(["api", f"repos/{_PUB_REPO}/contents/{path}", "--jq", ".content"])
    if c != 0 or not (b64 or "").strip():
        return None
    try:
        return base64.b64decode(b64.replace("\n", "")).decode("utf-8")
    except Exception:   # noqa: BLE001
        return None


def _looks_valid(m: dict) -> bool:
    """輕量 schema 檢查（GUI 防禦層）：結構對、policy 合法、render 有 src。"""
    if not isinstance(m, dict) or "repo_b" not in m or "dashboard" not in m:
        return False
    for section in ("repo_b", "dashboard"):
        entries = m.get(section)
        if not isinstance(entries, list):
            return False
        for e in entries:
            if not isinstance(e, dict) or "path" not in e or e.get("policy") not in _VALID_POLICIES:
                return False
            if e["policy"] == "render" and not e.get("src"):
                return False
    return True


def fetch_manifest(http_get: Callable[[str], Optional[str]]) -> dict:
    """抓 pub engine 的 repo_template.json；缺失/不合法 → fallback。
    http_get(path) → text|None（path 相對 pub engine 根目錄）。"""
    text = http_get("repo_template.json") if http_get else None
    if text:
        try:
            m = json.loads(text)
            if _looks_valid(m):
                return m
        except (ValueError, TypeError):
            pass
    return _FALLBACK_MANIFEST


def _seed(path: str) -> bytes:
    """placeholder 的種子內容。"""
    if path == ".nojekyll" or path.endswith("/.gitkeep"):
        return b""
    if path == "accounts.json":
        return b'{"accounts":[]}'
    if path == "index.html":
        return (b"<!DOCTYPE html><meta charset='utf-8'>"
                b"<p>Dashboard \xe5\x88\x9d\xe5\xa7\x8b\xe5\x8c\x96\xe4\xb8\xad\xe2\x80\xa6</p>")
    return b""


def sync(section: str, slug: str, version: str, *,
         gh: Callable, http_get: Optional[Callable[[str], Optional[str]]] = None,
         manifest: Optional[dict] = None,
         skip_paths: Optional[set] = None) -> Dict[str, str]:
    """對 slug 套用 manifest[section] 的所有 policy。回 {path: action}。

    gh(args, inp=None) → (code, out, err)，與 wizard._gh 同介面。
    http_get(path) 取 pub engine 檔內容；預設經 gh api（App 內穩定）。
    render 覆蓋、placeholder 缺才建、protected 跳過。
    skip_paths 內的 path 完全跳過（如：舊用戶已有別名 daily workflow，避免重複）。
    """
    get = http_get or (lambda path: _gh_get_content(gh, path))
    m = manifest or fetch_manifest(get)
    skip_paths = skip_paths or set()
    actions: Dict[str, str] = {}

    def _exists(path: str) -> bool:
        return gh(["api", f"repos/{slug}/contents/{path}", "--jq", ".sha"])[0] == 0

    def _put(path: str, content: bytes, msg: str) -> None:
        c, sha, _ = gh(["api", f"repos/{slug}/contents/{path}", "--jq", ".sha"])
        body = {"message": msg, "content": base64.b64encode(content).decode()}
        if c == 0 and sha.strip():
            body["sha"] = sha.strip()
        gh(["api", "-X", "PUT", f"repos/{slug}/contents/{path}", "--input", "-"],
           inp=json.dumps(body))

    for e in m.get(section, []):
        path, policy = e["path"], e["policy"]
        if path in skip_paths:
            actions[path] = "skipped"
            continue
        if policy == "render":
            tmpl = get(e["src"])
            if tmpl is None:
                actions[path] = "skip-no-template"
                continue
            _put(path, tmpl.replace("{version}", version).encode(), f"sync(render): {path} @ {version}")
            actions[path] = "rendered"
        elif policy == "placeholder":
            if _exists(path):
                actions[path] = "kept"
            else:
                _put(path, _seed(path), f"sync(placeholder): {path}")
                actions[path] = "created"
        elif policy == "protected":
            actions[path] = "protected"
        else:
            actions[path] = "skip-unknown-policy"   # 未知 policy → 安全跳過
    return actions
