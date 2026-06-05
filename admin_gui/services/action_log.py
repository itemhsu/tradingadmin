"""admin_gui/services/action_log.py — 統一動作日誌（杜絕安靜失敗）。

每個按鈕用 `with LOG.action("名稱") as a:` 包起來：
  - 自動記 start / end（end 依步驟結果標 ok/問題）
  - 例外 → 記 fail + traceback 後「重新拋出」（不私吞）
  - a.step(name, status, detail) 記每個內部步驟

寫入 ~/.tradingadmin/action_log.jsonl（持久），供「📧 發送 log」附帶。
"""
from __future__ import annotations

import json
import re
import traceback
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, List, Optional
from uuid import uuid4

_DEFAULT = Path.home() / ".tradingadmin" / "action_log.jsonl"

_PROBLEM = {"fail", "warn", "skip"}
_MAX_LINES = 5000          # 超限自動 rotate，保留尾段
_KEEP_LINES = 2000


def env_snapshot(repo_slug: str = "") -> str:
    """每個 action 開頭的環境快照（app/os/gh/repo/pin）—— 讓每次操作自帶環境。"""
    import platform
    try:
        from admin_gui import __version__ as app_ver
    except Exception:   # noqa: BLE001
        app_ver = "?"
    try:
        from admin_gui.services import probes
        login = probes.gh_login() or "?"
    except Exception:   # noqa: BLE001
        login = "?"
    return (f"app={app_ver} os={platform.platform(terse=True)} "
            f"gh_login={login} repo={repo_slug or '?'}")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ── 金鑰遮罩（寄送 log 前用）────────────────────────────────────────────────
_MASK_PATTERNS = [
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),         # GitHub token
    re.compile(r"\b[A-Z0-9]{20,}\b"),                      # 疑似 API key（全大寫數字長串）
    re.compile(r"(?i)(secret|password|token|api[_-]?key)\s*[:=]\s*\S+"),
]


def mask_secrets(text: str) -> str:
    """把疑似金鑰/token 換成 ***（寄 log 前必過）。"""
    out = text
    for pat in _MASK_PATTERNS:
        out = pat.sub(lambda m: (m.group(0).split(":")[0].split("=")[0] + "=***")
                      if (":" in m.group(0) or "=" in m.group(0)) else "***", out)
    return out


def half_mask(value: Optional[str], keep: int = 3) -> str:
    """半遮罩：露頭尾各 keep 碼 + 長度，中間遮掉。供 log 除錯比對用。

    目的：保留足夠線索（前綴/後綴/長度）診斷「值是否被存對」，又不洩完整 secret。
    例：'re_M3pbFEvZ_KgLq5xSGxmtwaMJj7sr43JUZ' → 're_…JUZ(len=36)'
        '-'（致命 bug 的值）                    → '…(len=1)'  ← 一眼看出長度異常
    刻意不用 '=' 連接（避免被 mask_secrets 二次蓋成 ***）。
    """
    s = value or ""
    n = len(s)
    if n == 0:
        return "(空)"
    if n <= keep * 2:
        return f"…(len={n})"          # 太短：只露長度，不洩短 secret 全文
    return f"{s[:keep]}…{s[-keep:]}(len={n})"


@dataclass
class Step:
    name: str
    status: str = "ok"          # ok | fail | warn | skip
    detail: str = ""


@dataclass
class _ActionScope:
    log: "ActionLog"
    aid: str
    name: str
    steps: List[Step] = field(default_factory=list)
    _failed: bool = False

    def step(self, name: str, status: str = "ok", detail: str = "") -> None:
        self.steps.append(Step(name, status, detail[:300]))
        self.log._emit({"ts": _now(), "aid": self.aid, "kind": "step",
                        "name": name, "status": status, "detail": detail[:300]})

    def has_problem(self) -> bool:
        return self._failed or any(s.status in _PROBLEM for s in self.steps)

    def problems(self) -> List[Step]:
        return [s for s in self.steps if s.status in _PROBLEM]

    def summary(self) -> str:
        if not self.has_problem():
            return f"{len(self.steps)} 步全部成功"
        ps = self.problems()
        return f"{len(ps)}/{len(self.steps)} 步有問題"


