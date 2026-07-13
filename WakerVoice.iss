; WakerVoice — Inno Setup installer
; Cài PER-USER (không cần admin) vào %LOCALAPPDATA%\Programs\WakerVoice, để updater
; (delta) vẫn ghi đè file được mà không cần quyền admin. Bọc bản build onedir hiện có.
; Version truyền từ release.py qua /DMyAppVersion=... ; có default để compile thủ công.

#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif
#define MyAppName "WakerVoice"
#define MyAppExe  "WakerVoice.exe"

[Setup]
; AppId CỐ ĐỊNH — không đổi giữa các phiên bản để nâng cấp/gỡ đúng chỗ.
AppId={{9B3D7A64-1E52-4C8F-AF10-6D2E9C4B7A31}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=tdat-dev
AppPublisherURL=https://github.com/tdat-dev/ByteVoice
DefaultDirName={localappdata}\Programs\{#MyAppName}
DisableProgramGroupPage=yes
DisableDirPage=auto
PrivilegesRequired=lowest
OutputDir=dist
OutputBaseFilename=WakerVoice-v{#MyAppVersion}-setup
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\{#MyAppExe}
UninstallDisplayName={#MyAppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Tự đóng WakerVoice đang chạy khi cài đè / gỡ, rồi mở lại sau.
CloseApplications=yes
RestartApplications=yes

[Tasks]
Name: "desktopicon"; Description: "Tạo lối tắt ngoài Desktop"; GroupDescription: "Lối tắt:"
Name: "startup"; Description: "Chạy WakerVoice khi khởi động Windows"; GroupDescription: "Tùy chọn:"; Flags: unchecked

[Files]
Source: "dist\WakerVoice\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"
Name: "{autodesktop}\{#MyAppName}";  Filename: "{app}\{#MyAppExe}"; Tasks: desktopicon

[Registry]
; Chạy cùng Windows (chỉ khi user tick) — cùng khoá HKCU\Run app tự quản ở khay.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; \
  ValueName: "WakerVoice"; ValueData: """{app}\{#MyAppExe}"""; Flags: uninsdeletevalue; Tasks: startup

[Run]
Filename: "{app}\{#MyAppExe}"; Description: "Mở WakerVoice ngay"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Xoá luôn các file updater tải thêm về sau khi gỡ.
Type: filesandordirs; Name: "{app}"
