"""admin_gui/services/probes.py — 連線驗證（需求 6 券商 / 12 Email / 13 gh）。

存檔前的「測試才放行」邏輯。回傳 (ok, message)；不寫金鑰、不落地。
"""
from __future__ import annotations

import json
import smtplib
import ssl
import urllib.error
import urllib.request
from typing import Optional, Tuple


def _ssl_ctx() -> ssl.SSLContext:
    """回傳帶 CA 憑證的 SSL context。

    打包成 .app（PyInstaller）後，系統 OpenSSL 找不到本機 CA → urllib/SMTP 會
    噴 CERTIFICATE_VERIFY_FAILED（unable to get local issuer certificate）。
    改用 certifi 內附的 cacert.pem 即可解。certifi 缺席時退回系統預設。
    """
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:   # noqa: BLE001
        return ssl.create_default_context()


def _dig(obj, dotted: str):
    """依 'a.b.c' 路徑取巢狀值；任何一層缺就回 None。"""
    cur = obj
    for part in (dotted or "").split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def fetch_account_id(spec: dict, environment: str, api_key: str) -> Tuple[bool, str]:
    """用 token 向券商 account_discovery 端點自動取回 account_id。

    給 bearer_token 類券商（如 Tradier）：使用者只輸入 token，
    GUI 打 profile 端點拿帳號。回 (True, account_id) 或 (False, 錯誤訊息)。
    """
    disc = (spec or {}).get("account_discovery") or {}
    ep = disc.get("endpoint")
    path = disc.get("account_id_path")
    if not ep or not path:
        return False, "此券商未定義自動取得帳號的方式"
    base = ((spec.get("environments") or {}).get(environment) or {}).get("base_url")
    if not base:
        return False, f"schema 沒有 {environment} 環境的 base_url"
    headers = {"Accept": "application/json"}
    for k, tpl in ((spec.get("auth") or {}).get("header_template") or {}).items():
        headers[k] = tpl.replace("{api_key}", api_key)
    try:
        req = urllib.request.Request(base.rstrip("/") + ep, headers=headers, method="GET")
        with urllib.request.urlopen(req, timeout=20, context=_ssl_ctx()) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return False, f"取得帳號失敗：HTTP {e.code}" + (
            "（token 無效）" if e.code in (401, 403) else "")
    except Exception as e:  # noqa: BLE001
        return False, f"取得帳號失敗：{str(e)[:140]}"

    # account_id_path 最後一段可能對應 dict 或 list（多帳號）；取第一個
    parent_path, _, leaf = path.rpartition(".")
    node = _dig(data, parent_path) if parent_path else data
    if isinstance(node, list):
        node = node[0] if node else None
    acc_id = node.get(leaf) if isinstance(node, dict) else None
    if not acc_id:
        return False, "回應中找不到帳號（account_id）"
    return True, str(acc_id)


