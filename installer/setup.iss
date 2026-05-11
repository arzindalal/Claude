; Inno Setup 6 script for ISO 26262 Validation Tool
; Compile with: iscc setup.iss
; Output: installer_output\ISO26262Validator_Setup.exe

#define AppName      "ISO 26262 Validation Tool"
#define AppVersion   "0.4.0"
#define AppPublisher "Your Organization"
#define AppURL       "https://github.com/arzindalal/Claude"
#define AppExeName   "ISO26262Validator.exe"
#define SourceDir    "..\dist\ISO26262Validator"

[Setup]
AppId={{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}
AppUpdatesURL={#AppURL}
DefaultDirName={autopf}\ISO26262Validator
DefaultGroupName={#AppName}
AllowNoIcons=yes
; OutputDir is relative to the location of this .iss file
OutputDir=..\installer_output
OutputBaseFilename=ISO26262Validator_Setup_v{#AppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
; Require Windows 10 or later
MinVersion=10.0
PrivilegesRequired=admin
UninstallDisplayIcon={app}\{#AppExeName}
VersionInfoVersion={#AppVersion}
VersionInfoCompany={#AppPublisher}
VersionInfoDescription={#AppName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; \
      GroupDescription: "Additional icons:"; Flags: unchecked
Name: "quicklaunchicon"; Description: "Create a &Quick Launch shortcut"; \
      GroupDescription: "Additional icons:"; \
      Flags: unchecked; OnlyBelowVersion: 6.1

[Files]
; All PyInstaller output (recursive)
Source: "{#SourceDir}\*"; DestDir: "{app}"; \
        Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}";                     Filename: "{app}\{#AppExeName}"
Name: "{group}\Uninstall {#AppName}";           Filename: "{uninstallexe}"
Name: "{commondesktop}\{#AppName}";             Filename: "{app}\{#AppExeName}"; \
      Tasks: desktopicon
Name: "{userappdata}\Microsoft\Internet Explorer\Quick Launch\{#AppName}"; \
      Filename: "{app}\{#AppExeName}"; Tasks: quicklaunchicon

[Run]
; Offer to launch immediately after install
Filename: "{app}\{#AppExeName}"; \
          Description: "Launch {#AppName} now"; \
          Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Remove log files generated at runtime (user data in %APPDATA% is intentionally kept)
Type: filesandordirs; Name: "{app}\logs"

[Messages]
; Override the finish page message
FinishedLabel=Setup has finished installing [name] on your computer.%n%nThe application will store your requirements database in:%n  %%APPDATA%%\ISO26262Validator%n%nBefore first use, add your Anthropic API key to:%n  %%APPDATA%%\ISO26262Validator\config.env
