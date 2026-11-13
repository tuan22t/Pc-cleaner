; Windows installer for PC Cleaner (Inno Setup 6).
;   iscc /DAppVersion=0.6.0 packaging\windows\pccleaner.iss
; Installs for the current user only (no administrator rights), into
; %LOCALAPPDATA%\Programs\PC Cleaner. The user's data and quarantine live
; elsewhere (%LOCALAPPDATA%\PCCleaner) and are never touched by installing,
; updating or uninstalling.
; AppId must never change: it is how an update finds the installed copy.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef AppName
  #define AppName "PC Cleaner"
#endif
#define AppExe "PCCleaner.exe"
#define DataFolder "PCCleaner"

[Setup]
AppId={{074F03C3-C7A9-4ED8-8B17-00E16E39E917}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppName}
VersionInfoVersion={#AppVersion}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\..\dist
OutputBaseFilename=PCCleaner-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
CloseApplications=yes
RestartApplications=no
MinVersion=10.0
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
#ifdef SignCommand
SignTool=pcc
SignedUninstaller=yes
#endif

[Languages]
Name: "en"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\..\dist\PCCleaner\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; An update replaces the program files completely, so no file of an older version lingers.
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
; After an update started from inside the app (/relaunch=1), open the app again.
Filename: "{app}\{#AppExe}"; Flags: nowait; Check: Relaunch

[UninstallRun]
; Take the scheduled cleanup task off Task Scheduler before the program goes.
Filename: "{app}\{#AppExe}"; Parameters: "--before-uninstall"; Flags: runhidden waituntilterminated; RunOnceId: "RemoveSchedule"

[UninstallDelete]
; Only the program folder. The data folder (scan results, log, quarantine) stays.
Type: filesandordirs; Name: "{app}"

[Code]
function Relaunch(): Boolean;
begin
  Result := WizardSilent() and (ExpandConstant('{param:relaunch|0}') = '1');
end;

function InitializeUninstall(): Boolean;
var
  Data: String;
begin
  Result := True;
  Data := ExpandConstant('{localappdata}\{#DataFolder}');
  if DirExists(Data) and not UninstallSilent() then
    MsgBox('The program will be removed. Your data and any files still in quarantine are kept in:' + #13#10 + Data + #13#10#13#10 +
           'To get files back from quarantine, open the app and click Restore before uninstalling.' + #13#10 +
           'Startup programs you turned off stay off.',
           mbInformation, MB_OK);
end;
