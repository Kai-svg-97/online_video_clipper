# Linux 패키징 가이드

Linux에서 단독 실행 바이너리와 이식성 높은 `.AppImage`를 생성하는 방법을 설명합니다.

---

## 배포 결과물

| 파일 | 설명 |
|------|------|
| `dist/linux/YouTubeContentManager` | PyInstaller 단일 바이너리 (AppImage 없이 바로 실행 가능) |
| `dist/YouTubeContentManager-x86_64.AppImage` | AppImage — 모든 주요 배포판에서 추가 설치 없이 실행 가능 (권장) |

---

## 요구 사항

### 필수

| 항목 | 버전 | 확인 방법 |
|------|------|----------|
| Linux | x86-64, glibc 2.17 이상 | `ldd --version` |
| Python | 3.10 이상 | `python3 --version` |
| curl | — | `curl --version` |

> 대부분의 최신 배포판(Ubuntu 20.04+, Fedora 36+, Debian 11+)은 기본으로 충족합니다.

### 선택 (AppImage 생성 시)

| 항목 | 설명 | 설치 |
|------|------|------|
| `appimagetool` | AppImage 생성 도구 | 아래 설치 방법 참조 |

#### appimagetool 설치

```bash
curl -LO "https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage"
chmod +x appimagetool-x86_64.AppImage
sudo mv appimagetool-x86_64.AppImage /usr/local/bin/appimagetool
```

> `appimagetool`이 없으면 단일 바이너리만 생성됩니다.  
> 빌드 스크립트가 자동으로 감지하여 건너뜁니다.

---

## 빌드 절차

### 1단계 — 시스템 패키지 설치 (Ubuntu/Debian 기준)

PyQt6 빌드에 필요한 시스템 라이브러리를 설치합니다.

```bash
sudo apt update
sudo apt install -y \
    python3-dev \
    libglib2.0-0 \
    libgl1-mesa-glx \
    libxcb-xinerama0 \
    libxcb-icccm4 \
    libxcb-image0 \
    libxcb-keysyms1 \
    libxcb-randr0 \
    libxcb-render-util0 \
    libxcb-xkb1 \
    libxkbcommon-x11-0
```

<details>
<summary>Fedora / RHEL 계열</summary>

```bash
sudo dnf install -y \
    python3-devel \
    glib2 \
    mesa-libGL \
    xcb-util-wm \
    xcb-util-image \
    xcb-util-keysyms \
    xcb-util-renderutil \
    libxkbcommon-x11
```

</details>

### 2단계 — 개발 의존성 설치

```bash
pip install -r requirements-dev.txt
```

### 3단계 — 자동 빌드 스크립트 실행

```bash
bash scripts/build_linux.sh
```

스크립트가 순서대로 처리하는 작업:

