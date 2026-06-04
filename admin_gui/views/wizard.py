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

    def _refresh_status(self):
        from admin_gui.services import engine_release as er
        if not self.user_edit.text().strip():
            self._set_done(self.repob_row, False, "")
            self._set_done(self.engine_row, False, "")
            return
        repob = self._repob_slug()
        u = self.user_edit.text().strip()
        dash  = f"{u}/tech-rebalance-dashboard"
        # 建立交易系統：兩個 repo 都要存在才算完成
        repob_ok = (_gh(["api", f"repos/{repob}", "--jq", ".full_name"])[0] == 0)
        dash_ok  = (_gh(["api", f"repos/{dash}",  "--jq", ".full_name"])[0] == 0)
        both_ok  = repob_ok and dash_ok
        if both_ok:
            note = f"已建立 · {repob.split('/')[-1]} + dashboard"
        elif repob_ok:
            note = f"已建立 {repob.split('/')[-1]}，尚缺 dashboard repo"
        elif dash_ok:
            note = f"已建立 dashboard，尚缺 {repob.split('/')[-1]}"
        else:
            note = ""
        self._set_done(self.repob_row, both_ok, note)
        exists = repob_ok   # 引擎檢查只需要 Repo B
        # 更新引擎：掃 Repo B 的所有 workflow 檔，找到 git+ pin 即可
        # （workflow 名稱不固定：daily.yml / daily_all_accounts.yml 等都接受）
        if not exists:
            self._set_done(self.engine_row, False, "")
            self.engine_row["status"].setText("（先建立交易系統）")
            return
        import base64 as _b64
        pinned = None
        # 1. 列出 .github/workflows/
        cw, wf_list, _ = _gh(["api",
            f"repos/{repob}/contents/.github/workflows", "--jq", "[.[].name]"])
        wf_names = []
        if cw == 0 and wf_list:
            try:
                import json as _json
                wf_names = _json.loads(wf_list)
            except Exception:  # noqa: BLE001
                wf_names = []
        # 2. 逐一讀取，找到含 git+ pin 的那個
        for wfn in wf_names:
            c2, content, _ = _gh(["api",
                f"repos/{repob}/contents/.github/workflows/{wfn}", "--jq", ".content"])
            if c2 == 0 and content:
                try:
                    text = _b64.b64decode(content).decode("utf-8")
                    p = er.pinned_git_version(text)
                    if p:
                        pinned = p
                        break
                except Exception:  # noqa: BLE001
                    continue
        versions = er.list_versions(_ENGINE_REPO)
        latest = versions[0] if versions else None
        up_to_date = bool(pinned and latest and pinned.lstrip("v") == latest.lstrip("v"))
        # note 永不空白：四種情況都給明確說明
        if up_to_date:
            note = f"已是最新 {pinned}"
        elif pinned and latest:
            note = f"可更新 {pinned}→{latest}"
        elif not pinned:
            note = "未用 git+ 釘版，按「更新」切換為公開引擎"
        else:  # pinned 有、latest 取不到
            note = f"目前 {pinned}（取不到最新版）"
        self._set_done(self.engine_row, up_to_date, note)
        # 「更新引擎」這列：未完成也要顯示狀態（_set_done 預設會清空）
        self.engine_row["status"].setText(note)

    # ── 建立 Repo B + Dashboard（一次兩個，已存在略過）───────────────────
    def _do_build_repob(self):
        import base64 as _b64, json as _json
        from admin_gui.services import engine_release as er
        from admin_gui.services import repo_b_provisioner as pv

        u = self.user_edit.text().strip()
        if not u:
            QMessageBox.warning(self, "缺帳號", "請先填入 GitHub 帳號。"); return
        slug  = self._repob_slug()                         # {user}/tech-rebalance
        dash  = f"{u}/tech-rebalance-dashboard"            # {user}/tech-rebalance-dashboard

        if QMessageBox.question(
                self, "建立交易系統",
                f"將建立：\n"
                f"  • {slug}（private，薄殼 Repo B）\n"
                f"  • {dash}（public，GitHub Pages Dashboard）\n"
                "已存在的 repo 會略過。要繼續嗎？"
        ) != QMessageBox.Yes:
            return

        versions = er.list_versions(_ENGINE_REPO)
        if not versions:
            QMessageBox.warning(self, "找不到引擎版本",
                                "無法列出公開引擎 Release，請確認 gh 已登入。"); return
        latest = versions[0]

        # ── ① 建 Repo B（薄殼，private）──────────────────────────────
        files = pv.build_template_files(latest)
        res = pv.provision(slug, files)
        repob_ok = res["ok"]
        if repob_ok:
            self.config.set("repob_slug", slug)

        # ── ② 建 Dashboard repo（public，GitHub Pages）+ 複製模板 ──────
        dash_ok = False
        dash_msg = ""
        TEMPLATE_REPO = "itemhsu/tech-rebalance-dashboard"
        # 需要複製的檔案（從 template repo 複製到用戶 dashboard repo）
        SEED_FILES = [
            "mvp_dashboard.html",          # 個人 NAV 看板
            ".nojekyll",                   # GitHub Pages 不用 Jekyll
            "momentum/index.html",         # 回測分析 SPA（讀 pub engine results/）
        ]
        INDEX_HTML = (
            "<!DOCTYPE html><html><head><meta charset='utf-8'>"
            f"<title>{u} Trading Dashboard</title>"
            "<meta http-equiv='refresh' content='0;url=mvp_dashboard.html'>"
            "</head><body><a href='mvp_dashboard.html'>前往 Dashboard</a></body></html>"
        )
        # 建 repo（已存在 → 繼續）
        rc = _gh(["repo", "create", dash, "--public"])[0]
        dash_existed = (rc != 0)
        if rc == 0 or dash_existed:
            # index.html：redirect 到 mvp_dashboard.html
            def _put_file(path, content_bytes, msg):
                cs, sha_raw, _ = _gh(["api", f"repos/{dash}/contents/{path}", "--jq", ".sha"])
                p = {"message": msg, "content": _b64.b64encode(content_bytes).decode()}
                if cs == 0 and sha_raw.strip():
                    p["sha"] = sha_raw.strip()
                _gh(["api", "-X", "PUT", f"repos/{dash}/contents/{path}", "--input", "-"],
                    inp=_json.dumps(p))

            _put_file("index.html", INDEX_HTML.encode(), "init: dashboard index")
            _put_file(".nojekyll", b"", "init: disable jekyll")

            # 從 template repo 複製核心 HTML 檔案
            for fpath in ["mvp_dashboard.html", "momentum/index.html"]:
                cr, content_b64, _ = _gh(["api",
                    f"repos/{TEMPLATE_REPO}/contents/{fpath}", "--jq", ".content"])
                if cr == 0 and content_b64.strip():
                    raw_bytes = _b64.b64decode(content_b64.replace("\n", ""))
                    _put_file(fpath, raw_bytes, f"init: seed {fpath} from template")

            # 啟用 GitHub Pages（main 分支根目錄）
            pages_payload = _json.dumps({"source": {"branch": "main", "path": "/"}})
            cp, _, ep = _gh(["api", "-X", "POST",
                             f"repos/{dash}/pages", "--input", "-"],
                            inp=pages_payload)
            dash_ok = cp == 0 or "already" in ep.lower() or "409" in ep
            dash_msg = "已啟用" if dash_ok else f"Pages 啟用失敗（{ep[:60]}）"
        else:
            dash_msg = "建立失敗"

        # ── 結果摘要 ──────────────────────────────────────────────────
        repob_status = "✅ 已建立" if repob_ok else "⚠ 部分失敗（見下方）"
        dash_status  = f"✅ {dash_msg}" if dash_ok else f"⚠ {dash_msg}"
        QMessageBox.information(self, "建立完成",
            f"Repo B：{repob_status}\n"
            f"Dashboard：{dash_status}\n\n"
            f"下一步：\n"
            f"1. 到 {slug} Settings → Secrets 設 Alpaca 金鑰\n"
            f"2. Dashboard URL：https://{u}.github.io/tech-rebalance-dashboard/")
        self._refresh_status()

    # ── 更新引擎版本 ─────────────────────────────────────────────────────
    def _do_update_engine(self):
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