def probe_broker(spec: dict, environment: str, api_key: str,
                 api_secret: str, account_id: str = "") -> Tuple[bool, str]:
    """依 broker schema 直接打券商 REST API 取餘額（不需 clone / broker 程式）。

    spec：brokers/<id>.json 的內容（由 Catalog.broker_spec 提供）。
    從 schema 取得 base_url、餘額端點、auth header、餘額 JSON 路徑後做一次 GET。
    """
    if not spec:
        return False, "找不到該券商的設定（broker schema）"
    if not (api_key and api_secret) and not api_key:
        return False, "缺 API 金鑰"
    try:
        base = ((spec.get("environments") or {}).get(environment) or {}).get("base_url")
        if not base:
            return False, f"schema 沒有 {environment} 環境的 base_url"
        eps = spec.get("endpoints") or {}
        ep = eps.get("account") or eps.get("balances") or eps.get("balance")
        if not ep:
            return False, "schema 沒有餘額/帳戶端點"
        ep = ep.replace("{account_id}", account_id or "")
        url = base.rstrip("/") + ep

        headers = {"Accept": "application/json"}
        for k, tpl in ((spec.get("auth") or {}).get("header_template") or {}).items():
            headers[k] = (tpl.replace("{api_key}", api_key)
                             .replace("{api_secret}", api_secret)
                             .replace("{account_id}", account_id or ""))

        req = urllib.request.Request(url, headers=headers, method="GET")
        with urllib.request.urlopen(req, timeout=20, context=_ssl_ctx()) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        bpath = (spec.get("response") or {}).get("balance") or {}
        nav = _dig(data, bpath.get("nav", ""))
        cash = _dig(data, bpath.get("cash", ""))
        if nav is None and cash is None:
            return True, "連線成功（已通過驗證；此券商未提供標準餘額欄位）"
        navf = float(nav) if nav is not None else 0.0
        cashf = float(cash) if cash is not None else 0.0
        return True, f"連線成功：NAV=${navf:,.2f}、現金=${cashf:,.2f}"
    except urllib.error.HTTPError as e:
        msg = f"HTTP {e.code}"
        if e.code in (401, 403):
            msg += "（金鑰無效，或 live key 配到 paper / 反之）"
        return False, f"連線失敗：{msg}"
    except Exception as e:  # noqa: BLE001
        return False, f"連線失敗：{str(e)[:160]}"


def probe_email(sender: str, app_password: str, recipient: str) -> Tuple[bool, str]:
    """用 Gmail SMTP 試寄一封測試信。成功回 (True, 摘要)。"""
    if not sender or not app_password:
        return False, "缺寄件人或 App 密碼"
    to = recipient or sender
    msg = (f"From: {sender}\r\nTo: {to}\r\n"
           f"Subject: [測試] 交易系統管理控制台 連線測試\r\n\r\n"
           f"這是一封測試信，收到代表 Email 發送設定正確。")
    try:
        ctx = _ssl_ctx()
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=20) as s:
            s.starttls(context=ctx)
            s.login(sender, app_password)
            s.sendmail(sender, [to], msg.encode("utf-8"))
        return True, f"測試信已寄至 {to}"
    except smtplib.SMTPAuthenticationError:
        return False, "驗證失敗：請確認用的是 Gmail App Password（非一般登入密碼）"
    except Exception as e:  # noqa: BLE001
        return False, f"寄送失敗：{str(e)[:160]}"


_DEV_EMAIL = "itemhsu@gmail.com"   # 開發者收件人（寫死，不接受 UI 輸入）


def send_log_to_dev(sender: str, app_password: str, body: str,
                    subject: str = "[TradingAdmin log]") -> Tuple[bool, str]:
    """用使用者自己的 Gmail SMTP 把 log 寄給開發者（itemhsu）。收件人寫死。"""
    if not sender or not app_password:
        return False, "缺寄件人或 App 密碼（無法 SMTP 寄送）"
    to = _DEV_EMAIL
    from email.mime.text import MIMEText
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to
    try:
        ctx = _ssl_ctx()
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as s:
            s.starttls(context=ctx)
            s.login(sender, app_password)
            s.sendmail(sender, [to], msg.as_string())
        return True, f"log 已寄給 {to}"
    except smtplib.SMTPAuthenticationError:
        return False, "驗證失敗：請用 Gmail App Password（非一般密碼）"
    except Exception as e:  # noqa: BLE001
        return False, f"寄送失敗：{str(e)[:160]}"


def gh_login(runner=None) -> str:
    """回傳目前 gh 登入的 GitHub 帳號（login）；未登入/失敗回空字串。"""
    import subprocess
    run = runner or subprocess.run
    try:
        r = run(["gh", "api", "user", "--jq", ".login"],
                capture_output=True, text=True, timeout=15)
        return (r.stdout or "").strip() if r.returncode == 0 else ""
    except Exception:  # noqa: BLE001
        return ""


