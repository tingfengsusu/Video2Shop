; ─────────────────────────────────────────────────────────────────
;  Video2Shop — Inno Setup installer script
;
;  Usage:
;    1. Install Inno Setup: https://jrsoftware.org/isinfo.php
;    2. Run a build first: scripts\build.bat
;    3. Open this file in Inno Setup Compiler, or run:
;       "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" scripts\setup.iss
;
;  The installer bundles dist\Video2Shop\ into a proper Windows setup.
; ─────────────────────────────────────────────────────────────────

#define AppName    "Video2Shop"
#define AppVersion ReadIni("scripts\build.ini", "version", "value", "1.0.0")
#define AppExeName "Video2Shop.exe"
#define AppPublisher "tingfengsusu"
#define AppURL "https://github.com/tingfengsusu/Video2Shop"

[Setup]
AppId={{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}
AppUpdatesURL={#AppURL}

DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
AllowNoIcons=yes

; Use the onedir output from PyInstaller
SourceDir=..

OutputDir=.
OutputBaseFilename=Video2Shop_Setup_v{#AppVersion}

Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern

; Require 64-bit Windows (Python/PyInstaller produces 64-bit exe)
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop icon"; GroupDescription: "Additional icons:"
Name: "desktopicon\common"; Description: "For all users"; GroupDescription: "Additional icons:"; Flags: exclusive

[Files]
; Bundle the entire onedir output
Source: "dist\Video2Shop\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent
