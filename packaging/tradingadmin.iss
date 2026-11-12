; packaging/tradingadmin.iss — Inno Setup 安裝程式（包 PyInstaller onedir 資料夾）。做法沿用 TopRacer-console。
; 版本由 CI 注入：ISCC /DMyAppVersion=0.4.41 packaging\tradingadmin.iss（本機無參數時 0.0.0）
#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif

[Setup]
; 固定 AppId → 新版就地升級（同一個解除安裝項目），不會並存兩份。永遠不要改這個 GUID。
AppId={{3C1DD55F-7F81-4BE9-A728-4DD5016DB37C}
AppName=TradingAdmin
AppVersion={#MyAppVersion}
AppPublisher=itemhsu
DefaultDirName={autopf}\TradingAdmin
DefaultGroupName=TradingAdmin
DisableProgramGroupPage=yes
; 只裝目前使用者（%LocalAppData%\Programs），不跳 UAC，每次升級位置一致。
PrivilegesRequired=lowest
; 升級時若 App 正在跑先關掉，否則 TradingAdmin.exe 被鎖住、舊檔留著。
CloseApplications=yes
RestartApplications=no
OutputDir=..\installer
OutputBaseFilename=TradingAdmin-Windows-Setup
Compression=lzma2/fast
SolidCompression=no
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\TradingAdmin.exe

[Files]
Source: "..\dist\TradingAdmin\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\TradingAdmin"; Filename: "{app}\TradingAdmin.exe"
Name: "{autodesktop}\TradingAdmin"; Filename: "{app}\TradingAdmin.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "建立桌面捷徑"; GroupDescription: "捷徑："

[Run]
Filename: "{app}\TradingAdmin.exe"; Description: "啟動 TradingAdmin"; Flags: nowait postinstall skipifsilent
