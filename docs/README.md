# YouTube Content Manager — 패키징 문서

이 디렉토리에는 각 운영체제별 배포 패키지 빌드 방법이 정리되어 있습니다.

---

## 빠른 참조

| 운영체제 | 배포 형식 | 자동화 스크립트 | 문서 |
|----------|-----------|----------------|------|
| Windows 10/11 | `.exe` 설치 파일 | `scripts/build_windows.ps1` | [packaging-windows.md](packaging-windows.md) |
| Linux (x86-64) | `.AppImage` | `scripts/build_linux.sh` | [packaging-linux.md](packaging-linux.md) |
| macOS 12+ | `.dmg` (수동) | 없음 (보조 지원) | [packaging-macos.md](packaging-macos.md) |

---

## 공통 전제 조건

모든 플랫폼에서 빌드 전 반드시 충족해야 하는 조건입니다.

### Python

```
Python 3.10 이상
```

```bash
python --version  # 3.10.x 이상 확인
```

### 개발 의존성 설치

```bash
pip install -r requirements-dev.txt
```

`requirements-dev.txt`는 런타임 패키지(`requirements.txt`) 전체를 포함하며, 빌드·테스트 도구가 추가됩니다.

| 패키지 | 용도 |
|--------|------|
| `PyInstaller >= 6.3` | 단일 실행 파일 번들링 |
| `pytest >= 8.0` | 테스트 |
| `ruff >= 0.4` | 린트 |

### 필수 애셋

빌드 전 아래 파일이 존재하는지 확인합니다.

```
online_video_clipper/
├── assets/
│   ├── icon.ico   ← Windows 빌드에 필요
│   └── icon.png   ← Linux / macOS 빌드에 필요
```

### ffmpeg 바이너리

`bin/` 폴더에 플랫폼별 ffmpeg 바이너리가 있어야 합니다.  
`bin/` 폴더는 `.gitignore`에 등록되어 있으므로 VCS에 포함되지 않습니다.  
각 OS 빌드 스크립트가 없을 경우 **자동으로 다운로드**합니다.

```
bin/
├── ffmpeg.exe   ← Windows
└── ffmpeg       ← Linux / macOS
```

---

## 프로젝트 디렉토리 구조 (빌드 관련)

```
online_video_clipper/
├── main.py                        # 애플리케이션 진입점
├── requirements.txt               # 런타임 패키지
├── requirements-dev.txt           # 빌드·테스트 패키지
│
├── assets/                        # 번들 포함 리소스
│   ├── icon.ico
│   └── icon.png
│
├── bin/                           # ffmpeg 바이너리 (VCS 제외)
│   ├── ffmpeg.exe
│   └── ffmpeg
│
├── packaging/
│   ├── online_video_clipper.spec  # PyInstaller 스펙 (Windows/Linux/macOS 공용)
│   └── installer.iss              # Inno Setup 스크립트 (Windows 전용)
│
├── scripts/
│   ├── build_windows.ps1          # Windows 자동 빌드
│   └── build_linux.sh             # Linux 자동 빌드
│
└── dist/                          # 빌드 결과물 (빌드 후 생성)
    ├── windows/
    │   └── YouTubeContentManager.exe
    ├── linux/
    │   └── YouTubeContentManager
    └── YouTubeContentManager-setup.exe      (Inno Setup 결과)
        YouTubeContentManager-x86_64.AppImage (AppImage 결과)
```

---

## 사용자 데이터 저장 위치

배포된 애플리케이션의 데이터(DB, 다운로드, 로그)는 앱 설치 폴더가 아닌 OS 표준 경로에 저장됩니다.  
앱 업데이트 시에도 사용자 데이터가 보존됩니다.

| 운영체제 | 데이터 경로 |
|----------|------------|
| 개발 환경 | `<프로젝트루트>/data/` |
| Windows (배포) | `<프로젝트루트>/data/` (exe 옆) |
| Linux (배포) | `<프로젝트루트>/data/` (exe 옆) |

> **경로 커스터마이징:** `data/config.yaml`을 생성하여 각 경로를 재정의할 수 있습니다.  
> 자세한 내용은 `config/settings.py`를 참조하세요.
