# TradingAdmin — 交易系統管理控制台（桌面 GUI）

跨平台桌面 App，用來管理你的自動交易系統帳戶 —— 新增/編輯帳戶、設定券商
金鑰、編輯 cron 排程、查看操作與排程日誌。

**純 API 模式**：全程透過 GitHub API（`gh` CLI）讀寫你私有 repo 裡的
`accounts.json` / workflow yml 與資料檔，**不需要 clone 任何代碼到本機、
本機也不存任何密鑰**（金鑰寫進 GitHub Secrets）。

> 搭配的交易引擎（每日 GitHub Actions 自動執行）放在你自己的私有 repo；
> 這個公開 repo 只含「管理用的桌面 App」原始碼與安裝檔。

---

## 📥 下載（macOS）

到 **[Releases](../../releases/latest)** 下載 `TradingAdmin-macOS.dmg`。

1. 開啟 `.dmg`，把 `TradingAdmin.app` 拖進 `Applications`
2. 首次開啟：對 App **右鍵 → 開啟**（未經 Apple 公證，直接雙擊會被 Gatekeeper 擋）
3. 首次啟動精靈：① `gh auth login` 登入 GitHub ② 指定要管理的 repo（`owner/repo`）

### 需求
- [GitHub CLI](https://cli.github.com/)：`brew install gh`，並 `gh auth login`
  （App 啟動會自動把 Homebrew 等路徑補進 PATH，從 Finder/DMG 開也找得到 `gh`）
- 對目標 repo 有寫入權限

---

## 🛠️ 從原始碼執行 / 自行打包

```bash
pip install -r requirements-gui.txt

# 直接執行
python -m admin_gui.app                       # 用 config 記住的 repo
python -m admin_gui.app owner/repo            # 指定 repo

# 跑測試（需要 PySide6；無 PySide6 會自動 skip GUI 冒煙測試）
QT_QPA_PLATFORM=offscreen python -m pytest tests/admin_gui -q

# 打包（macOS 會額外輸出 dist/TradingAdmin-macOS.dmg）
bash scripts/build_gui.sh
```

---

## 🏗️ 架構

| 層 | 內容 |
|---|---|
| `admin_gui/views/` | 4 個分頁：總覽（全域設定）/ 帳戶 / 排程 / 日誌（PySide6） |
| `admin_gui/services/` | 純邏輯（可單測）：`repo_store`（GitHub Contents API 後端）、`accounts_repo`、`catalog`、`cron_editor`、`probes`（schema 驅動的券商連線測試）、`gh_client`（Secrets）等 |
| `admin_gui/models/` | 帳戶資料驗證 |
| `brokers/*.json` | 券商連線 schema（base_url / headers / 餘額路徑）；新增券商＝寫 JSON，0 行 Python |
| `accounts.json` | **範例**帳戶清單（本 repo 內為消毒過的 sample；實際資料在你的私有 repo） |

新增一家 REST 券商：只要在 `brokers/` 放一份 schema JSON（參考 `alpaca.json` /
`tradier.json`），App 就能用它測試連線、引擎也能用它下單。

---

## 🔒 安全

- App 不在本機保存任何密鑰；API 金鑰由你在對話框輸入後直接寫入 **GitHub Secrets**。
- 設定檔（`accounts.json`、workflow yml）透過 GitHub API 直接 commit 回你的 repo。
- 本 repo 內的 `accounts.json` 為**範例**，不含任何真實帳戶或憑證。
