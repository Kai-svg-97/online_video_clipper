# Windows 패키징 가이드

Windows에서 `.exe` 단독 실행 파일과 Inno Setup 설치 파일(`.exe` 인스톨러)을 생성하는 방법을 설명합니다.

---

## 배포 결과물

| 파일 | 설명 |
|------|------|
| `dist\windows\YouTubeContentManager.exe` | PyInstaller 단일 실행 파일 (인스톨러 없이 바로 실행 가능) |
| `dist\YouTubeContentManager-setup.exe` | Inno Setup 설치 마법사 (권장 배포 방식) |

---

## 요구 사항

### 필수

| 항목 | 버전 | 확인 방법 |
|------|------|----------|
| Windows | 10 또는 11 (x86-64) | — |
| Python | 3.10 이상 | `python --version` |
| PowerShell | 5.1 이상 | `$PSVersionTable.PSVersion` |

> **PowerShell 실행 정책 확인**  
> Windows 기본값은 스크립트 실행이 차단되어 있습니다. 아래 명령으로 현재 정책을 확인하세요.
>
> ```powershell
> Get-ExecutionPolicy -Scope CurrentUser
> ```
>
> 결과가 `Restricted` 또는 `Undefined`이면 **빌드 전에** 정책을 변경해야 합니다. (→ [트러블슈팅](#powershell-실행-정책-오류-unauthorizedaccess) 참조)

### 선택 (설치 파일 생성 시)

| 항목 | 버전 | 다운로드 |
|------|------|---------|
| Inno Setup | 6.x | https://jrsoftware.org/isdl.php |

> Inno Setup이 없으면 설치 마법사 없이 단일 `.exe`만 생성됩니다.  
> 빌드 스크립트가 자동으로 감지하여 건너뜁니다.

---

## 빌드 절차

### 1단계 — 개발 의존성 설치

```powershell
pip install -r requirements-dev.txt
```

### 2단계 — 자동 빌드 스크립트 실행

프로젝트 루트에서 PowerShell을 열고 실행합니다.

```powershell
.\scripts\build_windows.ps1
```

스크립트가 순서대로 처리하는 작업:

1. **ffmpeg 자동 다운로드** — `bin\ffmpeg.exe`가 없으면 [gyan.dev](https://www.gyan.dev/ffmpeg/builds/) 에서 릴리스 빌드를 받아 배치합니다.
2. **PyInstaller 실행** — `packaging\online_video_clipper.spec`을 사용해 단일 `.exe`를 생성합니다.
3. **Inno Setup 실행** — `packaging\installer.iss`로 설치 마법사를 생성합니다. (설치된 경우에만)

### 2단계 (수동) — 단계별 실행

자동 스크립트 대신 수동으로 실행할 경우:

```powershell
# ffmpeg 수동 배치 (bin\ffmpeg.exe 가 없는 경우)
# https://www.gyan.dev/ffmpeg/builds/ 에서 ffmpeg-release-essentials.zip 다운로드 후
# ffmpeg.exe를 bin\ 폴더에 복사

# PyInstaller 빌드
python -m PyInstaller packaging\online_video_clipper.spec `
    --distpath dist\windows `
    --workpath build\tmp `
    --noconfirm

# Inno Setup (선택)
& "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe" packaging\installer.iss
```

---

## 빌드 결과 확인

성공 시 아래 파일이 생성됩니다.

```
dist\
├── windows\
│   └── YouTubeContentManager.exe   ← 단일 실행 파일
└── YouTubeContentManager-setup.exe ← 설치 마법사 (Inno Setup 있을 때만)
```

실행 파일을 Python이 없는 환경에서 직접 실행해 동작을 확인합니다.

```powershell
.\dist\windows\YouTubeContentManager.exe
```

---

## PyInstaller 스펙 상세 (`packaging\online_video_clipper.spec`)

```python
binaries  = [("bin/ffmpeg.exe", "bin")]      # ffmpeg 번들 포함
datas     = [("assets", "assets"),            # 아이콘 등 리소스
             ("db",     "db"),                # SQLite 스키마
             + yt_dlp 데이터 파일
             + PyQt6 데이터 파일]
icon      = "assets/icon.ico"
console   = False                             # GUI 앱 — 콘솔 창 없음
onefile   = True                              # 단일 파일 번들
```

---

## Inno Setup 설치 스크립트 상세 (`packaging\installer.iss`)

| 항목 | 설정값 |
|------|-------|
| 기본 설치 경로 | `%ProgramFiles%\YouTubeContentManager` |
| 시작 메뉴 그룹 | `YouTube Content Manager` |
| 바탕화면 바로가기 | 생성 |
| 관리자 권한 | 불필요 (`PrivilegesRequired=lowest`) |
| 압축 | `lzma2` (SolidCompression) |

---

## 트러블슈팅

### PowerShell 실행 정책 오류 (`UnauthorizedAccess`)

**증상:**
```
.\scripts\build_windows.ps1 : 이 시스템에서 스크립트를 실행할 수 없으므로 ... 파일을 로드할 수 없습니다.
PSSecurityException: UnauthorizedAccess
```

**원인:** Windows PowerShell의 기본 실행 정책(`Restricted`)이 로컬 스크립트 실행을 차단합니다.

**해결 방법 1 — 현재 사용자 정책 변경 (영구, 권장):**

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

- `RemoteSigned`: 로컬 스크립트는 자유롭게 실행, 인터넷에서 내려받은 스크립트는 서명 필요
- `-Scope CurrentUser`: 현재 사용자에게만 적용 (관리자 권한 불필요)

설정 후 정책을 확인합니다.

```powershell
Get-ExecutionPolicy -Scope CurrentUser
# RemoteSigned 출력되면 정상
```

이후 스크립트를 다시 실행합니다.

```powershell
.\scripts\build_windows.ps1
```

**해결 방법 2 — 일회성 우회 실행 (정책 변경 없이):**

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_windows.ps1
```

> 보안 정책을 영구적으로 바꾸고 싶지 않은 환경(공용 PC, 기업 관리 PC)에서 사용합니다.

---

### `ModuleNotFoundError` 발생 시

yt-dlp 플러그인 등 동적으로 로드되는 모듈이 누락된 경우입니다.  
`packaging\online_video_clipper.spec`의 `hiddenimports`에 해당 모듈을 추가합니다.

```python
hiddenimports=[
    *collect_submodules("yt_dlp"),
    "PyQt6.sip",
    "sqlite3",
    "모듈명_추가",   # ← 여기에 추가
]
```

### `pyinstaller` 명령을 찾을 수 없음 (`CommandNotFoundException`)

**증상:**
```
'pyinstaller' 용어가 cmdlet, 함수, 스크립트 파일 또는 실행할 수 있는 프로그램 이름으로 인식되지 않습니다.
```

**원인:** pip가 설치한 실행 파일(`pyinstaller.exe`)이 있는 Scripts 폴더가 PATH에 등록되지 않은 경우입니다.  
Python을 사용자 설치(`--user`) 하거나 Microsoft Store 버전으로 설치하면 자주 발생합니다.

**해결:** 빌드 스크립트는 `python -m PyInstaller`를 사용하도록 이미 수정되어 있어 PATH 등록 없이도 동작합니다.  
수동 실행 시에도 동일하게 사용하세요.

```powershell
python -m PyInstaller packaging\online_video_clipper.spec `
    --distpath dist\windows `
    --workpath build\tmp `
    --noconfirm
```

---

### `ffmpeg not found` 오류 시

`bin\ffmpeg.exe`가 없거나 PATH에도 없는 상태입니다.  
빌드 스크립트를 다시 실행하거나, 수동으로 `bin\ffmpeg.exe`를 배치하세요.

### Inno Setup을 찾을 수 없다는 경고

Inno Setup 6이 설치되어 있지 않거나 기본 경로가 다른 경우입니다.  
`scripts\build_windows.ps1`의 `$iscc` 변수 경로를 실제 설치 경로로 수정하세요.

```powershell
$iscc = "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
```

### PyInstaller 빌드가 매우 느린 경우

`build\tmp` 폴더를 삭제한 뒤 재시도하면 캐시 충돌 문제가 해결될 수 있습니다.

```powershell
Remove-Item -Recurse -Force build\tmp
```

---

## 빌드 전 체크리스트

- [ ] `python --version` → 3.10 이상
- [ ] PowerShell 실행 정책 확인 (`Get-ExecutionPolicy -Scope CurrentUser` → `RemoteSigned` 이상)
- [ ] `pip install -r requirements-dev.txt` 완료
- [ ] `assets\icon.ico` 존재
- [ ] `bin\ffmpeg.exe` 존재 (또는 스크립트가 자동 다운로드)
- [ ] `packaging\online_video_clipper.spec` 존재
- [ ] `packaging\installer.iss` 존재 (설치 파일 생성 시)
- [ ] Inno Setup 6 설치 (설치 파일 생성 시)
- [ ] 빌드 결과 실행 파일이 Python 없는 환경에서 정상 구동되는지 확인
