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
; failed; code 5) 오류 방지. Inno의 자동 재시작은 끈다.
CloseApplications=force
RestartApplications=no

[Files]
Source: "..\dist\windows\YouTubeContentManager\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs

[Icons]
Name: "{group}\YouTube Content Manager"; Filename: "{app}\YouTubeContentManager.exe"
Name: "{userdesktop}\YouTube Content Manager"; Filename: "{app}\YouTubeContentManager.exe"

[Run]
; postinstall 은 무인 설치(/VERYSILENT)에서도 실행되므로 skipifsilent 를 붙인다.
; 업데이트 후 앱 재실행은 main.py 종료 tail 배치가 단독으로 담당한다 — 양쪽이 모두
; 실행하면 인스턴스가 2개가 되고, 양쪽을 모두 막으면 아무도 실행하지 않는다.
; (배치는 구버전 앱이 만들고 인스톨러는 신버전이라 한쪽만 고쳐야 한다.)
Filename: "{app}\YouTubeContentManager.exe"; Description: "Launch YouTube Content Manager"; Flags: postinstall nowait skipifsilent
