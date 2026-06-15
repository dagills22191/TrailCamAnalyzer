; Inno Setup script for TrailCam Sorter
; Requires: Inno Setup 6+ (https://jrsoftware.org/isinfo.php)
; Run after PyInstaller build:
;   "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer\setup.iss
; Output: installer\output\TrailCamSorter-Setup.exe

#define AppName "TrailCam Sorter"
#define AppVersion "1.3.0"
#define AppPublisher "dagills22191"
#define AppURL "https://github.com/dagills22191/TrailCamAnalyzer"
#define AppExeName "TrailCamSorter.exe"
#define SourceDir "..\dist\TrailCamSorter"

[Setup]
AppId={{A7E3F2D1-4B8C-4F9A-B2E1-3C7D5F9A1B2E}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}
AppUpdatesURL={#AppURL}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
OutputDir=output
OutputBaseFilename=TrailCamSorter-Setup
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
; First-run model download needs ~1 GB free beyond the install itself
ExtraDiskSpaceRequired=1073741824

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Remove the downloaded model weights cache on uninstall (optional — comment out to keep)
; Type: filesandordirs; Name: "{usercf}\.cache\kagglehub"
