"""admin_gui/views/wizard.py — 啟動精靈 v3（兩-repo 薄殼專用）。

只有兩步：
  ① gh 登入　② 建立交易系統（兩 repo 薄殼）＋ 更新引擎版本
使用者只輸入「GitHub 帳號」，內部自動組成 {帳號}/tech-rebalance（Repo B）。
引擎以 git+ 從公開 repo 安裝（免 token / 免 wheel）。

舊的 fork 路線（Fork 範本 / Pages / Actions / 同步上游）已移除——本系統一律走
兩-repo 薄殼架構，不再支援 fork。精靈每次啟動都顯示、保留「略過」。
不處理也不提示 Email 密碼（總覽分頁）與帳戶（帳戶分頁）。
"""
from __future__ import annotations

import subprocess

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QMessageBox, QWidget,
)

from admin_gui.services.probes import probe_gh
from admin_gui.services.global_config import GlobalConfig

# 兩 repo 架構：使用者的薄殼 Repo B（設定+資料，引擎以 git+ 從公開 repo 安裝，免 token）
# Repo B 一律為 {帳號}/tech-rebalance（單一 repo，無候選）。
_REPOB_NAME = "tech-rebalance"
# 已廢棄的舊命名：若 config 殘留此 slug 一律忽略，不再依賴它
_DISCARDED_REPOB_NAME = "tech-rebalance-data"
_ENGINE_REPO = "itemhsu/tech-rebalance-pub"


def is_first_run(config: GlobalConfig) -> bool:
    """保留供相容；app 現在每次啟動都顯示精靈（W-1）。"""
    return not config.load().get("setup_done", False)


def _gh(args, inp=None, timeout=60):
    """所有 gh 流量的瓶頸 —— 在這裡內建 log，涵蓋全部 ~50 個呼叫點（密度規則 C）。
    回傳即記 args(去敏) + rc；非零記 stderr 前 200 字。"""
    from admin_gui.services.action_log import LOG, mask_secrets
    safe_args = mask_secrets(" ".join(str(a) for a in args))[:200]
    try:
        r = subprocess.run(["gh", *args], capture_output=True, text=True,
                           input=inp, timeout=timeout)
        code = r.returncode
        out = (r.stdout or "").strip()
        err = (r.stderr or "").strip()
        if code != 0:
            # 冪等修復的「預期」非零（repo 已存在 / Pages 已啟用 / 404 探測）不算警告。
            # 404：render 前查檔案 sha，檔案還沒建立會回 404，屬正常「將建立」路徑。
            benign = ("already exists" in err.lower()
                      or "already enabled" in err.lower()
                      or "http 409" in err.lower()
                      or "http 404" in err.lower()
                      or "not found" in err.lower())
            LOG.note("gh", "ok" if benign else "warn",
                     f"rc={code} `{safe_args}` err={err[:200]}")
        return code, out, err
    except Exception as e:  # noqa: BLE001  例外＝記原因，不靜默
        LOG.note("gh", "fail", f"`{safe_args}` exc={type(e).__name__}: {str(e)[:160]}")
        return 1, "", str(e)


