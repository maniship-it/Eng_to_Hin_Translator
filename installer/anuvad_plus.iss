; Inno Setup script for Anuvad Plus.
;
; Produces AnuvadPlusSetup.exe -- a single installer that can be carried to any
; offline Windows PC. It installs the frozen application, the translation model
; and the dictionary, and installs Microsoft's C++ runtime only if the machine
; turns out to need it.
;
; Build it (on Windows, after PyInstaller has produced dist\AnuvadPlus):
;     "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer\anuvad_plus.iss
;
; scripts\Build Installer.bat does the whole sequence for you.

#define AppName        "Anuvad Plus"
#define AppVersion     "1.1.0"
#define AppPublisher   "Anuvad Plus"
#define AppExeName     "AnuvadPlus.exe"
#define SourceDir      "..\dist\AnuvadPlus"

[Setup]
AppId={{8E3A7F2C-4D51-4B7A-9C21-5F0B6D8A1E93}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=AnuvadPlusSetup
SetupIconFile=anuvad.ico
UninstallDisplayIcon={app}\{#AppExeName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern

; Installing per-user needs no administrator rights, which matters on a
; managed office PC. The user may still choose an all-users install.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

; The model and dictionary make this a large payload; refuse to start if the
; disk cannot hold it rather than failing halfway through.
ExtraDiskSpaceRequired=0

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; \
    GroupDescription: "Shortcuts:"

[Files]
; The frozen application, the model and the dictionary.
Source: "{#SourceDir}\*"; DestDir: "{app}"; \
    Flags: ignoreversion recursesubdirs createallsubdirs

; Documentation, kept beside the program so it can be found later.
Source: "..\INSTALLATION.md"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
Source: "..\README.md";       DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
Source: "..\LICENSE";         DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist

; Microsoft's C++ runtime, unpacked only when this PC actually lacks it.
Source: "vc_redist.x64.exe"; DestDir: "{tmp}"; \
    Flags: deleteafterinstall skipifsourcedoesntexist; Check: NeedsVCRedist

[Icons]
Name: "{group}\{#AppName}";                Filename: "{app}\{#AppExeName}"
Name: "{group}\Uninstall {#AppName}";      Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}";          Filename: "{app}\{#AppExeName}"; \
    Tasks: desktopicon

[Run]
; Install the runtime first, silently, if it is missing.
Filename: "{tmp}\vc_redist.x64.exe"; \
    Parameters: "/install /quiet /norestart"; \
    StatusMsg: "Installing the Microsoft C++ runtime (one time only)..."; \
    Flags: waituntilterminated skipifdoesntexist; Check: NeedsVCRedist

Filename: "{app}\{#AppExeName}"; \
    Description: "Start {#AppName} now"; \
    Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Settings written at run time; the installer did not create these.
Type: filesandordirs; Name: "{localappdata}\AnuvadPlus"

[Code]
function NeedsVCRedist: Boolean;
{ CTranslate2 links against these two libraries. Python does not provide them,
  and a freshly imaged PC may not have them, so check for the files rather
  than guessing from a registry key that varies by runtime version. }
begin
  Result := (not FileExists(ExpandConstant('{sys}\msvcp140.dll'))) or
            (not FileExists(ExpandConstant('{sys}\vcruntime140_1.dll')));
end;

function InitializeSetup: Boolean;
begin
  Result := True;
end;
