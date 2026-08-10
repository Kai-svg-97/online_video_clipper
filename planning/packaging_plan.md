# 배포 패키지 계획

## 목표

| 플랫폼  | 배포 형식                       | 도구                          |
|---------|---------------------------------|-------------------------------|
| Windows | `.exe` 설치 파일 (Inno Setup)   | PyInstaller + Inno Setup 6    |
| Linux   | `.AppImage` (단일 실행 파일)    | PyInstaller + appimagetool    |

사용자는 Python, ffmpeg, yt-dlp를 별도 설치할 필요 없음 — 모두 패키지에 포함.

---

## 핵심 코드 패턴 (개발 시 반드시 준수)

### 1. 리소스 경로: `utils/resources.py`

```python
import sys
from pathlib import Path

def get_resource_path(relative: str) -> Path:
    """PyInstaller 번들과 개발 환경 모두에서 올바른 경로를 반환."""
    base = Path(sys._MEIPASS) if hasattr(sys, "_MEIPASS") else Path(__file__).parent.parent
    return base / relative
```

사용 예: `get_resource_path("assets/icon.ico")`

- `assets/`, `bin/ffmpeg` 등 번들 리소스는 **반드시 이 함수로 참조**
- 하드코딩된 절대 경로 금지

### 2. 사용자 데이터 경로: `config/settings.py`

```python
from platformdirs import user_data_dir, user_log_dir
from pathlib import Path

APP_NAME = "YouTubeContentManager"
APP_AUTHOR = "KaiDev"

# OS별 표준 경로 자동 선택
# Windows: %APPDATA%\YouTubeContentManager\
# Linux:   ~/.local/share/YouTubeContentManager/
DATA_DIR  = Path(user_data_dir(APP_NAME, APP_AUTHOR))
LOG_DIR   = Path(user_log_dir(APP_NAME, APP_AUTHOR))

DB_PATH       = DATA_DIR / "library.db"
DOWNLOAD_DIR  = DATA_DIR / "downloads"
BACKUP_DIR    = DATA_DIR / "backups"
```

- DB, 로그, 다운로드 파일은 **앱 설치 폴더가 아닌 사용자 데이터 폴더에 저장**
- 앱 업데이트 시 사용자 데이터 보존됨

### 3. ffmpeg 경로 해석

```python
import shutil
from utils.resources import get_resource_path

def get_ffmpeg_path() -> str:
    # 1순위: 번들 bin/ 폴더
    bundled = get_resource_path("bin/ffmpeg")
    if bundled.exists():
        return str(bundled)
    # 2순위: 시스템 PATH
    system = shutil.which("ffmpeg")
    if system:
        return system
    raise FileNotFoundError("ffmpeg not found. Install ffmpeg or place it in bin/")
```

---

## PyInstaller 스펙 (`packaging/online_video_clipper.spec`)

```python
# -*- mode: python -*-
from PyInstaller.utils.hooks import collect_data_files, collect_submodules
import sys, platform

is_windows = platform.system() == "Windows"
ffmpeg_bin = ("bin/ffmpeg.exe", "bin") if is_windows else ("bin/ffmpeg", "bin")

a = Analysis(
    ["../main.py"],
    pathex=[".."],
    binaries=[ffmpeg_bin],
    datas=[
        ("../assets", "assets"),
        *collect_data_files("yt_dlp"),
        *collect_data_files("PyQt6"),
    ],
    hiddenimports=[
        *collect_submodules("yt_dlp"),
        "PyQt6.sip",
        "sqlite3",
        # 클라우드 동기화 — 지연/동적 import라 명시 수집
        "keyring",
        *collect_submodules("keyring.backends"),
        *collect_submodules("msal"),
        "googleapiclient",
        "google_auth_oauthlib",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, a.binaries, a.datas,
    name="YouTubeContentManager",
    debug=False,
    console=False,           # GUI app — no terminal window
    icon="../assets/icon.ico" if is_windows else "../assets/icon.png",
    onefile=True,            # 단일 실행 파일
)
```

---

## 빌드 스크립트

### Windows (`scripts/build_windows.ps1`)

```powershell
# 1. ffmpeg 다운로드 (없을 경우)
if (-not (Test-Path "..\bin\ffmpeg.exe")) {
    Write-Host "Downloading ffmpeg for Windows..."
    # ffmpeg-release-essentials.zip 다운로드 후 bin/ 에 복사
}

# 2. PyInstaller 실행
pyinstaller build/online_video_clipper.spec --distpath dist/windows --workpath build/tmp

# 3. Inno Setup으로 설치 파일 생성
iscc build/installer.iss
Write-Host "Output: dist/YouTubeContentManager-setup.exe"
```