class ActionLog:
    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = Path(path) if path else _DEFAULT
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._listeners: List[Callable[[dict], None]] = []
        self._current: Optional["_ActionScope"] = None   # 進行中的 action

    def note(self, name: str, status: str = "ok", detail: str = "") -> None:
        """供 action 範圍外（或底層 gh/http）記一筆。有進行中的 action → 併入其步驟。"""
        if self._current is not None:
            self._current.step(name, status, detail)
        else:
            self._emit({"ts": _now(), "aid": "-", "kind": "note",
                        "name": name, "status": status, "detail": detail[:300]})

    def subscribe(self, fn: Callable[[dict], None]) -> None:
        """日誌分頁可訂閱即時更新。"""
        self._listeners.append(fn)

    def _emit(self, record: dict) -> None:
        try:
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception:   # noqa: BLE001  寫檔失敗也不能讓動作崩
            pass
        for fn in list(self._listeners):
            try:
                fn(record)
            except Exception:   # noqa: BLE001
                pass

    def clear(self) -> int:
        """清空 action_log.jsonl，回清掉的行數。只動本機檔，不碰 GitHub。"""
        n = 0
        try:
            if self.path.exists():
                n = sum(1 for _ in self.path.open("r", encoding="utf-8"))
                self.path.write_text("", encoding="utf-8")
        except Exception:   # noqa: BLE001
            pass
        return n

    def _rotate_if_needed(self) -> None:
        try:
            if not self.path.exists():
                return
            lines = self.path.read_text(encoding="utf-8").splitlines()
            if len(lines) > _MAX_LINES:
                self.path.write_text("\n".join(lines[-_KEEP_LINES:]) + "\n", encoding="utf-8")
        except Exception:   # noqa: BLE001
            pass

    @contextmanager
    def action(self, name: str, ctx: str = ""):
        self._rotate_if_needed()
        aid = uuid4().hex[:8]
        self._emit({"ts": _now(), "aid": aid, "kind": "start", "action": name, "ctx": ctx})
        scope = _ActionScope(self, aid, name)
        prev = self._current
        self._current = scope
        # R7：每個 action 第一筆必為 env 快照
        scope.step("env", "ok", env_snapshot(ctx))
        try:
            yield scope
        except Exception as e:   # noqa: BLE001  例外＝大聲記，不私吞
            scope._failed = True
            self._emit({"ts": _now(), "aid": aid, "kind": "fail", "action": name,
                        "error": repr(e)[:300], "trace": traceback.format_exc()[-1500:]})
            raise
        finally:
            self._current = prev
            self._emit({"ts": _now(), "aid": aid, "kind": "end", "action": name,
                        "ok": not scope.has_problem(), "summary": scope.summary()})

    def tail(self, n: int = 500) -> List[dict]:
        if not self.path.exists():
            return []
        lines = self.path.read_text(encoding="utf-8").splitlines()
        out = []
        for line in lines[-n:]:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out

    def tail_text(self, n: int = 500) -> str:
        """純文字版（給 email / 顯示用）。輸出前一律過遮罩，不外洩 secret 明碼。"""
        rows = []
        for r in self.tail(n):
            kind = r.get("kind", "")
            if kind == "start":
                rows.append(f"\n▶ {r.get('ts','')} [{r.get('aid','')}] {r.get('action','')}  {r.get('ctx','')}")
            elif kind == "step":
                rows.append(f"   · {r.get('name','')}: {r.get('status','')}  {r.get('detail','')}")
            elif kind == "fail":
                rows.append(f"   ✗ FAIL {r.get('error','')}\n{r.get('trace','')}")
            elif kind == "end":
                mark = "✅" if r.get("ok") else "⚠"
                rows.append(f"   {mark} {r.get('summary','')}")
        return mask_secrets("\n".join(rows))


# 單例
LOG = ActionLog()
