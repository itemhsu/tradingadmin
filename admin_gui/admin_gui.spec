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

a = Analysis(
    [str(ROOT / "admin_gui" / "app.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[],
    hiddenimports=[
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

exe = EXE(
    pyz, a.scripts, a.binaries, a.zipfiles, a.datas, [],
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

# macOS 產出 .app bundle
if sys.platform == "darwin":
    app = BUNDLE(
        exe,
        name="TradingAdmin.app",
        icon=None,
        bundle_identifier="com.itemhsu.tradingadmin",
    )