def probe_gh(runner=None) -> Tuple[bool, str]:
    """gh 是否已登入。"""
    import subprocess
    run = runner or subprocess.run
    try:
        r = run(["gh", "auth", "status"], capture_output=True, text=True)
        if r.returncode == 0:
            return True, "gh 已登入"
        return False, "gh 未登入 → 執行 gh auth login"
    except FileNotFoundError:
        return False, "找不到 gh，請先安裝 GitHub CLI"


# ── 需求 22：測試發信＝觸發雲端 workflow（不要本機密碼）────────────────
def trigger_test_email(repo: str = "itemhsu/tech-rebalance", runner=None) -> Tuple[bool, str]:
    """觸發 test_email.yml（用 repo 端已存的 EMAIL_PASSWORD secret 寄信）。"""
    import subprocess
    run = runner or subprocess.run
    r = run(["gh", "workflow", "run", "test_email.yml", "--repo", repo],
            capture_output=True, text=True)
    if r.returncode != 0:
        return False, f"觸發失敗：{(r.stderr or r.stdout)[:160]}"
    return True, "已觸發測試發信，約 20–40 秒後按『查看結果』"


def trigger_refresh_nav(repo: str, runner=None) -> Tuple[bool, str]:
    """觸發 refresh_nav.yml（雲端唯讀查每帳戶即時 NAV，寫 data/nav_snapshot.json）。"""
    import subprocess
    run = runner or subprocess.run
    r = run(["gh", "workflow", "run", "refresh_nav.yml", "--repo", repo],
            capture_output=True, text=True)
    if r.returncode != 0:
        err = (r.stderr or r.stdout)[:200]
        if "does not have" in err.lower() or "not found" in err.lower():
            return False, "尚無 refresh_nav.yml —— 請先「重新執行設定精靈→修復」。"
        return False, f"觸發失敗：{err}"
    return True, "已觸發即時 NAV 查詢"


def last_refresh_nav_result(repo: str, runner=None) -> Tuple[str, str]:
    """refresh_nav.yml 最新 run 的 (status, conclusion)。"""
    import json
    import subprocess
    run = runner or subprocess.run
    r = run(["gh", "run", "list", "--workflow", "refresh_nav.yml", "--repo", repo,
             "--limit", "1", "--json", "status,conclusion"],
            capture_output=True, text=True)
    if r.returncode != 0:
        return "unknown", ""
    try:
        d = json.loads(r.stdout or "[]")
    except json.JSONDecodeError:
        return "unknown", ""
    return (d[0].get("status", "unknown"), d[0].get("conclusion", "")) if d else ("none", "")


def read_nav_snapshot(repo: str, runner=None) -> dict:
    """從 repo B 讀 data/nav_snapshot.json（gh api contents），回 {id: {nav,cash,ts}|{error}}。"""
    import base64
    import json
    import subprocess
    run = runner or subprocess.run
    r = run(["gh", "api", f"repos/{repo}/contents/data/nav_snapshot.json",
             "--jq", ".content"], capture_output=True, text=True)
    if r.returncode != 0:
        return {}
    try:
        return json.loads(base64.b64decode(r.stdout or "").decode("utf-8"))
    except Exception:  # noqa: BLE001
        return {}


_SEND_LOG_MAX = 50000   # workflow_dispatch input 上限 65535，留餘裕


def trigger_send_log(repo: str, body: str, who: str = "", runner=None) -> Tuple[bool, str]:
    """觸發 send_log.yml：把 log 內容當 input 傳給雲端 workflow，由它用
    EMAIL_SENDER/EMAIL_PASSWORD secret（雲端 SMTP，已證可用）寄給開發者。
    本機不需任何密碼。body 過長則截尾（保留最新）。"""
    import subprocess
    run = runner or subprocess.run
    if len(body) > _SEND_LOG_MAX:
        body = "（前段已截斷，僅保留最新部分）\n" + body[-_SEND_LOG_MAX:]
    r = run(["gh", "workflow", "run", "send_log.yml", "--repo", repo,
             "--field", f"body={body}", "--field", f"who={who}"],
            capture_output=True, text=True)
    if r.returncode != 0:
        err = (r.stderr or r.stdout)[:200]
        if "Workflow does not have" in err or "not found" in err.lower():
            return False, ("repo 還沒有 send_log.yml workflow —— 請先到「總覽」按"
                           "『重新執行設定精靈』修復交易系統（會補上此 workflow）。")
        return False, f"觸發失敗：{err}"
    return True, "已觸發雲端寄送 log，約 20–40 秒寄達"


