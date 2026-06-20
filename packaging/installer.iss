#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif

[Setup]
AppName=YouTube Content Manager
AppVersion={#AppVersion}
DefaultDirName={autopf}\YouTubeContentManager
DefaultGroupName=YouTube Content Manager
OutputDir=..\dist
OutputBaseFilename=YouTubeContentManager-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
CloseApplications=yes
RestartApplications=no

[Files]
Source: "..\dist\windows\YouTubeContentManager.exe"; DestDir: "{app}"

[Icons]
Name: "{group}\YouTube Content Manager"; Filename: "{app}\YouTubeContentManager.exe"
Name: "{userdesktop}\YouTube Content Manager"; Filename: "{app}\YouTubeContentManager.exe"

[Run]
Filename: "{app}\YouTubeContentManager.exe"; Description: "Launch YouTube Content Manager"; Flags: postinstall nowait
