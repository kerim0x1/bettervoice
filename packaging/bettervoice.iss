; The BetterVoice installer, for Inno Setup 6.7 or newer.
;
; scripts/build.py compiles it and passes the version, the app folder and the
; wizard images, which it renders from the mark:
;
;     python scripts/build.py --installer
;
; BetterVoice installs per user, into %LOCALAPPDATA%\Programs\BetterVoice:
; no administrator rights, and updates install over it in place. Settings, keys
; and models live in %APPDATA%\BetterVoice; the uninstaller removes them only
; when the user asks it to.

#if VER < EncodeVer(6, 7, 0)
  #error BetterVoice's installer needs Inno Setup 6.7 or newer
#endif
#ifndef AppVersion
  #error Compile the installer with scripts/build.py --installer
#endif

[Setup]
; Windows knows the installed app by this ID: never change it
AppId={{BC2A7FF9-4D01-4C91-93D9-112B4EA5839F}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
AppUpdatesURL={#AppURL}/releases
AppCopyright=Copyright (c) 2026 {#AppName} contributors
VersionInfoVersion={#FileVersion}
VersionInfoTextVersion={#AppVersion}
VersionInfoProductName={#AppName}
VersionInfoProductVersion={#FileVersion}
VersionInfoProductTextVersion={#AppVersion}
VersionInfoCompany={#AppPublisher}
VersionInfoDescription={#AppName} Setup
; per user, like autostart and the settings: no UAC prompt
PrivilegesRequired=lowest
DefaultDirName={autopf}\{#AppName}
DisableProgramGroupPage=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
; the app holds this mutex while it runs (src/bettervoice/app.py): Setup and
; Uninstall ask to quit it first
AppMutex=BetterVoice.SingleInstance
SetupMutex=BetterVoice.Setup
UninstallDisplayName={#AppName}
UninstallDisplayIcon={app}\{#AppName}.exe
SetupIconFile={#IconFile}
OutputDir={#OutputDir}
OutputBaseFilename={#OutputName}
Compression=lzma2/max
SolidCompression=yes
; dark like the app: near-black pages, the mark on the last page and in the
; page headers
WizardStyle=modern dark hidebevels
WizardBackColor={#BackColor}
WizardImageFile={#WizardImages}
WizardSmallImageFile={#WizardSmallImages}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Messages]
; also the title of the question about settings and models
UninstallAppTitle={#AppName} Uninstall
FinishedLabel=Setup has finished installing [name] on your computer.%n%nPress Win+O in any app to start dictating, and Win+O again to stop. [name] runs in the notification area of the taskbar.

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[InstallDelete]
; the previous version's libraries: an update must not mix old and new ones
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "{#AppDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppName}.exe"; Comment: "{#AppTagline}"; AppUserModelID: "{#AppUserModelID}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppName}.exe"; Comment: "{#AppTagline}"; AppUserModelID: "{#AppUserModelID}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppName}.exe"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[Code]
const
  RunKey = 'Software\Microsoft\Windows\CurrentVersion\Run';

function StartsThisInstallation(Command: String): Boolean;
begin
  Result := Pos(Lowercase(ExpandConstant('{app}\')), Lowercase(Command)) > 0;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  // with "Start with Windows" on, start this installation from now on, not
  // a copy it replaces (for example an unzipped one)
  if (CurStep = ssPostInstall) and RegValueExists(HKCU, RunKey, '{#AppName}') then
    RegWriteStringValue(HKCU, RunKey, '{#AppName}', '"' + ExpandConstant('{app}\{#AppName}.exe') + '"');
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Command, DataDir: String;
begin
  if CurUninstallStep = usUninstall then
  begin
    // "Start with Windows" must not outlive the app it starts
    if RegQueryStringValue(HKCU, RunKey, '{#AppName}', Command) and StartsThisInstallation(Command) then
      RegDeleteValue(HKCU, RunKey, '{#AppName}');
  end
  else if CurUninstallStep = usPostUninstall then
  begin
    DataDir := ExpandConstant('{userappdata}\{#AppName}');
    if DirExists(DataDir) and not UninstallSilent and
       (MsgBox('Also delete your {#AppName} settings, API keys and downloaded models?' + #13#10#13#10 +
               'They are in ' + DataDir + '. Keep them to continue where you left off ' +
               'if you install {#AppName} again.', mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES) then
      DelTree(DataDir, True, True, True);
  end;
end;
