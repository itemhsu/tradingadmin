"""manifest 驅動 sync 測試（C-13~C-15, C-22, C-23）。gh / http 全 mock。"""
import json

from admin_gui.services import repo_sync as rs


_MANIFEST = {
    "version": "1",
    "repo_b": [
        {"path": ".github/workflows/daily.yml",      "policy": "render", "src": "templates/daily.yml"},
        {"path": ".github/workflows/test_email.yml", "policy": "render", "src": "templates/test_email.yml"},
        {"path": "accounts.json",                    "policy": "protected"},
        {"path": "data/.gitkeep",                    "policy": "placeholder"},
    ],
    "dashboard": [],
}


def _gh_factory(existing: set, calls: list):
    """fake gh：existing 內的 path 視為已存在；記錄所有 PUT。"""
    def gh(args, inp=None, **k):
        joined = " ".join(args)
        if "--jq" in args and ".sha" in args and "PUT" not in args:
            # 找出 path
            for p in existing:
                if f"contents/{p} " in joined or joined.endswith(f"contents/{p}"):
                    return (0, "deadbeef", "")
            return (1, "", "404")
        if "PUT" in args:
            calls.append((joined, inp))
            return (0, "", "")
        return (0, "", "")
    return gh


def _http(src_map):
    return lambda url: next((v for k, v in src_map.items() if url.endswith(k)), None)


# ── C-14：render 覆蓋、protected 不碰 ────────────────────────────────────────
def test_render_overwrites_protected_skipped():
    calls = []
    gh = _gh_factory(existing={"accounts.json"}, calls=calls)
    http = _http({"templates/daily.yml": "pin {version}",
                  "templates/test_email.yml": "email {version}"})
    actions = rs.sync("repo_b", "u/r", "v1.0.6", gh=gh, http_get=http, manifest=_MANIFEST)

    assert actions[".github/workflows/daily.yml"] == "rendered"
    assert actions["accounts.json"] == "protected"          # 不碰
    # daily.yml 被 PUT，內容代入版本
    put_paths = [c for c, _ in calls]
    assert any("daily.yml" in p for p in put_paths)
    assert not any("accounts.json" in p for p in put_paths)  # protected 無 PUT
    body = json.loads([inp for c, inp in calls if "daily.yml" in c][0])
    import base64
    assert base64.b64decode(body["content"]).decode() == "pin v1.0.6"


# ── C-15：placeholder 缺才建、已存在不動 ─────────────────────────────────────
def test_placeholder_created_when_missing_kept_when_present():
    calls = []
    gh = _gh_factory(existing=set(), calls=calls)                 # data/.gitkeep 不存在
    http = _http({"templates/daily.yml": "x", "templates/test_email.yml": "y"})
    actions = rs.sync("repo_b", "u/r", "v1", gh=gh, http_get=http, manifest=_MANIFEST)
    assert actions["data/.gitkeep"] == "created"

    calls2 = []
    gh2 = _gh_factory(existing={"data/.gitkeep"}, calls=calls2)   # 已存在
    actions2 = rs.sync("repo_b", "u/r", "v1", gh=gh2, http_get=http, manifest=_MANIFEST)
    assert actions2["data/.gitkeep"] == "kept"
    assert not any(".gitkeep" in c for c, _ in calls2)            # 不覆蓋


# ── C-06/E-06：test_email.yml 一定被 render（補推） ──────────────────────────
def test_test_email_always_rendered():
    calls = []
    gh = _gh_factory(existing=set(), calls=calls)
    http = _http({"templates/daily.yml": "d", "templates/test_email.yml": "TEST {version}"})
    actions = rs.sync("repo_b", "u/r", "v1.0.6", gh=gh, http_get=http, manifest=_MANIFEST)
    assert actions[".github/workflows/test_email.yml"] == "rendered"


# ── C-22：manifest 缺失/不合法 → fallback ────────────────────────────────────
def test_fetch_manifest_fallback_when_missing():
    m = rs.fetch_manifest(http_get=lambda url: None)             # 抓不到
    assert m is rs._FALLBACK_MANIFEST


def test_fetch_manifest_fallback_when_invalid():
    bad = json.dumps({"repo_b": [{"path": "x", "policy": "WRONG"}], "dashboard": []})
    m = rs.fetch_manifest(http_get=lambda url: bad)
    assert m is rs._FALLBACK_MANIFEST                            # 不合 schema → fallback


def test_fetch_manifest_accepts_valid():
    good = json.dumps(_MANIFEST)
    m = rs.fetch_manifest(http_get=lambda url: good)
    assert m["version"] == "1" and len(m["repo_b"]) == 4


# ── C-23：未知 policy 安全跳過（新檔忘了維護不當機）─────────────────────────
def test_unknown_policy_skipped_safely():
    mani = {"repo_b": [{"path": "future.txt", "policy": "render", "src": "templates/daily.yml"},
                       {"path": "weird", "policy": "render", "src": "templates/daily.yml"}],
            "dashboard": []}
    # 用合法 manifest 但塞一個 policy 之外的值 → _looks_valid 會擋；這裡直接傳 manifest 繞過
    mani["repo_b"][1]["policy"] = "bogus"
    calls = []
    gh = _gh_factory(existing=set(), calls=calls)
    http = _http({"templates/daily.yml": "x"})
    actions = rs.sync("repo_b", "u/r", "v1", gh=gh, http_get=http, manifest=mani)
    assert actions["weird"] == "skip-unknown-policy"            # 不炸


def test_fetch_via_gh_not_urllib():
    """回歸：template/manifest 抓取走 gh api（App 內穩定），不靠 urllib。"""
    import base64 as _b64
    seen = []
    def gh(args, inp=None, **k):
        j = " ".join(args)
        seen.append(j)
        if "tech-rebalance-pub/contents/repo_template.json" in j:
            return (0, _b64.b64encode(json.dumps(_MANIFEST).encode()).decode(), "")
        if "tech-rebalance-pub/contents/templates/" in j:
            return (0, _b64.b64encode(b"pin {version}").decode(), "")
        if ".sha" in j and "PUT" not in args:
            return (1, "", "404")
        return (0, "", "")
    actions = rs.sync("repo_b", "u/r", "v1.0.6", gh=gh)   # 不傳 http_get → 走 gh
    assert actions[".github/workflows/test_email.yml"] == "rendered"
    # 確認真的有經 gh api 抓 pub engine 的 template
    assert any("tech-rebalance-pub/contents/templates/test_email.yml" in s for s in seen)