class SetupWizard(QDialog):
    """引導式設定；完成回傳 chosen_repo = {帳號}/tech-rebalance。"""

    def __init__(self, config: GlobalConfig, parent=None):
        super().__init__(parent)
        self.config = config
        self.chosen_repo = ""
        self.setWindowTitle("設定精靈")
        self.resize(600, 380)
        lay = QVBoxLayout(self)

        lay.addWidget(QLabel(
            "<b>歡迎！</b>用 GitHub API 直接管理你的交易系統，"
            "<b>不下載任何代碼</b>。完成下列步驟即可開始。"))

        # gh 登入
        self.gh_lbl = QLabel("GitHub 登入：檢查中…")
        lay.addWidget(self.gh_lbl)
        gh_btn = QPushButton("登入 GitHub（gh auth login，開瀏覽器授權）")
        gh_btn.clicked.connect(self._gh_login)
        lay.addWidget(gh_btn)

        # 帳號（唯一輸入；登入後自動帶出）
        urow = QWidget(); ul = QHBoxLayout(urow); ul.setContentsMargins(0, 0, 0, 0)
        ul.addWidget(QLabel("你的 GitHub 帳號"))
        self.user_edit = QLineEdit(self._initial_user())
        self.user_edit.setPlaceholderText("例如 itemhsu")
        self.user_edit.textChanged.connect(lambda *_: self._refresh_status())
        ul.addWidget(self.user_edit)
        lay.addWidget(urow)

        # 兩 repo 架構：建立薄殼 Repo B + 更新引擎版本（唯一路線）
        self.repob_row = self._step_row(lay, "建立交易系統（兩 repo 薄殼）", "建立", self._do_build_repob)
        self.engine_row = self._step_row(lay, "更新引擎版本", "更新", self._do_update_engine)

        refresh_btn = QPushButton("↻ 重新檢查狀態")
        refresh_btn.clicked.connect(self._refresh_status)
        lay.addWidget(refresh_btn)

        lay.addStretch()
        brow = QWidget(); bl = QHBoxLayout(brow)
        skip = QPushButton("略過"); skip.clicked.connect(self.reject)
        done = QPushButton("完成，開始使用 →"); done.clicked.connect(self._finish)
        bl.addWidget(skip); bl.addStretch(); bl.addWidget(done)
        lay.addWidget(brow)

        self._refresh_gh()
        # 精靈顯示後自動偵測一次（singleShot 讓視窗先渲染完再跑，不卡 UI）
        from PySide6.QtCore import QTimer
        QTimer.singleShot(400, self._refresh_status)

    # ── 建一列「狀態圖示 + 標題 + 動作按鈕」並回傳控制項 dict ───────────────
    def _step_row(self, lay, title, action_text, handler) -> dict:
        row = QWidget(); h = QHBoxLayout(row); h.setContentsMargins(0, 0, 0, 0)
        icon = QLabel("⬜")
        text = QLabel(title)
        status = QLabel("")
        status.setStyleSheet("color:#94a3b8;font-size:11px;")
        btn = QPushButton(action_text)
        btn.clicked.connect(handler)
        h.addWidget(icon); h.addWidget(text); h.addStretch()
        h.addWidget(status); h.addWidget(btn)
        lay.addWidget(row)
        return {"icon": icon, "status": status, "btn": btn, "action": action_text, "widget": row}

    def _initial_user(self) -> str:
        slug = self.config.get("repob_slug") or self.config.get("repo_slug")
        if slug and "/" in slug:
            return slug.split("/")[0]
        return ""

    def _repob_slug(self) -> str:
        """解析 Repo B slug（純函式，不連網）：Repo B 一律為 {帳號}/tech-rebalance。

          1. config 已存 repob_slug → 用它（但忽略已廢棄的 *-data 殘留快取）
          2. 否則 {帳號}/tech-rebalance
        """
        cfg = self.config.get("repob_slug")
        if cfg and not cfg.endswith(f"/{_DISCARDED_REPOB_NAME}"):
            return cfg
        u = self.user_edit.text().strip()
        return f"{u}/{_REPOB_NAME}" if u else ""

    # ── ① gh 登入 ─────────────────────────────────────────────────────
    def _refresh_gh(self):
        """檢查 gh 登入 + 偵測帳號。背景執行，不卡精靈（P0）。"""
        from admin_gui.services.async_task import run_async
        self.gh_lbl.setText("GitHub 登入：檢查中…")
        run_async(self, lambda report: self._compute_gh(), on_done=self._apply_gh)

    @staticmethod
    def _compute_gh():
        """背景：gh auth status + gh api user。"""
        ok, msg = probe_gh()
        login = ""
        if ok:
            code, out, _ = _gh(["api", "user", "--jq", ".login"])
            login = out if code == 0 else ""
        return (ok, msg, login)

    def _apply_gh(self, res):
        ok, msg, login = res
        self.gh_lbl.setText(("✅ " if ok else "❌ ") + "GitHub 登入：" + msg)
        if ok and login and not self.user_edit.text().strip():
            self.user_edit.setText(login)   # 觸發 textChanged → _refresh_status（已背景）

    def _detect_user(self):
        code, out, _ = _gh(["api", "user", "--jq", ".login"])
        if code == 0 and out:
            self.user_edit.setText(out)

    def _gh_login(self):
        from admin_gui.services.action_log import LOG
        with LOG.action("登入 GitHub（gh auth login）") as a:
            try:
                subprocess.Popen(["gh", "auth", "login", "--web"])
                a.step("開啟 gh auth login --web", "ok", "已啟動瀏覽器授權流程")
                QMessageBox.information(self, "授權中",
                    "已開啟 gh 登入流程，請依指示完成後回來按「↻ 重新檢查狀態」。")
            except FileNotFoundError:
                a.step("開啟 gh auth login", "fail", "找不到 gh（GitHub CLI 未安裝）")
                QMessageBox.warning(self, "找不到 gh", "請先安裝 GitHub CLI（gh）。")
        self._refresh_gh()

    # ── 狀態檢查（冪等防呆）─────────────────────────────────────────────
    def _set_done(self, row: dict, done: bool, done_text: str):
        row["icon"].setText("✅" if done else "⬜")
        row["status"].setText(done_text if done else "")
        row["btn"].setEnabled(not done)
        row["btn"].setText(("✅ 已完成" if done else row["action"]))

    def _refresh_status(self):
        """檢查 repo / 引擎狀態。耗時的 gh 呼叫全在背景執行，UI 先顯示「檢查中…」，
        絕不凍結精靈（P0：先畫面、後耗時）。"""
        if not self.user_edit.text().strip():
            self._set_done(self.repob_row, False, "")
            self._set_done(self.engine_row, False, "")
            return
        if getattr(self, "_status_running", False):
            return                                   # 避免快速輸入時重複起背景任務
        self._status_running = True
        # UI 先給「檢查中…」回饋
        self.repob_row["status"].setText("檢查中…")
        self.engine_row["status"].setText("檢查中…")
        repob = self._repob_slug()
        u = self.user_edit.text().strip()
        from admin_gui.services.async_task import run_async
        run_async(self,
                  lambda report: self._compute_status(repob, u),
                  on_done=self._apply_status,
                  on_failed=self._status_failed)

    @staticmethod
    def _compute_status(repob: str, u: str) -> dict:
        """背景執行緒：所有 gh 網路呼叫在此，回傳結果 dict（不碰 UI）。"""
        import base64 as _b64
        import json as _json
        from admin_gui.services import engine_release as er
        dash = f"{u}/tech-rebalance-dashboard"
        repob_ok = (_gh(["api", f"repos/{repob}", "--jq", ".full_name"])[0] == 0)
        dash_ok = (_gh(["api", f"repos/{dash}", "--jq", ".full_name"])[0] == 0)
        res = {"repob": repob, "repob_ok": repob_ok, "dash_ok": dash_ok,
               "both_ok": repob_ok and dash_ok, "engine_note": "", "engine_ok": False}
        if not repob_ok:
            res["engine_note"] = "（先建立交易系統）"
            return res
        pinned = None
        cw, wf_list, _ = _gh(["api",
            f"repos/{repob}/contents/.github/workflows", "--jq", "[.[].name]"])
        wf_names = []
        if cw == 0 and wf_list:
            try:
                wf_names = _json.loads(wf_list)
            except Exception:  # noqa: BLE001
                wf_names = []
        for wfn in wf_names:
            c2, content, _ = _gh(["api",
                f"repos/{repob}/contents/.github/workflows/{wfn}", "--jq", ".content"])
            if c2 == 0 and content:
                try:
                    p = er.pinned_git_version(_b64.b64decode(content).decode("utf-8"))
                    if p:
                        pinned = p
                        break
                except Exception:  # noqa: BLE001
                    continue
        versions = er.list_versions(_ENGINE_REPO)
        latest = versions[0] if versions else None
        up_to_date = bool(pinned and latest and pinned.lstrip("v") == latest.lstrip("v"))
        if up_to_date:
            note = f"已是最新 {pinned}"
        elif pinned and latest:
            note = f"可更新 {pinned}→{latest}"
        elif not pinned:
            note = "未用 git+ 釘版，按「更新」切換為公開引擎"
        else:
            note = f"目前 {pinned}（取不到最新版）"
        res["engine_ok"] = up_to_date
        res["engine_note"] = note
        return res

    def _apply_status(self, res: dict):
        """主執行緒：依背景結果更新各列。"""
        self._status_running = False
        repob = res["repob"]
        both_ok = res["both_ok"]
        if both_ok:
            note = f"已建立 · {repob.split('/')[-1]} + dashboard"
        elif res["repob_ok"]:
            note = f"已建立 {repob.split('/')[-1]}，尚缺 dashboard repo"
        elif res["dash_ok"]:
            note = f"已建立 dashboard，尚缺 {repob.split('/')[-1]}"
        else:
            note = ""
        self._set_done(self.repob_row, both_ok, note)
        self.repob_row["btn"].setEnabled(True)
        self.repob_row["btn"].setText("🔧 修復" if both_ok else self.repob_row["action"])
        self._set_done(self.engine_row, res["engine_ok"], res["engine_note"])
        self.engine_row["status"].setText(res["engine_note"])

    def _status_failed(self, err: str):
        self._status_running = False
        self.repob_row["status"].setText(f"檢查失敗：{err[:60]}")

    # ── 建立 / 修復 交易系統（manifest 驅動，冪等）───────────────────────
    def _do_build_repob(self):
        """建立/修復交易系統：先彈進度視窗，重活在背景執行（不凍結精靈）。"""
        from PySide6.QtWidgets import QProgressDialog
        from PySide6.QtCore import Qt, QTimer
        from admin_gui.services.async_task import run_async
        from admin_gui.services.action_log import LOG

        u = self.user_edit.text().strip()
        if not u:
            QMessageBox.warning(self, "缺帳號", "請先填入 GitHub 帳號。"); return
        slug = self._repob_slug()                          # {user}/tech-rebalance
        dash = f"{u}/tech-rebalance-dashboard"

        repob_exists = (_gh(["api", f"repos/{slug}", "--jq", ".full_name"])[0] == 0)
        verb = "修復" if repob_exists else "建立"
        if QMessageBox.question(
                self, f"{verb}交易系統",
                f"將{verb}：\n  • {slug}（private，薄殼 Repo B）\n"
                f"  • {dash}（public，Dashboard）\n"
                "冪等：缺的檔補上、引擎 workflow 更新到最新；你的 accounts.json / 資料不會被動。\n"
                "要繼續嗎？"
        ) != QMessageBox.Yes:
            return

        # 進度視窗：顯示目前步驟 + 秒數（步驟名來自 action_log 的即時 step）
        dlg = QProgressDialog(f"{verb}交易系統…", "在背景繼續", 0, 0, self)
        dlg.setWindowTitle(f"{verb}交易系統"); dlg.setWindowModality(Qt.WindowModal)
        dlg.setMinimumWidth(460); dlg.setAutoClose(False); dlg.setAutoReset(False)
        dlg.setMinimumDuration(0); dlg.show()      # 立刻顯示，不等預設 4 秒
        self._build_secs = 0; self._build_step = "準備中…"
        timer = QTimer(self); timer.setInterval(1000)
        def _tick():
            self._build_secs += 1
            dlg.setLabelText(f"{verb}交易系統…（{self._build_secs}s）\n目前：{self._build_step}")
        timer.timeout.connect(_tick); timer.start()

        def _on_step(rec):
            if isinstance(rec, dict) and rec.get("kind") == "step":
                self._build_step = rec.get("name", "")
        LOG.subscribe(_on_step)

        def _cleanup():
            timer.stop(); dlg.close()
            try:
                LOG._listeners.remove(_on_step)
            except (ValueError, AttributeError):
                pass

        def _finish(problems):
            _cleanup(); self._build_done(verb, slug, u, problems)

        def _failed(err):
            _cleanup(); QMessageBox.warning(self, f"{verb}失敗", err[:300])

        run_async(self,
                  lambda report: self._do_build_repob_core(verb, slug, dash, u),
                  on_done=_finish, on_failed=_failed)

    def _build_done(self, verb, slug, u, problems):
        """主執行緒：建立完成後的結果對話框 + 重新檢查狀態。"""
        if not problems:
            QMessageBox.information(self, f"{verb}完成",
                f"全部成功 ✅\n\n下一步：\n1. 在「帳戶」分頁新增帳戶並填 Alpaca 金鑰\n"
                f"2. Dashboard：https://{u}.github.io/tech-rebalance-dashboard/")
        else:
            detail = "\n".join(f"• {p.name}: {p.status} {p.detail}"
                               for p in problems if p.status != "skip")
            QMessageBox.warning(self, f"{verb}完成但有問題",
                f"以下步驟未完全成功（詳見「日誌」分頁，可按📧發送 log）：\n\n{detail}")
        self._refresh_status()

    def _do_build_repob_core(self, verb, slug, dash, u):
        """背景執行緒：實際建立/修復（所有 gh 在此）。回傳 problems 清單。"""
        import base64 as _b64, json as _json
        from admin_gui.services import engine_release as er
        from admin_gui.services import repo_b_provisioner as pv
        from admin_gui.services import repo_sync as rs
        from admin_gui.services.action_log import LOG
        with LOG.action(f"{verb}交易系統", ctx=slug) as a:
            versions = er.list_versions(_ENGINE_REPO)
            if not versions:
                a.step("list_versions", "fail", f"列不到 {_ENGINE_REPO} 的 Release")
                raise RuntimeError("找不到引擎版本，請確認 gh 已登入。")
            latest = versions[0]
            a.step("latest engine", "ok", latest)

            # 「已存在」對修復而言是正常結果 → 記 ok，不要嚇使用者
            def _repo_create_status(rc):
                if rc[0] == 0:
                    return "ok", "已建立"
                if "already exists" in (rc[2] or "").lower():
                    return "ok", "已存在（修復時略過）"
                return "fail", f"rc={rc[0]} {rc[2][:80]}"

            # ── ① Repo B：建 repo + 初始 accounts.json（缺才補）+ sync ──
            rc = _gh(["repo", "create", slug, "--private"])
            st, dt = _repo_create_status(rc)
            a.step("gh repo create (repo B)", st, dt)

            # PAGES_TOKEN：自動用使用者現有的 gh token 設定（使用者擁有 dashboard repo，
            # 此 token 即可寫入）。完全不需使用者建 PAT。每日才能把持倉資料推上 Dashboard。
            try:
                tk = subprocess.run(["gh", "auth", "token"],
                                    capture_output=True, text=True, timeout=15)
                token = (tk.stdout or "").strip()
                if token:
                    sr = _gh(["secret", "set", "PAGES_TOKEN", "--repo", slug], inp=token)
                    a.step("set PAGES_TOKEN（用 gh token，自動）",
                           "ok" if sr[0] == 0 else "fail",
                           "已設（發佈 Dashboard 用）" if sr[0] == 0 else f"rc={sr[0]}")
                else:
                    a.step("set PAGES_TOKEN", "warn", "拿不到 gh token，Dashboard 發佈將略過")
            except Exception as e:   # noqa: BLE001  設不到不擋修復
                a.step("set PAGES_TOKEN", "warn", f"{type(e).__name__}: {str(e)[:120]}")
            if _gh(["api", f"repos/{slug}/contents/accounts.json", "--jq", ".sha"])[0] != 0:
                init_files = pv.build_template_files(latest)
                acc = init_files.get("accounts.json")
                if acc:
                    pr = _gh(["api", "-X", "PUT", f"repos/{slug}/contents/accounts.json", "--input", "-"],
                             inp=_json.dumps({"message": "init accounts.json",
                                              "content": _b64.b64encode(acc).decode()}))
                    a.step("init accounts.json", "ok" if pr[0] == 0 else "fail", f"rc={pr[0]}")
            # 安全：別名 daily workflow → 不另 render daily.yml（避免重複下單）
            skip = set()
            cwf, wf_raw, _ = _gh(["api", f"repos/{slug}/contents/.github/workflows",
                                  "--jq", "[.[].name]"])
            if cwf == 0 and wf_raw:
                try:
                    names = _json.loads(wf_raw)
                except Exception as ex:  # noqa: BLE001
                    a.step("parse workflows", "warn", f"{type(ex).__name__}: {wf_raw[:120]}")
                    names = []
                legacy = [n for n in names if n.endswith(".yml") and n != "daily.yml"
                          and ("daily" in n or "all_accounts" in n)]
                if legacy:
                    skip.add(".github/workflows/daily.yml")
                    a.step("legacy daily workflow", "ok",   # 資訊性，非問題
                           f"偵測到 {legacy}，跳過 daily.yml（避免重複下單）")
            rs.sync("repo_b", slug, latest, gh=_gh, skip_paths=skip, logger=a)
            self.config.set("repob_slug", slug)

            # ── ② Dashboard：建 repo + 共用 viewer 複製 + sync placeholders ──
            rc = _gh(["repo", "create", dash, "--public"])
            st, dt = _repo_create_status(rc)
            a.step("gh repo create (dashboard)", st, dt)
            TEMPLATE = "itemhsu/tech-rebalance-dashboard"
            # viewer 一律「覆蓋更新」（修復時把舊 viewer 升級到最新，例如友善空狀態）；
            # 其餘共用頁缺才補。
            _viewer_overwrite = {"mvp_dashboard.html"}
            for fpath in ["mvp_dashboard.html", "momentum/index.html"]:
                cur_sha = _gh(["api", f"repos/{dash}/contents/{fpath}", "--jq", ".sha"])
                exists = cur_sha[0] == 0
                if exists and fpath not in _viewer_overwrite:
                    continue                              # 既有且非 viewer → 不動
                cr, c64, ce = _gh(["api", f"repos/{TEMPLATE}/contents/{fpath}", "--jq", ".content"])
                if cr == 0 and c64.strip():
                    payload = {"message": f"seed {fpath}", "content": c64.replace("\n", "")}
                    if exists:
                        payload["sha"] = cur_sha[1].strip()   # 覆蓋需帶 sha
                    _gh(["api", "-X", "PUT", f"repos/{dash}/contents/{fpath}", "--input", "-"],
                        inp=_json.dumps(payload))
                    a.step(f"seed {fpath}", "ok", "更新" if exists else "from template")
                else:
                    a.step(f"seed {fpath}", "fail", f"rc={cr} err={ce[:120]}")
            rs.sync("dashboard", dash, latest, gh=_gh, logger=a)
            pages_payload = _json.dumps({"source": {"branch": "main", "path": "/"}})
            cp, _, ep = _gh(["api", "-X", "POST", f"repos/{dash}/pages", "--input", "-"],
                            inp=pages_payload)
            dash_ok = cp == 0 or "already" in ep.lower() or "409" in ep
            a.step("enable Pages", "ok" if dash_ok else "warn",
                   "已啟用" if dash_ok else f"rc={cp} {ep[:80]}")

            problems = a.problems()
        # 結果對話框在主執行緒（_build_done）做；這裡只回傳 problems。
        return problems

    # ── 更新引擎版本 ─────────────────────────────────────────────────────
    def _do_update_engine(self):
        """包一層 action_log（裡面的 _gh() 呼叫會自動歸進此 action）。"""
        from admin_gui.services.action_log import LOG
        with LOG.action("更新引擎版本", ctx=self._repob_slug()):
            self._do_update_engine_impl()

    def _do_update_engine_impl(self):
        """掃 Repo B 所有 workflow，找到含 pip install 的那個，遷移或 bump 到最新 pub engine。

        支援兩種情況：
          - 已有 git+ pin → bump 版本
          - 還在用 pip install -r requirements.txt → 遷移成 git+ 安裝
        """
        import base64 as _b64, json as _json
        from admin_gui.services import engine_release as er
        slug = self.config.get("repob_slug") or self._repob_slug()
        if not slug:
            QMessageBox.warning(self, "缺 Repo B", "請先建立交易系統（按「建立」）。"); return
        versions = er.list_versions(_ENGINE_REPO)
        if not versions:
            QMessageBox.warning(self, "找不到引擎版本", "無法列出公開引擎 Release。"); return
        latest = versions[0]

        # ── 找目標 workflow 檔案（掃所有，優先選已有 git+ pin 的）────────
        cw, wf_list_raw, _ = _gh(["api",
            f"repos/{slug}/contents/.github/workflows", "--jq", "[.[].name]"])
        wf_names = []
        if cw == 0 and wf_list_raw:
            try:
                wf_names = _json.loads(wf_list_raw)
            except Exception:  # noqa: BLE001
                pass

        target_path = target_text = target_sha = None
        fallback_path = fallback_text = fallback_sha = None
        for wfn in wf_names:
            if not wfn.endswith(".yml"):
                continue
            path = f".github/workflows/{wfn}"
            c2, content_b64, _ = _gh(["api",
                f"repos/{slug}/contents/{path}", "--jq", ".content"])
            cs, sha_raw, _ = _gh(["api",
                f"repos/{slug}/contents/{path}", "--jq", ".sha"])
            if c2 != 0:
                continue
            try:
                text = _b64.b64decode(content_b64).decode("utf-8")
            except Exception:  # noqa: BLE001
                continue
            sha = sha_raw.strip() if cs == 0 else None
            if er.pinned_git_version(text):
                target_path, target_text, target_sha = path, text, sha
                break                          # git+ 已在此 → 直接用
            if fallback_path is None and ("requirements.txt" in text
                                          or "pip install" in text):
                fallback_path, fallback_text, fallback_sha = path, text, sha

        if target_path is None:
            target_path, target_text, target_sha = (
                fallback_path, fallback_text, fallback_sha)

        if target_path is None:
            QMessageBox.warning(self, "找不到 workflow",
                f"{slug} 的 .github/workflows/ 中找不到可更新的 workflow。\n"
                "請確認 Repo B 已建立且含 GitHub Actions workflow。")
            return

        wf_name = target_path.split("/")[-1]
        if QMessageBox.question(
                self, "更新引擎",
                f"將更新 {slug}/{wf_name} 的引擎為 {latest}。\n"
                "（git+ 安裝公開引擎，免 token / 免 wheel）要繼續嗎？"
        ) != QMessageBox.Yes:
            return

        new_text = er.migrate_to_git_install(target_text, latest)
        if new_text is None:
            QMessageBox.warning(self, "無法自動遷移",
                f"{wf_name} 中找不到 pip install 行，無法自動更新。\n"
                "請手動把安裝步驟改為：\n"
                f'pip install "tech-rebalance @ git+https://github.com/itemhsu/tech-rebalance-pub@{latest}"')
            return

        body: dict = {"message": f"update engine → {latest} (git+ pub)",
                      "content": _b64.b64encode(new_text.encode()).decode()}
        if target_sha:
            body["sha"] = target_sha
        r = _gh(["api", "-X", "PUT",
                 f"repos/{slug}/contents/{target_path}", "--input", "-"],
                inp=_json.dumps(body))
        if r[0] == 0:
            QMessageBox.information(self, "更新完成",
                f"{slug}/{wf_name} 的引擎已更新到 {latest}。")
            self._refresh_status()
        else:
            QMessageBox.warning(self, "推送失敗",
                f"更新 {wf_name} 時發生錯誤：{r[2][:200]}")

    # ── 完成 ──────────────────────────────────────────────────────────
    def _finish(self):
        slug = self._repob_slug()
        if not slug:
            QMessageBox.warning(self, "缺帳號", "請填入你的 GitHub 帳號。"); return
        self.chosen_repo = slug
        self.config.set("repob_slug", slug)
        self.config.set("setup_done", True)
        self.config.set("repo_slug", slug)
        self.accept()
