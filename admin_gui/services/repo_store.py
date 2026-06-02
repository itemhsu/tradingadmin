"""admin_gui/services/repo_store.py — repo 檔案存取抽象（不需 clone）。

兩種後端：
  - GhContentsStore：透過 `gh api repos/{slug}/contents/{path}` 直接讀寫 GitHub
    上的檔案。不下載任何代碼，只動 accounts.json / workflow yml / data 等少數檔。
  - LocalStore：本機檔案系統（給單元測試與離線用，行為與舊版一致）。

介面（兩者一致）：
  read_text(path)            → str（缺檔丟 FileNotFoundError）
  read_text_or_none(path)    → Optional[str]
  read_json(path)            → dict（缺檔/壞檔回 {}）
  exists(path)               → bool
  list_dir(path)             → List[str]（basename，缺目錄回 []）
  write_text(path, text, message) → str（回人類可讀結果；遠端＝直接 commit）

路徑一律用 repo 內的相對 POSIX 路徑（如 "accounts.json"、
".github/workflows/x.yml"、"data/3/portfolio_state.json"）。
"""
from __future__ import annotations

import base64
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Callable, List, Optional


class StoreError(Exception):
    pass


# ── 本機檔案系統 ─────────────────────────────────────────────────────────
class LocalStore:
    def __init__(self, root) -> None:
        self.root = Path(root)

    def _p(self, path: str) -> Path:
        return self.root / path

    def read_text(self, path: str) -> str:
        return self._p(path).read_text(encoding="utf-8")

    def read_text_or_none(self, path: str) -> Optional[str]:
        p = self._p(path)
        return p.read_text(encoding="utf-8") if p.exists() else None

    def read_json(self, path: str) -> dict:
        try:
            return json.loads(self.read_text(path))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return {}

    def exists(self, path: str) -> bool:
        return self._p(path).exists()

    def list_dir(self, path: str) -> List[str]:
        d = self._p(path)
        if not d.is_dir():
            return []
        return sorted(p.name for p in d.iterdir())

    def write_text(self, path: str, text: str, message: str = "") -> str:
        p = self._p(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(p.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(text)
            os.replace(tmp, p)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
        return f"已寫入本機 {path}"


# ── GitHub Contents API（不 clone）──────────────────────────────────────
class GhContentsStore:
    """用 gh CLI 打 GitHub Contents API；只動指定檔案，不下載 repo。"""

    def __init__(self, repo_slug: str, runner: Optional[Callable] = None,
                 branch: str = "") -> None:
        self.slug = repo_slug
        self.branch = branch
        self._run = runner or subprocess.run

    def _api(self, args: List[str], **kw):
        return self._run(["gh", "api", *args], capture_output=True, text=True, **kw)

    def _get_meta(self, path: str):
        """回 (content_text, sha)；缺檔回 (None, None)。"""
        ref = ["-f", f"ref={self.branch}"] if self.branch else []
        r = self._api([f"repos/{self.slug}/contents/{path}", *ref])
        if r.returncode != 0:
            if "404" in (r.stderr or "") or "Not Found" in (r.stderr or ""):
                return None, None
            raise StoreError(f"讀取 {path} 失敗：{(r.stderr or '')[:200]}")
        try:
            obj = json.loads(r.stdout or "{}")
        except json.JSONDecodeError:
            raise StoreError(f"{path} 回應非 JSON")
        if isinstance(obj, list):
            raise StoreError(f"{path} 是目錄，不是檔案")
        b64 = obj.get("content", "")
        text = base64.b64decode(b64).decode("utf-8") if b64 else ""
        return text, obj.get("sha")

    def read_text(self, path: str) -> str:
        text, _ = self._get_meta(path)
        if text is None:
            raise FileNotFoundError(path)
        return text

    def read_text_or_none(self, path: str) -> Optional[str]:
        text, _ = self._get_meta(path)
        return text

    def read_json(self, path: str) -> dict:
        try:
            text = self.read_text_or_none(path)
            return json.loads(text) if text else {}
        except (json.JSONDecodeError, StoreError):
            return {}

    def exists(self, path: str) -> bool:
        text, _ = self._get_meta(path)
        return text is not None

    def list_dir(self, path: str) -> List[str]:
        ref = ["-f", f"ref={self.branch}"] if self.branch else []
        r = self._api([f"repos/{self.slug}/contents/{path}", *ref])
        if r.returncode != 0:
            return []
        try:
            arr = json.loads(r.stdout or "[]")
        except json.JSONDecodeError:
            return []
        if not isinstance(arr, list):
            return []
        return sorted(item.get("name", "") for item in arr if item.get("name"))

    def write_text(self, path: str, text: str, message: str = "") -> str:
        """PUT 檔案內容＝直接在 GitHub 上 commit（需要時帶 sha 更新）。"""
        _, sha = self._get_meta(path)
        payload = {
            "message": message or f"chore(admin): update {path}",
            "content": base64.b64encode(text.encode("utf-8")).decode("ascii"),
        }
        if sha:
            payload["sha"] = sha
        if self.branch:
            payload["branch"] = self.branch
        r = self._api(["-X", "PUT", f"repos/{self.slug}/contents/{path}",
                       "--input", "-"], input=json.dumps(payload))
        if r.returncode != 0:
            raise StoreError(f"寫入 {path} 失敗：{(r.stderr or r.stdout)[:200]}")
        return f"已 commit 到 GitHub：{path}"


def make_store(repo_slug: Optional[str] = None, root=None, runner=None):
    """有 repo_slug → 用 GitHub API（不 clone）；否則用本機路徑。"""
    if repo_slug:
        return GhContentsStore(repo_slug, runner=runner)
    if root is not None:
        return LocalStore(root)
    raise StoreError("make_store 需要 repo_slug 或 root 其一")
