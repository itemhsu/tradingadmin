"""兩 repo GUI 服務 G2：manifest / engine_release / workflow_runner / provisioner。

對應 GUI 計劃測試矩陣 A(PB) B(ER) C(WR) D(CAT)。外部 gh 全 mock。
"""
import base64
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from admin_gui.services import manifest as mf
from admin_gui.services import engine_release as er
from admin_gui.services import workflow_runner as wr
from admin_gui.services import repo_b_provisioner as pv


class R:
    def __init__(self, rc=0, out="", err=""):
        self.returncode = rc; self.stdout = out; self.stderr = err


_SAMPLE_MANIFEST = {
    "manifest_version": "1", "engine_version": "1.0.4", "data_schema": "1.0",
    "strategies": ["top10", "mom_6m_t20"],
    "brokers": {"alpaca": {"required_env": ["{PREFIX}_ALPACA_KEY", "{PREFIX}_ALPACA_SECRET"],
                           "environments": ["paper", "live"]}},
}


def _arg(args, flag):
    return args[args.index(flag) + 1] if flag in args else None


# ── D. manifest ──────────────────────────────────────────────────────────────
def test_parse_manifest():
    m = mf.parse_manifest(json.dumps(_SAMPLE_MANIFEST))
    assert m["engine_version"] == "1.0.4" and m["strategies"] == ["top10", "mom_6m_t20"]


def test_fetch_manifest_writes_and_parses(tmp_path):
    def runner(args, **k):
        d = _arg(args, "--dir")
        (Path(d) / "manifest.json").write_text(json.dumps(_SAMPLE_MANIFEST))
        return R(0)
    m = mf.fetch_manifest("v1.0.4", runner=runner, use_cache=False)
    assert m and m["engine_version"] == "1.0.4"


def test_fetch_manifest_failure_returns_none():
    assert mf.fetch_manifest("v9", runner=lambda *a, **k: R(1), use_cache=False) is None


def test_required_secrets_templating():
    assert mf.required_secrets(_SAMPLE_MANIFEST, "alpaca", "ACC1") == \
        ["ACC1_ALPACA_KEY", "ACC1_ALPACA_SECRET"]


def test_strategies_and_brokers():
    assert mf.strategies(_SAMPLE_MANIFEST) == ["top10", "mom_6m_t20"]
    assert mf.brokers(_SAMPLE_MANIFEST) == ["alpaca"]
    assert mf.broker_environments(_SAMPLE_MANIFEST, "alpaca") == ["paper", "live"]


# ── B. engine_release ────────────────────────────────────────────────────────
def test_list_versions():
    runner = lambda *a, **k: R(0, json.dumps([{"tagName": "v1.0.4"}, {"tagName": "v1.0.3"}]))
    assert er.list_versions(runner=runner) == ["v1.0.4", "v1.0.3"]


def test_wheel_name():
    assert er.wheel_name("v1.0.4") == "tech_rebalance-1.0.4-py3-none-any.whl"


def test_download_wheel(tmp_path):
    def runner(args, **k):
        d = _arg(args, "--dir")
        (Path(d) / "tech_rebalance-1.0.4-py3-none-any.whl").write_bytes(b"x")
        return R(0)
    assert er.download_wheel("v1.0.4", str(tmp_path), runner=runner) == \
        "tech_rebalance-1.0.4-py3-none-any.whl"


def test_pinned_version_and_bump():
    daily = "        run: pip install vendor/tech_rebalance-1.0.3-py3-none-any.whl\n"
    assert er.pinned_version(daily) == "1.0.3"
    bumped = er.bump_daily(daily, "v1.0.4")
    assert "tech_rebalance-1.0.4-py3-none-any.whl" in bumped
    assert "1.0.3" not in bumped


def test_pinned_git_version_and_bump():
    daily = ('      - name: Install engine (public repo, no token)\n'
             '        run: pip install "tech-rebalance @ '
             'git+https://github.com/itemhsu/tech-rebalance-pub@v1.0.5"\n')
    assert er.pinned_git_version(daily) == "v1.0.5"
    bumped = er.bump_git_version(daily, "v1.0.6")
    assert "tech-rebalance-pub@v1.0.6" in bumped
    assert "v1.0.5" not in bumped
    assert er.pinned_git_version(bumped) == "v1.0.6"