### Linux (`scripts/build_linux.sh`)

```bash
#!/usr/bin/env bash
set -e

# 1. ffmpeg 다운로드 (없을 경우)
if [ ! -f ../bin/ffmpeg ]; then
    echo "Downloading ffmpeg for Linux..."
    # ffmpeg static build 다운로드 후 bin/ 에 복사
    chmod +x ../bin/ffmpeg
fi

# 2. PyInstaller 실행
pyinstaller build/online_video_clipper.spec --distpath dist/linux --workpath build/tmp

# 3. AppImage 생성
mkdir -p AppDir/usr/bin
cp dist/linux/YouTubeContentManager AppDir/usr/bin/
appimagetool AppDir dist/YouTubeContentManager-x86_64.AppImage
echo "Output: dist/YouTubeContentManager-x86_64.AppImage"
```

---

## YouTube OAuth 클라이언트 주입 (빌드 시 credential injection)

앱은 사용자가 직접 Google Cloud OAuth Client ID/Secret을 입력하지 않는다 — 배포자가
소유한 **하나의 Desktop(Installed App) OAuth 클라이언트 설정**을 빌드 시 번들해
`설정 → YouTube API 연동 → Google 계정으로 연결` 버튼만으로 인증이 이루어진다.

- **빌드 입력**: 환경변수 `OVC_YOUTUBE_OAUTH_CONFIG`가 가리키는 JSON 파일. 미지정 시
  로컬 개발 입력인 `data/OAuth2.json`을 기본값으로 쓴다(`data/OAuth.json`은 Client
  Secret이 달라 사용하지 않음 — 절대 혼동하지 말 것).
- **검증**: `scripts/build_windows.ps1`/`scripts/build_linux.sh`가 PyInstaller 실행
  전에 JSON을 파싱해 `installed.client_id`·`installed.client_secret`·localhost
  loopback redirect 존재를 확인한다. 값은 어떤 로그에도 출력하지 않고, 실패 시
  파일 경로와 누락 필드명만 담은 예외를 던진다.
- **주입 범위**: `OVC_YOUTUBE_OAUTH_CONFIG`는 PyInstaller 하위 프로세스에만 설정되고
  빌드 스크립트 종료 시(`finally`) 복원/제거된다.
