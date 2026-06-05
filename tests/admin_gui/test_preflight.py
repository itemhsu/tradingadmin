"""前置資源檢查 preflight（L-21, L-22）。gh 全 mock。"""
from admin_gui.services import preflight as pf
from admin_gui.services import action_log as al


def _gh(secrets=(), repos=(), workflows=(), login="alice"):
    """fake gh：依參數回應 secret list / repo exists / workflow exists / user。"""
    def gh(args, inp=None, **k):
        j = " ".join(args)
        if args[:2] == ["secret", "list"]:
            return (0, "\n".join(f"{s}  2024-01-01" for s in secrets), "")
        if "/contents/.github/workflows/" in j:
            wf = j.split("/workflows/")[1].split(" ")[0]
            return (0, wf, "") if wf in workflows else (1, "", "404 Not Found")
        if j.endswith("--jq .full_name"):
            repo = j.split("repos/")[1].split(" ")[0]
            return (0, repo, "") if repo in repos else (1, "", "404")
        if "api user" in j:
            return (0, login, "") if login else (1, "", "not logged in")
        return (0, "", "")
    return gh


def _log(tmp_path):
    return al.ActionLog(path=tmp_path / "a.jsonl")


# ── L-21：preflight 抓到缺 secret → 回 False 並記 MISSING，不呼叫外部 ─────────
def test_l21_preflight_catches_missing_secret(tmp_path):
    LOG = _log(tmp_path)
    gh = _gh(secrets=["EMAIL_PASSWORD"], repos=["alice/r"],
             workflows=["test_email.yml"])     # 故意缺 EMAIL_SENDER
    with LOG.action("測試發信") as a:
        ready = pf.preflight(a, [
            pf.GhAuth(),
            pf.Secret("EMAIL_SENDER", "alice/r"),
            pf.Secret("EMAIL_PASSWORD", "alice/r"),
            pf.WorkflowFile("test_email.yml", "alice/r"),
        ], gh=gh)
    assert ready is False
    steps = [r for r in LOG.tail() if r["kind"] == "step"]
    sender = [s for s in steps if "secret EMAIL_SENDER" in s["name"]][0]
    assert sender["status"] == "fail" and sender["detail"] == "MISSING"
    # 結論 step 指出缺什麼
    concl = [s for s in steps if "preflight 結論" in s["name"]][0]
    assert "EMAIL_SENDER" in concl["detail"]


# ── L-22：全資源就緒 → 每項都記 present，回 True ─────────────────────────────
def test_l22_preflight_all_ok_logs_each(tmp_path):
    LOG = _log(tmp_path)
    gh = _gh(secrets=["EMAIL_SENDER", "EMAIL_PASSWORD"], repos=["alice/r"],
             workflows=["test_email.yml"])
    with LOG.action("測試發信") as a:
        ready = pf.preflight(a, [
            pf.GhAuth(),
            pf.Secret("EMAIL_SENDER", "alice/r"),
            pf.Secret("EMAIL_PASSWORD", "alice/r"),
            pf.WorkflowFile("test_email.yml", "alice/r"),
        ], gh=gh)
    assert ready is True
    steps = [r for r in LOG.tail() if r["kind"] == "step" and r["name"].startswith("preflight ")]
    assert len(steps) == 4 and all(s["status"] == "ok" for s in steps)  # 全 ok 也記


def test_workflow_missing_detected(tmp_path):
    LOG = _log(tmp_path)
    gh = _gh(secrets=["EMAIL_SENDER", "EMAIL_PASSWORD"], repos=["alice/r"],
             workflows=[])                       # 缺 workflow
    with LOG.action("x") as a:
        ready = pf.preflight(a, [pf.WorkflowFile("test_email.yml", "alice/r")], gh=gh)
    assert ready is False


def test_repo_missing_detected(tmp_path):
    LOG = _log(tmp_path)
    gh = _gh(repos=[])                            # repo 不存在
    with LOG.action("x") as a:
        ready = pf.preflight(a, [pf.RepoExists("alice/none")], gh=gh)
    assert ready is False