def test_list_versions_failure_empty():
    assert er.list_versions(runner=lambda *a, **k: R(1)) == []


# ── C. workflow_runner ───────────────────────────────────────────────────────
def test_run_workflow_dry_run():
    cap = {}
    def runner(args, **k): cap["args"] = args; return R(0)
    assert wr.run_workflow("u/r", dry_run=True, runner=runner) is True
    assert "dry_run=true" in cap["args"] and "force=false" in cap["args"]


def test_run_workflow_force():
    cap = {}
    wr.run_workflow("u/r", dry_run=False, force=True,
                    runner=lambda a, **k: cap.update(args=a) or R(0))
    assert "force=true" in cap["args"]


def test_live_force_requires_confirm():
    with pytest.raises(wr.LiveForceNotConfirmed):
        wr.run_workflow("u/r", force=True, environment="live", confirmed=False,
                        runner=lambda *a, **k: R(0))


def test_live_force_with_confirm_ok():
    assert wr.run_workflow("u/r", force=True, environment="live", confirmed=True,
                           runner=lambda *a, **k: R(0)) is True


def test_list_runs_and_view_log():
    assert wr.list_runs("u/r", runner=lambda *a, **k: R(0, '[{"databaseId":1}]')) == [{"databaseId": 1}]
    assert wr.view_log("u/r", 1, runner=lambda *a, **k: R(0, "LOG")) == "LOG"


# ── A. provisioner ───────────────────────────────────────────────────────────
def test_build_template_files_shape_and_safety():
    files = pv.build_template_files("v1.0.6")
    assert ".github/workflows/daily.yml" in files          # 巢狀路徑
    # 不再 vendor wheel：以 git+ 從公開 repo 安裝
    assert not any(p.startswith("vendor/") for p in files)
    daily = files[".github/workflows/daily.yml"].decode("utf-8")
    assert "git+https://github.com/itemhsu/tech-rebalance-pub@v1.0.6" in daily
    assert ".whl" not in daily                              # 無 wheel 安裝
    accts = json.loads(files["accounts.json"])
    assert accts["accounts"][0]["strategy"] == "top10"
    # 安全：任何檔案不得含金鑰樣字
    blob = b"\n".join(files.values()).decode("utf-8", "ignore")
    assert "ALPACA_KEY:" in blob and "secrets." in blob    # 只能是 secrets 參照
    assert "ALPACA_KEY=" not in blob                        # 不得有明文賦值


def test_provision_creates_repo_and_pushes_files():
    calls = []
    def runner(args, **k):
        calls.append(args)
        return R(0)
    files = {"accounts.json": b"{}", ".github/workflows/daily.yml": b"x",
             "vendor/w.whl": b"W"}
    res = pv.provision("u/myrepo", files, runner=runner)
    assert res["ok"] and res["created"]
    assert calls[0][:3] == ["gh", "repo", "create"] and "--private" in calls[0]
    # 每個檔都經 contents PUT
    puts = [c for c in calls if "PUT" in c]
    assert len(puts) == 3
    assert any("repos/u/myrepo/contents/.github/workflows/daily.yml" in c for c in puts)


def test_provision_repo_exists_continues():
    def runner(args, **k):
        if args[:3] == ["gh", "repo", "create"]:
            return R(1, err="Name already exists on this account")
        return R(0)
    res = pv.provision("u/r", {"a.json": b"{}"}, runner=runner)
    assert res["ok"]            # repo 已存在 → 繼續推檔，不算失敗


def test_provision_secrets_via_stdin_not_argv():
    """檔案內容經 --input -（stdin），不出現在 argv（避免外洩/超長）。"""
    seen = {}
    def runner(args, **k):
        if "PUT" in args:
            seen["has_input"] = "input" in k
            seen["content_in_argv"] = any("content" in str(a) and "=" in str(a) for a in args)
        return R(0)
    pv.provision("u/r", {"a.json": b"{}"}, runner=runner)
    assert seen["has_input"] is True and seen["content_in_argv"] is False