- **GitHub Actions(`release.yml`)**: 로컬 `data/OAuth2.json`은 gitignore라 CI 체크아웃에
  없으므로, 저장소 시크릿 `YOUTUBE_OAUTH_CLIENT_JSON`(그 파일 내용 그대로)을 읽어
  `$RUNNER_TEMP/OAuth2.json`으로 복원 후 `OVC_YOUTUBE_OAUTH_CONFIG`로 넘긴다("Write
  YouTube OAuth client config from secret" 스텝). 시크릿이 없으면 빌드가 즉시 실패한다
  (`gh secret set YOUTUBE_OAUTH_CLIENT_JSON --repo <owner>/<repo> < data/OAuth2.json`로 등록).
- **패키징**: `packaging/online_video_clipper.spec`이 검증된 경로를 `datas`에
  `(_oauth_src, "config")`로 추가해 번들 내 `config/OAuth2.json` 한 개로 고정한다.
  환경변수가 없거나 파일이 없으면 spec이 `SystemExit`로 빌드를 즉시 중단한다.
- **런타임 해석**: `infrastructure/youtube/oauth_client_config.py:find_youtube_oauth_config()`가
  `get_resource_path("config/OAuth2.json")`로 이 파일을 찾는다(개발 환경에서는
  `data/OAuth2.json` 폴백).
- **사용자 토큰과의 분리**: 클라이언트 설정(배포자 소유, 빌드 시 1개 고정)과 사용자별
  OAuth 토큰(설치 후 각자 인증, OS keyring 저장)은 서로 다른 자산이다 — 개발자의
  액세스/리프레시 토큰이나 `data/library.db`는 어떤 빌드에도 포함되지 않는다.

### 산출물 안전성 검증 (필수)

빌드 후 아래 읽기 전용 점검으로 정확히 OAuth 클라이언트 JSON 1개만 포함되고
DB·쿠키·시크릿 파일이 0개인지 확인한다:

```powershell
$bundle = Resolve-Path 'dist/windows/YouTubeContentManager'
$oauth = Get-ChildItem -LiteralPath $bundle -Recurse -File -Filter 'OAuth2.json'
$forbidden = Get-ChildItem -LiteralPath $bundle -Recurse -File |
  Where-Object { $_.Name -match 'library\.db|cookies|secrets\.json' }
[PSCustomObject]@{
  OAuthConfigCount = @($oauth).Count
  ForbiddenFileCount = @($forbidden).Count
}
```

기대값: `OAuthConfigCount = 1`, `ForbiddenFileCount = 0`. 파일 내용은 절대 출력하지 않는다.

---

## Inno Setup 스크립트 (`build/installer.iss`)

```ini
[Setup]
AppName=YouTube Content Manager
AppVersion=1.0.0
DefaultDirName={autopf}\YouTubeContentManager
DefaultGroupName=YouTube Content Manager
OutputDir=..\dist
OutputBaseFilename=YouTubeContentManager-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Files]
Source: "..\dist\windows\YouTubeContentManager.exe"; DestDir: "{app}"

[Icons]
Name: "{group}\YouTube Content Manager"; Filename: "{app}\YouTubeContentManager.exe"
Name: "{commondesktop}\YouTube Content Manager"; Filename: "{app}\YouTubeContentManager.exe"

[Run]
Filename: "{app}\YouTubeContentManager.exe"; Description: "Launch app"; Flags: postinstall nowait
```

> **파일 잠금(업데이트 시) 방지 — 필수**: `[Setup]`에 `CloseApplications=force` + `RestartApplications=no`를 둔다. 실행 중인 앱이 `.pyd`/`.exe`를 잠그면 재설치·업데이트 시 `DeleteFile failed; code 5. 액세스가 거부되었습니다` 오류가 난다. `force`는 Restart Manager로 실행 중인 앱을 강제 종료 후 파일을 교체하고, 앱 재실행은 자동 업데이트 배치(`main.py`의 pending-update 런처)와 `[Run] postinstall`이 담당하므로 Inno 자동 재시작은 끈다(중복 실행 방지). **주의: 이 설정은 해당 설정을 포함해 빌드된 setup.exe부터 효력이 있다** — 이미 설치된 구버전을 덮어쓸 때가 아니라, 새 버전의 setup.exe가 구버전을 닫을 때 적용된다.

---

## requirements 분리

**`requirements.txt`** (런타임 — 번들에 포함):

```text
PyQt6>=6.6
yt-dlp>=2024.1
requests>=2.31
beautifulsoup4>=4.12
playwright>=1.40
ffmpeg-python>=0.2
platformdirs>=4.1
msal>=1.28
keyring>=25.0
```

> 클라우드 동기화(OneDrive)는 `msal`, 자격증명 저장은 `keyring`(부재 시 파일 폴백)을 쓴다.
> Google Drive는 기존 `google-auth-oauthlib`/`google-api-python-client`를 재사용한다.

**`requirements-dev.txt`** (빌드/테스트 전용 — 번들 제외):

```text
-r requirements.txt
pyinstaller>=6.3
pytest>=8.0
ruff>=0.3
```

---

## 빌드 전 체크리스트

- [ ] `utils/resources.py`의 `get_resource_path()` 로 리소스 참조
- [ ] DB/로그/다운로드 경로가 `platformdirs` 기반인지 확인
- [ ] `bin/ffmpeg[.exe]` 빌드 머신에 존재하는지 확인
- [ ] `assets/icon.ico` (Windows), `assets/icon.png` (Linux) 존재 확인
- [ ] `pyinstaller build/online_video_clipper.spec` 로컬 테스트 통과
- [ ] 번들 실행 파일이 Python 없는 환경에서 실행되는지 검증
- [ ] `OVC_YOUTUBE_OAUTH_CONFIG`(또는 `data/OAuth2.json`)가 유효한 Desktop OAuth
      클라이언트 설정인지 확인 — 값은 출력하지 않고 검증만
- [ ] 산출물에 `config/OAuth2.json` 1개만 있고 `library.db`·쿠키·시크릿 파일이
      0개인지 안전성 감사 통과

---

## 디렉토리 구조 요약

```text
online_video_clipper/
├── bin/                    # ffmpeg 바이너리 (VCS 제외 — .gitignore)
├── assets/                 # 아이콘 등 번들 리소스
├── build/
│   ├── online_video_clipper.spec
│   ├── installer.iss
│   └── appimage/
├── scripts/
│   ├── build_windows.ps1
│   └── build_linux.sh
└── utils/
    └── resources.py        # get_resource_path()
```
