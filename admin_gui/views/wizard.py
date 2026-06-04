"""admin_gui/views/wizard.py — 啟動精靈 v2（引導式一鍵設定）。

五步（對應計劃書 W-1~W-7）：
  ① gh 登入　② Fork 範本（設為 private）　③ 確認帳號　⑥ 啟用 Pages　⑦ 啟用 Actions
使用者只輸入「GitHub 帳號」，內部自動組成 {帳號}/tech-rebalance；不顯示/不要求完整 owner/repo。
⑥⑦ 一鍵冪等：已完成顯示 ✅、可安全重按。精靈每次啟動都顯示、保留「略過」。
不處理也不提示 Email 密碼（總覽分頁）與帳戶（帳戶分頁）。
"""
from __future__ import annotations

import json
import subprocess

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QMessageBox, QWidget,
)

from admin_gui.services.probes import probe_gh
from admin_gui.services.global_config import GlobalConfig

# 內部常數：範本與倉庫名不顯示給使用者
_TEMPLATE = "itemhsu/tech-rebalance"
_REPO_NAME = _TEMPLATE.split("/")[-1]
# 線上儀表板（Pages）在「另一個 public repo」，不是引擎 repo
_DASHBOARD_REPO = "tech-rebalance-dashboard"
# 兩 repo 架構：使用者的薄殼 Repo B（設定+資料，引擎以 git+ 從公開 repo 安裝，免 token）
_REPOB_NAME = "tech-rebalance-data"
_ENGINE_REPO = "itemhsu/tech-rebalance-pub"


def is_first_run(config: GlobalConfig) -> bool:
    """保留供相容；app 現在每次啟動都顯示精靈（W-1）。"""
    return not config.load().get("setup_done", False)


