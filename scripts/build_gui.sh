#!/usr/bin/env bash
# 打包管理 GUI 成跨平台單檔執行檔（在哪個 OS 跑就產哪個平台的）。
#   bash scripts/build_gui.sh
# 產物：dist/TradingAdmin（Linux/Win .exe）或 dist/TradingAdmin.app（macOS）
set -euo pipefail
cd "$(dirname "$0")/.."

echo "▶ 安裝建置相依（PySide6 + PyInstaller）…"
python3 -m pip install -q --upgrade PySide6 pyinstaller

echo "▶ PyInstaller 打包…"
python3 -m PyInstaller admin_gui/admin_gui.spec --noconfirm --clean

# macOS：把 .app 包成可拖曳安裝的 DMG（含 /Applications 捷徑）
if [ "$(uname -s)" = "Darwin" ] && [ -d dist/TradingAdmin.app ]; then
  echo "▶ 產生 DMG…"
  rm -rf dist/dmg_stage dist/TradingAdmin-macOS.dmg
  mkdir -p dist/dmg_stage
  ditto dist/TradingAdmin.app dist/dmg_stage/TradingAdmin.app
  ln -s /Applications dist/dmg_stage/Applications
  hdiutil create -volname "TradingAdmin" -srcfolder dist/dmg_stage \
    -ov -format UDZO dist/TradingAdmin-macOS.dmg >/dev/null
  rm -rf dist/dmg_stage
fi

echo "✅ 完成。產物在 dist/："
ls -lh dist/ 2>/dev/null || true
case "$(uname -s)" in
  Darwin) echo "   macOS：dist/TradingAdmin-macOS.dmg（拖進 Applications；首次右鍵→開啟過 Gatekeeper）" ;;
  Linux)  echo "   Linux：./dist/TradingAdmin" ;;
  *)      echo "   Windows：dist\\TradingAdmin.exe" ;;
esac
