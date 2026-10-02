#define MyAppName "Vtuber Live Translator"
#ifndef MyAppVersion
  #error "MyAppVersion must be supplied by scripts/build_release.ps1"
#endif
#define MyAppExeName "VtuberLiveTranslator.exe"

[Setup]
AppId={{D4A3424B-8BE8-49A6-BF7A-C46BE1D2204A}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher=Vtuber Live Translator
DefaultDirName={localappdata}\Programs\VtuberLiveTranslator
DefaultGroupName=Vtuber Live Translator
AllowNoIcons=yes
PrivilegesRequired=lowest
OutputDir=output
OutputBaseFilename=VtuberLiveTranslator-Setup
SetupIconFile=..\assets\app.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no
DisableProgramGroupPage=yes
VersionInfoVersion={#MyAppVersion}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "建立桌面捷徑"; GroupDescription: "其他選項："

[Files]
Source: "..\dist\VtuberLiveTranslator\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Vtuber Live Translator"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\Vtuber Live Translator"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "啟動 Vtuber Live Translator"; Flags: nowait postinstall skipifsilent

[Code]
procedure CurUninstallStepChanged(CurStep: TUninstallStep);
var
  DataPath: String;
begin
  if CurStep = usUninstall then
    RegDeleteValue(HKEY_CURRENT_USER,
      'Software\Microsoft\Windows\CurrentVersion\Run', 'VtuberLiveTranslator');
  if CurStep = usPostUninstall then
  begin
    DataPath := ExpandConstant('{localappdata}\VtuberLiveTranslator');
    if (not UninstallSilent) and DirExists(DataPath) and
       (MsgBox('是否同時刪除預設資料夾中的 Session、模型、設定與記錄？' + #13#10 +
               '自訂 Session 位置不會刪除。選擇「否」會保留全部資料，之後重新安裝仍可繼續使用。',
               mbConfirmation, MB_YESNO) = IDYES) then
      DelTree(DataPath, True, True, True);
  end;
end;