def _gh(args, inp=None, timeout=60):
    try:
        r = subprocess.run(["gh", *args], capture_output=True, text=True,
                           input=inp, timeout=timeout)
        return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()
    except Exception as e:  # noqa: BLE001
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

        # 舊 fork 模式步驟
        self.fork_row = self._step_row(lay, "你的交易系統（從範本 Fork，私有）", "一鍵 Fork", self._do_fork)
        self.pages_row = self._step_row(lay, "啟用線上儀表板（GitHub Pages）", "啟用", self._do_pages)
        self.actions_row = self._step_row(lay, "啟用每日自動執行（GitHub Actions）", "啟用", self._do_actions)
        # 從上游同步引擎（拉取修復；經 GitHub Sync fork API，不需 clone）
        self.sync_row = self._step_row(lay, "從上游同步引擎（拉取最新修復）", "同步", self._do_sync_upstream)
        # 兩 repo 架構（新）：建立薄殼 Repo B + 更新引擎版本
        self.repob_row = self._step_row(lay, "建立交易系統（兩 repo 薄殼）", "建立", self._do_build_repob)
        self.engine_row = self._step_row(lay, "更新引擎版本", "更新", self._do_update_engine)

        refresh_btn = QPushButton("↻ 重新檢查狀態")
        # 依偵測到的模式顯示對應步驟（fork / repo_b）；預設先全顯，refresh 時再收斂
        self._fork_rows = [self.fork_row, self.pages_row, self.actions_row, self.sync_row]
        self._repob_rows = [self.repob_row, self.engine_row]
        refresh_btn.clicked.connect(self._refresh_status)
        lay.addWidget(refresh_btn)

        lay.addStretch()
        brow = QWidget(); bl = QHBoxLayout(brow)
        skip = QPushButton("略過"); skip.clicked.connect(self.reject)
        done = QPushButton("完成，開始使用 →"); done.clicked.connect(self._finish)
        bl.addWidget(skip); bl.addStretch(); bl.addWidget(done)
        lay.addWidget(brow)

        self._refresh_gh()

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

    def _apply_mode(self, mode):
        """依模式顯示對應步驟。

        兩-repo 是預設路線：只有「明確偵測到 fork」(repo 內含引擎碼) 才顯示舊
        fork 步驟；repo_b 與 unknown 一律只顯示新的兩-repo 步驟，避免兩套心智
        模型同畫面混搭。
        """
        from admin_gui.services import mode_detect as md
        is_fork = (mode == md.FORK)
        for r in self._fork_rows:
            r["widget"].setVisible(is_fork)
        for r in self._repob_rows:
            r["widget"].setVisible(not is_fork)

    def _initial_user(self) -> str:
        slug = self.config.get("repo_slug")
        if slug and "/" in slug:
            return slug.split("/")[0]
        return ""

    def _managed_slug(self) -> str:
        u = self.user_edit.text().strip()
        return f"{u}/{_REPO_NAME}" if u else ""

    def _dashboard_slug(self) -> str:
        """線上儀表板的 repo（public，Pages 在這裡，不是引擎 repo）。"""
        u = self.user_edit.text().strip()
        return f"{u}/{_DASHBOARD_REPO}" if u else ""

    def _repob_slug(self) -> str:
        """兩 repo 架構：使用者的薄殼 Repo B（設定+資料）。"""
        u = self.user_edit.text().strip()
        return f"{u}/{_REPOB_NAME}" if u else ""

    # ── ① gh 登入 ─────────────────────────────────────────────────────
    def _refresh_gh(self):
        ok, msg = probe_gh()
        self.gh_lbl.setText(("✅ " if ok else "❌ ") + "GitHub 登入：" + msg)
        if ok and not self.user_edit.text().strip():
            self._detect_user()

    def _detect_user(self):
        code, out, _ = _gh(["api", "user", "--jq", ".login"])
        if code == 0 and out:
            self.user_edit.setText(out)

    def _gh_login(self):
        try:
            subprocess.Popen(["gh", "auth", "login", "--web"])
            QMessageBox.information(self, "授權中",
                "已開啟 gh 登入流程，請依指示完成後回來按「↻ 重新檢查狀態」。")
        except FileNotFoundError:
            QMessageBox.warning(self, "找不到 gh", "請先安裝 GitHub CLI（gh）。")
        self._refresh_gh()

    # ── 狀態檢查（冪等防呆）─────────────────────────────────────────────
    def _set_done(self, row: dict, done: bool, done_text: str):
        row["icon"].setText("✅" if done else "⬜")
        row["status"].setText(done_text if done else "")
        row["btn"].setEnabled(not done)
        row["btn"].setText(("✅ 已完成" if done else row["action"]))

    def _detect_mode(self) -> str:
        """偵測使用者目前在哪條路線（repo_b 薄殼 / fork / 未知）。

        先看薄殼 Repo B（tech-rebalance-data）是否已是薄殼；否則看 fork repo
        是否含引擎碼。任何 gh 失敗都退回 unknown（精靈全顯，安全預設）。
        """
        from admin_gui.services import mode_detect as md
        try:
            from admin_gui.services.repo_store import GhContentsStore
        except Exception:  # noqa: BLE001
            return md.UNKNOWN
        repob = self._repob_slug()
        if repob:
            m = md.detect_mode(GhContentsStore(repob))
            if m == md.REPO_B:
                return md.REPO_B
        fork = self._managed_slug()
        if fork:
            return md.detect_mode(GhContentsStore(fork))
        return md.UNKNOWN

    def _refresh_status(self):
        from admin_gui.services import mode_detect as md
        slug = self._managed_slug()
        if not slug:
            for row in (self.fork_row, self.pages_row, self.actions_row):
                self._set_done(row, False, "")
            self._apply_mode(md.UNKNOWN)
            return
        # Fork：repo 是否已存在
        code, _, _ = _gh(["api", f"repos/{slug}", "--jq", ".full_name"])
        self._set_done(self.fork_row, code == 0, "已有（私有）")
        # Pages —— 檢查「儀表板 repo」（非引擎 repo）
        dash = self._dashboard_slug()
        code, _, _ = _gh(["api", f"repos/{dash}/pages"]) if dash else (1, "", "")
        self._set_done(self.pages_row, code == 0, "已啟用")
        # Actions
        code, out, _ = _gh(["api", f"repos/{slug}/actions/permissions", "--jq", ".enabled"])
        self._set_done(self.actions_row, code == 0 and out == "true", "已啟用")
        # 依偵測到的模式收斂顯示哪幾個步驟（fork vs repo_b）
        self._apply_mode(self._detect_mode())

    # ── ② Fork（並設為 private，W-5）────────────────────────────────────
    def _do_fork(self):
        if not probe_gh()[0]:
            QMessageBox.warning(self, "尚未登入", "請先完成 GitHub 登入。"); return
        self.fork_row["status"].setText("⏳ Fork 中…"); self.repaint()
        code, out, err = _gh(["repo", "fork", _TEMPLATE, "--clone=false"])
        if code != 0 and "already exists" not in (err + out).lower():
            self.fork_row["status"].setText("❌ Fork 失敗")
            QMessageBox.warning(self, "Fork 失敗", (err or out)[:200]); return
        if not self.user_edit.text().strip():
            self._detect_user()
        slug = self._managed_slug()
        # 設為 private（含真錢設定，務必私有）
        ec, _, ee = _gh(["repo", "edit", slug, "--visibility", "private",
                         "--accept-visibility-change-consequences"])
        if ec != 0:
            QMessageBox.warning(self, "請手動設為 Private",
                f"Fork 完成，但自動設私有失敗：{ee[:160]}\n"
                f"請到 GitHub 將 {slug} 設為 Private（含真錢設定）。")
        self._refresh_status()

    # ── ⑥ 啟用 Pages（在儀表板 repo，冪等）──────────────────────────────
    def _do_pages(self):
        dash = self._dashboard_slug()
        if not dash:
            QMessageBox.warning(self, "缺帳號", "請先填入 GitHub 帳號。"); return
        # 儀表板 repo 不存在時提示（需先有 *-dashboard repo）
        if _gh(["api", f"repos/{dash}", "--jq", ".name"])[0] != 0:
            QMessageBox.warning(self, "找不到儀表板 repo",
                f"{dash} 不存在。線上儀表板需要這個 public repo；"
                f"請先建立/取得後再啟用 Pages。")
            return
        payload = json.dumps({"source": {"branch": "main", "path": "/"}})
        code, out, err = _gh(["api", "-X", "POST", f"repos/{dash}/pages",
                             "--input", "-"], inp=payload)
        blob = (err + out).lower()
        if code != 0 and "409" not in blob and "already" not in blob:
            QMessageBox.warning(self, "啟用 Pages 失敗", (err or out)[:200])
        self._refresh_status()

    # ── ⑦ 啟用 Actions（冪等）───────────────────────────────────────────
    def _do_actions(self):
        slug = self._managed_slug()
        if not slug:
            QMessageBox.warning(self, "缺帳號", "請先填入 GitHub 帳號。"); return
        code, out, err = _gh(["api", "-X", "PUT", f"repos/{slug}/actions/permissions",
                             "-F", "enabled=true", "-f", "allowed_actions=all"])
        if code != 0:
            QMessageBox.warning(self, "啟用 Actions 失敗", (err or out)[:200])
        self._refresh_status()

    # ── ⑧ 從上游同步引擎（GitHub Sync fork API，不需 clone）─────────────
    def _do_sync_upstream(self):
        slug = self._managed_slug()
        if not slug:
            QMessageBox.warning(self, "缺帳號", "請先填入 GitHub 帳號。"); return
        if QMessageBox.question(
                self, "從上游同步引擎",
                f"將把上游最新修復合併進你的 {slug}（預設分支 main）。\n"
                "你的 accounts.json / 帳戶資料不會被改動。要繼續嗎？"
        ) != QMessageBox.Yes:
            return
        # GitHub「Sync fork」：POST /repos/{slug}/merge-upstream
        code, out, err = _gh(["api", "-X", "POST", f"repos/{slug}/merge-upstream",
                             "-f", "branch=main"])
        blob = (err + out).lower()
        if code == 0:
            QMessageBox.information(self, "同步完成",
                "已從上游拉取最新修復。若有更新，下次自動執行即套用。")
        elif "409" in blob or "conflict" in blob or "diverg" in blob:
            QMessageBox.warning(self, "需手動處理",
                "你的 fork 與上游分歧，無法自動快轉合併。\n"
                "請在本機執行 scripts/sync_upstream.sh，或在 GitHub 開 PR 解決。")
        else:
            QMessageBox.warning(self, "同步失敗", (err or out)[:200])

    # ── Ⓐ 建立 Repo B（兩 repo 薄殼）─────────────────────────────────────
    def _do_build_repob(self):
        import tempfile
        from pathlib import Path
        from admin_gui.services import engine_release as er
        from admin_gui.services import repo_b_provisioner as pv
        slug = self._repob_slug()
        if not slug:
            QMessageBox.warning(self, "缺帳號", "請先填入 GitHub 帳號。"); return
        if QMessageBox.question(
                self, "建立交易系統",
                f"將建立 private repo {slug}（薄殼：設定+資料；引擎以 git+ 從公開 repo 安裝，免 token）。\n"
                "之後你只需在它的 Settings 設 Alpaca 金鑰。要繼續嗎？"
        ) != QMessageBox.Yes:
            return
        versions = er.list_versions(_ENGINE_REPO)
        if not versions:
            QMessageBox.warning(self, "找不到引擎版本",
                                "無法列出公開引擎 Release，請確認 gh 已登入。"); return
        latest = versions[0]
        files = pv.build_template_files(latest)   # git+ 安裝，不下載 wheel
        res = pv.provision(slug, files)
        if res["ok"]:
            QMessageBox.information(self, "建立完成",
                f"{slug} 已建立（引擎釘 {latest}，git+ 安裝公開引擎）。\n"
                "下一步：到該 repo Settings → Secrets 設 ACC1_ALPACA_KEY / ACC1_ALPACA_SECRET。")
            self.config.set("repob_slug", slug)
        else:
            QMessageBox.warning(self, "部分失敗", res.get("error") or "推檔未全部成功，請重試。")

    # ── Ⓑ 更新引擎版本 ──────────────────────────────────────────────────
    def _do_update_engine(self):
        import base64 as _b64, json as _json
        from admin_gui.services import engine_release as er
        slug = self.config.get("repob_slug") or self._repob_slug()
        if not slug:
            QMessageBox.warning(self, "缺 Repo B", "請先建立交易系統（按「建立」）。"); return
        versions = er.list_versions(_ENGINE_REPO)
        if not versions:
            QMessageBox.warning(self, "找不到引擎版本", "無法列出公開引擎 Release。"); return
        latest = versions[0]
        if QMessageBox.question(
                self, "更新引擎",
                f"將把 {slug} 的引擎更新到 {latest}（改 daily.yml 的 git+ 釘版，免 wheel）。要繼續嗎？") != QMessageBox.Yes:
            return
        # 讀現有 daily.yml → 換 git+ 的 @vX → 推回（只動一個檔）
        code, daily_text, _ = _gh(["api",
            f"repos/{slug}/contents/.github/workflows/daily.yml", "--jq", ".content"])
        if code != 0:
            QMessageBox.warning(self, "讀取失敗", "讀不到 Repo B 的 daily.yml。"); return
        try:
            daily = _b64.b64decode(daily_text).decode("utf-8")
        except Exception:  # noqa: BLE001
            daily = ""
        new_daily = er.bump_git_version(daily, latest)
        path = ".github/workflows/daily.yml"
        c2, meta, _ = _gh(["api", f"repos/{slug}/contents/{path}", "--jq", ".sha"])
        body = {"message": f"update engine → {latest}",
                "content": _b64.b64encode(new_daily.encode()).decode()}
        if c2 == 0 and meta.strip():
            body["sha"] = meta.strip()
        _gh(["api", "-X", "PUT", f"repos/{slug}/contents/{path}", "--input", "-"],
            inp=_json.dumps(body))
        QMessageBox.information(self, "更新完成",
            f"{slug} 的引擎已釘到 {latest}（git+ 安裝，免 token / 免 wheel）。")

    # ── 完成 ──────────────────────────────────────────────────────────
    def _finish(self):
        slug = self._managed_slug()
        if not slug:
            QMessageBox.warning(self, "缺帳號", "請填入你的 GitHub 帳號。"); return
        self.chosen_repo = slug
        self.config.set("setup_done", True)
        self.config.set("repo_slug", slug)
        self.accept()