1. **ffmpeg 자동 다운로드** — `bin/ffmpeg`가 없으면 [johnvansickle.com](https://johnvansickle.com/ffmpeg/) 의 정적 빌드를 받아 배치합니다.
2. **PyInstaller 실행** — `packaging/online_video_clipper.spec`을 사용해 단일 바이너리를 생성합니다.
3. **AppDir 구성** — `.desktop` 파일과 아이콘을 포함한 AppDir 구조를 준비합니다.
4. **AppImage 생성** — `appimagetool`로 `.AppImage`를 생성합니다. (설치된 경우에만)

### 3단계 (수동) — 단계별 실행

```bash
# ffmpeg 수동 배치 (bin/ffmpeg 가 없는 경우)
mkdir -p bin
curl -L "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz" \
     -o /tmp/ffmpeg.tar.xz
tar -xf /tmp/ffmpeg.tar.xz -C /tmp
cp /tmp/ffmpeg-*/ffmpeg bin/ffmpeg
chmod +x bin/ffmpeg

# PyInstaller 빌드
pyinstaller packaging/online_video_clipper.spec \
    --distpath dist/linux \
    --workpath build/tmp \
    --noconfirm

# AppDir 구성
mkdir -p build/AppDir/usr/bin
cp dist/linux/YouTubeContentManager build/AppDir/usr/bin/

cat > build/AppDir/YouTubeContentManager.desktop <<EOF
[Desktop Entry]
Name=YouTube Content Manager
Exec=YouTubeContentManager
Icon=icon
Type=Application
Categories=Network;Video;
EOF

cp assets/icon.png build/AppDir/icon.png

# AppImage 생성 (appimagetool 있을 때만)
appimagetool build/AppDir dist/YouTubeContentManager-x86_64.AppImage
```

---

## 빌드 결과 확인

성공 시 아래 파일이 생성됩니다.

```
dist/
├── linux/
│   └── YouTubeContentManager       ← 단일 바이너리
└── YouTubeContentManager-x86_64.AppImage  ← AppImage (appimagetool 있을 때만)
```

AppImage를 실행 가능하게 설정한 뒤 구동합니다.

```bash
chmod +x dist/YouTubeContentManager-x86_64.AppImage
./dist/YouTubeContentManager-x86_64.AppImage
```

Python이 설치되지 않은 다른 배포판 환경에서도 동작하는지 검증하는 것을 권장합니다.

---

## AppImage 배포 시 참고 사항

### FUSE 요구 사항

AppImage를 실행하려면 호스트 시스템에 FUSE 2가 필요합니다.

```bash
# Ubuntu / Debian
sudo apt install libfuse2

# Fedora
sudo dnf install fuse
```

### FUSE 없이 실행 (--appimage-extract-and-run)

FUSE 설치가 불가한 환경에서는 AppImage를 임시 폴더에 압축 해제 후 실행합니다.

```bash
./YouTubeContentManager-x86_64.AppImage --appimage-extract-and-run
```

---

## PyInstaller 스펙 상세 (`packaging/online_video_clipper.spec`)

```python
binaries = [("bin/ffmpeg", "bin")]            # ffmpeg 번들 포함
datas    = [("assets", "assets"),              # 아이콘 등 리소스
            ("db",     "db"),                  # SQLite 스키마
            + yt_dlp 데이터 파일
            + PyQt6 데이터 파일]
icon     = "assets/icon.png"
console  = False                               # GUI 앱 — 터미널 창 없음
onefile  = True                                # 단일 파일 번들
```

---

## 트러블슈팅

### `libGL.so.1: cannot open shared object file`

OpenGL 라이브러리가 누락된 경우입니다.

```bash
# Ubuntu / Debian
sudo apt install libgl1-mesa-glx

# Fedora
sudo dnf install mesa-libGL
```

### `xcb plugin` 관련 오류 (`qt.qpa.plugin`)

Qt XCB 플러그인 의존성이 없는 경우입니다.

```bash
# Ubuntu / Debian
sudo apt install libxcb-xinerama0 libxkbcommon-x11-0
```

### 헤드리스 서버에서 빌드 실패

GUI 디스플레이가 없는 서버에서는 `Xvfb`로 가상 디스플레이를 제공합니다.

```bash
sudo apt install xvfb
Xvfb :99 -screen 0 1024x768x24 &
export DISPLAY=:99
bash scripts/build_linux.sh
```

### `ModuleNotFoundError` 발생 시

`packaging/online_video_clipper.spec`의 `hiddenimports`에 누락 모듈을 추가합니다.

```python
hiddenimports=[
    *collect_submodules("yt_dlp"),
    "PyQt6.sip",
    "sqlite3",
    "누락된_모듈명",   # ← 여기에 추가
]
```

### `ffmpeg` 다운로드 실패 (네트워크 차단)

`johnvansickle.com`에 접근이 불가한 환경에서는 ffmpeg를 직접 배치합니다.

```bash
# 공식 ffmpeg 정적 빌드: https://ffmpeg.org/download.html
mkdir -p bin
cp /경로/to/ffmpeg bin/ffmpeg
chmod +x bin/ffmpeg
```

---

## 빌드 전 체크리스트

- [ ] `python3 --version` → 3.10 이상
- [ ] 시스템 Qt/XCB 의존성 설치 완료
- [ ] `pip install -r requirements-dev.txt` 완료
- [ ] `assets/icon.png` 존재
- [ ] `bin/ffmpeg` 존재 (또는 스크립트가 자동 다운로드)
- [ ] `packaging/online_video_clipper.spec` 존재
- [ ] `appimagetool` 설치 (AppImage 생성 시)
- [ ] AppImage가 FUSE 없는 다른 배포판에서도 실행되는지 확인
