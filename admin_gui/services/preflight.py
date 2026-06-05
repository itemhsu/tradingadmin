"""admin_gui/services/preflight.py — 呼叫外部前的「資源就緒檢查」。

原則（R8）：任何外部呼叫前，先檢查它依賴的每一個資源並記下就緒狀態；
缺資源 → 記成失敗原因並中止，不盲目觸發遠端再拿一個模糊錯誤。

每個 Resource 是一個 (label, check) ——check 回 (ok: bool, detail: str)。
preflight() 對每項呼叫 logger.step()，全 ok 回 True，任一缺回 False。
gh 介面可注入測試。
"""
from __future__ import annotations

import json
from typing import Callable, List, Tuple


def _default_gh(args, inp=None):
    import subprocess
    try:
        r = subprocess.run(["gh", *args], capture_output=True, text=True,
                           input=inp, timeout=30)
        return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()
    except Exception as e:  # noqa: BLE001
        return 1, "", str(e)


class Resource:
    def __init__(self, label: str, check: Callable[[Callable], Tuple[bool, str]]):
        self.label = label
        self._check = check

    def check(self, gh) -> Tuple[bool, str]:
        try:
            return self._check(gh)
        except Exception as e:  # noqa: BLE001  檢查本身失敗也記、不靜默
            return False, f"檢查例外 {type(e).__name__}: {str(e)[:120]}"


# ── 各種資源 ──────────────────────────────────────────────────────────────
def Secret(name: str, repo: str) -> Resource:
    """repo 是否有名為 name 的 secret（不取值）。"""
    def chk(gh):
        c, out, err = gh(["secret", "list", "--repo", repo])
        if c != 0:
            return False, f"讀不到 secret 清單 rc={c} {err[:120]}"
        names = {ln.split()[0] for ln in out.splitlines() if ln.strip()}
        return (name in names), ("present" if name in names else "MISSING")
    return Resource(f"secret {name}", chk)


def WorkflowFile(name: str, repo: str) -> Resource:
    """repo 預設分支是否有 .github/workflows/{name}。"""
    def chk(gh):
        c, _, err = gh(["api", f"repos/{repo}/contents/.github/workflows/{name}",
                        "--jq", ".name"])
        return (c == 0), ("present" if c == 0 else f"missing（{err[:100]}）")
    return Resource(f"workflow {name}", chk)


def RepoExists(repo: str) -> Resource:
    def chk(gh):
        c, _, err = gh(["api", f"repos/{repo}", "--jq", ".full_name"])
        return (c == 0), ("存在" if c == 0 else f"404/無權限（{err[:100]}）")
    return Resource(f"repo {repo}", chk)


def GhAuth() -> Resource:
    def chk(gh):
        c, out, err = gh(["api", "user", "--jq", ".login"])
        return (c == 0 and bool(out)), (f"已登入 {out}" if c == 0 and out
                                        else f"未登入/失敗（{err[:80]}）")
    return Resource("gh auth", chk)


def ConfigValue(key: str, value: str) -> Resource:
    def chk(_gh):
        return (bool(value), "有值" if value else "空")
    return Resource(f"config {key}", chk)


def EngineVersion(list_versions: Callable[[], List[str]]) -> Resource:
    def chk(_gh):
        vs = list_versions()
        return (bool(vs), (vs[0] if vs else "列不到 pub release"))
    return Resource("engine version", chk)


# ── 主函式 ────────────────────────────────────────────────────────────────
def preflight(logger, requires: List[Resource], *, gh: Callable = _default_gh) -> bool:
    """對 requires 逐項檢查並 logger.step()。全 ok 回 True；任一缺回 False。
    logger 須有 .step(name, status, detail)（_ActionScope）。"""
    all_ok = True
    missing = []
    for res in requires:
        ok, detail = res.check(gh)
        logger.step(f"preflight {res.label}", "ok" if ok else "fail", detail)
        if not ok:
            all_ok = False
            missing.append(res.label)
    if not all_ok:
        logger.step("preflight 結論", "fail", f"缺：{', '.join(missing)} → 中止，不呼叫外部")
    return all_ok
