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
; 실행 중인 앱을 Restart Manager로 강제 종료 후 파일 교체 — 파일 잠금(DeleteFile
; failed; code 5) 오류 방지. 앱 재실행은 자동 업데이트 배치([Run] postinstall)가
; 담당하므로 Inno의 자동 재시작은 끈다(중복 실행 방지).
CloseApplications=force
RestartApplications=no

[Files]
Source: "..\dist\windows\YouTubeContentManager\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs

[Icons]
Name: "{group}\YouTube Content Manager"; Filename: "{app}\YouTubeContentManager.exe"
Name: "{userdesktop}\YouTube Content Manager"; Filename: "{app}\YouTubeContentManager.exe"

[Run]
Filename: "{app}\YouTubeContentManager.exe"; Description: "Launch YouTube Content Manager"; Flags: postinstall nowait
