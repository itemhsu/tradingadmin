# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — 把管理 GUI 打包成單一執行檔（Mac/Win/Linux）。

打包的是 GUI 本體 + PySide6；交易系統的 repo（brokers/strategies/accounts）
由使用者透過首啟精靈 fork/指定，App 在執行時讀取該 repo（不打包進來）。

建置：
    pip install pyinstaller PySide6
    pyinstaller admin_gui/admin_gui.spec --noconfirm
產物：dist/TradingAdmin（或 .app / .exe）
"""
import sys
from pathlib import Path

block_cipher = None

ROOT = Path.cwd()

# certifi 的 cacert.pem 必須打包進 .app，否則 urllib/SMTP 會
# CERTIFICATE_VERIFY_FAILED（系統找不到 CA）。
try:
    from PyInstaller.utils.hooks import collect_data_files
    _certifi_datas = collect_data_files("certifi")
except Exception:
    _certifi_datas = []

a = Analysis(
    [str(ROOT / "admin_gui" / "app.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=_certifi_datas,
    hiddenimports=[
        "certifi",
        "admin_gui.views.overview_view",
        "admin_gui.views.accounts_view",
        "admin_gui.views.schedule_view",
        "admin_gui.views.log_view",
        "admin_gui.views.wizard",
        "admin_gui.services.probes",
        "admin_gui.services.log_reader",
        "admin_gui.services.audit_log",
        "admin_gui.services.global_config",
        "admin_gui.services.account_factory",
        "admin_gui.services.accounts_repo",
        "admin_gui.services.catalog",
        "admin_gui.services.state_reader",
        "admin_gui.services.gh_client",
        "admin_gui.services.cron_editor",
        "admin_gui.services.repo_store",
        "admin_gui.services.env_fix",
        "admin_gui.services.secrets_audit",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "numpy", "pandas", "yfinance"],
    cipher=block_cipher,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# ── onedir 模式（關鍵效能修正）─────────────────────────────────────────────
# 原本是 onefile（EXE 直接吃 a.binaries/a.zipfiles/a.datas）：每次啟動 PyInstaller
# bootloader 都要把整包 ~37MB（含整個 Qt）解壓到暫存 _MEIxxxx 才能跑 Python，
# 這段發生在我們任何程式碼之前，無法用 splash 遮掉 —— 正是「啟動等 7~8 秒」的元兇。
# 改 onedir：exclude_binaries=True + COLLECT，檔案在 .app 內只攤平一次，
# 之後每次啟動不再解壓，秒開。
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,   # ← onedir：binaries 交給 COLLECT，不塞進單檔
    name="TradingAdmin",
    debug=False,
    strip=False,
    upx=False,
    console=False,           # GUI app，不開終端機視窗
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe, a.binaries, a.zipfiles, a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="TradingAdmin",
)

# macOS 產出 .app bundle（包 onedir 的 COLLECT 結果）
if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="TradingAdmin.app",
        icon=None,
        bundle_identifier="com.itemhsu.tradingadmin",
    )
