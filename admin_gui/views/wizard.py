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
        # 建立交易系統：Repo B 是否已存在
        exists = (_gh(["api", f"repos/{repob}", "--jq", ".full_name"])[0] == 0)
        name = repob.split("/")[-1]
        self._set_done(self.repob_row, exists, f"已建立 · {name}")
        # 更新引擎：讀 Repo B 的 daily.yml 現釘版本 vs 公開引擎最新版
        if not exists:
            self._set_done(self.engine_row, False, "")
            self.engine_row["status"].setText("（先建立交易系統）")
            return
        c2, content, _ = _gh(["api",
            f"repos/{repob}/contents/.github/workflows/daily.yml", "--jq", ".content"])
        pinned = None
        if c2 == 0 and content:
            import base64 as _b64
            try:
                pinned = er.pinned_git_version(_b64.b64decode(content).decode("utf-8"))
            except Exception:  # noqa: BLE001
                pinned = None
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

    # ── 建立 Repo B（兩 repo 薄殼）───────────────────────────────────────
    def _do_build_repob(self):
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
        slug = self._repob_slug()
        if not slug:
            QMessageBox.warning(self, "缺帳號", "請填入你的 GitHub 帳號。"); return
        self.chosen_repo = slug
        self.config.set("repob_slug", slug)
        self.config.set("setup_done", True)
        self.config.set("repo_slug", slug)
        self.accept()