def last_send_log_result(repo: str, runner=None) -> Tuple[str, str]:
    """讀 send_log.yml 最新一次 run 的 (status, conclusion)。"""
    import json
    import subprocess
    run = runner or subprocess.run
    r = run(["gh", "run", "list", "--workflow", "send_log.yml", "--repo", repo,
             "--limit", "1", "--json", "status,conclusion"],
            capture_output=True, text=True)
    if r.returncode != 0:
        return "unknown", ""
    try:
        data = json.loads(r.stdout or "[]")
    except json.JSONDecodeError:
        return "unknown", ""
    if not data:
        return "none", ""
    return data[0].get("status", "unknown"), data[0].get("conclusion", "")


def last_test_email_result(repo: str = "itemhsu/tech-rebalance", runner=None) -> Tuple[str, str]:
    """讀 test_email.yml 最新一次 run 的狀態。回 (status, conclusion)。"""
    import json
    import subprocess
    run = runner or subprocess.run
    r = run(["gh", "run", "list", "--workflow", "test_email.yml", "--repo", repo,
             "--limit", "1", "--json", "status,conclusion"],
            capture_output=True, text=True)
    if r.returncode != 0:
        return "unknown", ""
    try:
        data = json.loads(r.stdout or "[]")
    except json.JSONDecodeError:
        return "unknown", ""
    if not data:
        return "none", ""
    return data[0].get("status", "unknown"), data[0].get("conclusion", "")


def last_test_email_failure_reason(repo: str = "itemhsu/tech-rebalance",
                                   runner=None, workflow: str = "test_email.yml") -> str:
    """抓指定 workflow 最新失敗 run 的 log，回傳 python 印的 FAIL/錯誤行。
    讀不到回空字串（呼叫端顯示通用訊息）。杜絕安靜失敗——把真正原因撈出來。"""
    import json
    import subprocess
    run = runner or subprocess.run
    r = run(["gh", "run", "list", "--workflow", workflow, "--repo", repo,
             "--limit", "1", "--json", "databaseId"],
            capture_output=True, text=True)
    if r.returncode != 0:
        return ""
    try:
        rows = json.loads(r.stdout or "[]")
        rid = rows[0]["databaseId"] if rows else None
    except (json.JSONDecodeError, KeyError, IndexError):
        return ""
    if not rid:
        return ""
    lr = run(["gh", "run", "view", str(rid), "--repo", repo, "--log"],
             capture_output=True, text=True)
    log = (lr.stdout or "") + (lr.stderr or "")
    import re
    ansi = re.compile(r"\x1b\[[0-9;]*m")
    out = []
    for raw in log.splitlines():
        ln = ansi.sub("", raw)                       # 去 ANSI 色碼
        # gh log 每行格式：job<TAB>step<TAB>timestamp 內容 —— 砍掉前綴只留內容
        parts = ln.split("\t")
        content = parts[-1] if parts else ln
        content = re.sub(r"^\S*Z\s*", "", content).strip()   # 砍 ISO 時戳
        # 只要「程式真正輸出」的 FAIL/Error；排除回顯的原始碼（含 print(/sys.exit）
        if not content or "##[" in content:
            continue
        if "print(" in content or "sys.exit" in content or content.startswith("run:"):
            continue
        if ("FAIL" in content or "Traceback" in content
                or re.search(r"\bError\b", content)):
            out.append(content)
    return out[-1][:300] if out else ""
