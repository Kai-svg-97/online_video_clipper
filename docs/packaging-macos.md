# macOS 패키징 가이드

> **지원 수준:** macOS는 보조(secondary) 플랫폼입니다.  
> 자동화 빌드 스크립트가 없으므로 아래 단계를 수동으로 실행합니다.

macOS에서 `.app` 번들과 `.dmg` 배포 이미지를 생성하는 방법을 설명합니다.

---

## 배포 결과물

| 파일 | 설명 |
|------|------|
| `dist/macos/YouTubeContentManager.app` | macOS 앱 번들 (PyInstaller 결과) |
| `dist/YouTubeContentManager.dmg` | DMG 배포 이미지 (권장 배포 방식) |

---

## 요구 사항

### 필수

| 항목 | 버전 | 확인 방법 |
|------|------|----------|
| macOS | 12 Monterey 이상 | `sw_vers` |
| Python | 3.10 이상 | `python3 --version` |
| Xcode Command Line Tools | 최신 | `xcode-select --version` |

```bash
# Xcode Command Line Tools 설치
xcode-select --install
```

### 선택 (DMG 생성 시)

| 항목 | 설명 | 설치 |
|------|------|------|
| `create-dmg` | DMG 생성 도구 | `brew install create-dmg` |
| Homebrew | 패키지 관리자 | https://brew.sh |

---

## 빌드 절차

### 1단계 — Homebrew 및 ffmpeg 설치

```bash
# Homebrew 설치 (없는 경우)
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# ffmpeg 설치 후 bin/ 에 복사
brew install ffmpeg
mkdir -p bin
cp "$(brew --prefix ffmpeg)/bin/ffmpeg" bin/ffmpeg
chmod +x bin/ffmpeg
```

> Apple Silicon(M1/M2/M3) 환경에서는 Homebrew 경로가 `/opt/homebrew`입니다.  
> Intel Mac은 `/usr/local`입니다.

### 2단계 — 개발 의존성 설치

```bash
pip3 install -r requirements-dev.txt
```

### 3단계 — PyInstaller 빌드

공용 스펙 파일을 사용합니다. macOS에서는 `onefile=True`일 때 `.app` 번들이 아닌 단일 바이너리가 생성되므로, `--onedir` 방식으로 `.app` 번들을 얻습니다.

```bash
pyinstaller packaging/online_video_clipper.spec \
    --distpath dist/macos \
    --workpath build/tmp \
    --noconfirm
```

> **Apple Silicon 주의:** Rosetta 2를 거치지 않고 Native ARM 바이너리를 얻으려면  
> ARM 빌드의 Python과 PyInstaller를 사용해야 합니다.  
> `arch -arm64 pyinstaller ...` 형태로 실행하세요.

### 4단계 — 앱 번들 확인

```bash
open dist/macos/YouTubeContentManager.app
```

### 5단계 — DMG 생성 (선택)

```bash
brew install create-dmg

create-dmg \
    --volname "YouTube Content Manager" \
    --volicon "assets/icon.png" \
    --window-pos 200 120 \
    --window-size 600 300 \
    --icon-size 100 \
    --icon "YouTubeContentManager.app" 175 120 \
    --app-drop-link 425 120 \
    "dist/YouTubeContentManager.dmg" \
    "dist/macos/"
```

---

## 코드 서명 및 공증 (Notarization)

macOS Gatekeeper를 통과하려면 Apple Developer 계정으로 서명과 공증이 필요합니다.  
서명 없이 배포하면 사용자가 직접 허용해야 합니다.

### 서명 없이 실행 허용 (개발·내부 배포용)

```bash
# 격리 속성 제거
xattr -cr dist/macos/YouTubeContentManager.app

# 또는 시스템 환경설정 → 개인 정보 보호 및 보안 → "확인 없이 열기"
```

### 코드 서명 (Apple Developer Program 가입 필요)

```bash
# 서명
codesign --deep --force --verify --verbose \
    --sign "Developer ID Application: YOUR_NAME (TEAM_ID)" \
    --options runtime \
    dist/macos/YouTubeContentManager.app

# 서명 확인
codesign --verify --verbose dist/macos/YouTubeContentManager.app
spctl --assess --verbose dist/macos/YouTubeContentManager.app
```

### 공증 (Notarization)

```bash
# DMG 공증 제출
xcrun notarytool submit dist/YouTubeContentManager.dmg \
    --apple-id "your@apple.id" \
    --team-id "TEAM_ID" \
    --password "앱 전용 암호" \
    --wait

# 공증 스탬프 첨부
xcrun stapler staple dist/YouTubeContentManager.dmg
```

---

## PyInstaller 스펙 수정 (macOS 전용 설정)

현재 공용 스펙(`packaging/online_video_clipper.spec`)을 사용합니다.  
macOS 전용 설정이 필요한 경우 스펙 파일을 다음과 같이 수정합니다.

```python
# packaging/online_video_clipper.spec 수정 예시
_win   = platform.system() == "Windows"
_mac   = platform.system() == "Darwin"
_linux = platform.system() == "Linux"

_ffmpeg_src = "bin/ffmpeg.exe" if _win else "bin/ffmpeg"
_icon = "assets/icon.ico" if _win else "assets/icon.icns" if _mac else "assets/icon.png"

# macOS에서 .app 번들 생성을 원하는 경우 BUNDLE 추가
if _mac:
    app = BUNDLE(
        exe,
        name="YouTubeContentManager.app",
        icon="../assets/icon.icns",
        bundle_identifier="com.yourname.youtubecontentmanager",
    )
```

> `.icns` 파일은 macOS 앱 번들의 아이콘 형식입니다.  
> `sips` 또는 `iconutil` 명령어로 `.png`를 `.icns`로 변환할 수 있습니다.

```bash
# icon.png → icon.icns 변환
mkdir icon.iconset
sips -z 16 16   assets/icon.png --out icon.iconset/icon_16x16.png
sips -z 32 32   assets/icon.png --out icon.iconset/icon_16x16@2x.png
sips -z 32 32   assets/icon.png --out icon.iconset/icon_32x32.png
sips -z 64 64   assets/icon.png --out icon.iconset/icon_32x32@2x.png
sips -z 128 128 assets/icon.png --out icon.iconset/icon_128x128.png
sips -z 256 256 assets/icon.png --out icon.iconset/icon_128x128@2x.png
sips -z 256 256 assets/icon.png --out icon.iconset/icon_256x256.png
sips -z 512 512 assets/icon.png --out icon.iconset/icon_256x256@2x.png
sips -z 512 512 assets/icon.png --out icon.iconset/icon_512x512.png
cp assets/icon.png icon.iconset/icon_512x512@2x.png
iconutil -c icns icon.iconset -o assets/icon.icns
rm -rf icon.iconset
```

---

## 트러블슈팅

### `This app is damaged and can't be opened`

Gatekeeper가 서명되지 않은 앱을 차단하는 경우입니다.

```bash
xattr -cr dist/macos/YouTubeContentManager.app
```

### `Library not loaded: @rpath/...` 오류

dylib 경로 문제입니다. PyInstaller가 의존 라이브러리를 번들에 포함시키지 못한 경우입니다.

```bash
# 실제 의존 라이브러리 확인
otool -L dist/macos/YouTubeContentManager.app/Contents/MacOS/YouTubeContentManager
```

### Qt 플러그인 오류 (`qt.qpa.plugin`)

```bash
# XCB 대신 macOS 네이티브 플랫폼 사용
export QT_QPA_PLATFORM=cocoa
```

### Apple Silicon에서 `Bad CPU type in executable`

ARM 네이티브 Python이 아닌 x86_64 Python을 사용하고 있는 경우입니다.

```bash
# 현재 Python 아키텍처 확인
python3 -c "import platform; print(platform.machine())"
# arm64 이어야 함

# arm64 Python 설치 (pyenv 사용)
arch -arm64 brew install pyenv
arch -arm64 pyenv install 3.12.0
```

### `ModuleNotFoundError` 발생 시

`packaging/online_video_clipper.spec`의 `hiddenimports`에 누락 모듈을 추가합니다.

```python
hiddenimports=[
    *collect_submodules("yt_dlp"),
    "PyQt6.sip",
    "sqlite3",
    "누락된_모듈명",
]
```

---

## 빌드 전 체크리스트

- [ ] `sw_vers` → macOS 12 이상
- [ ] `python3 --version` → 3.10 이상
- [ ] `xcode-select --version` → Xcode CLT 설치 확인
- [ ] `assets/icon.png` 존재 (`.icns` 사용 시 변환 완료)
- [ ] `bin/ffmpeg` 존재 (Homebrew에서 복사)
- [ ] `pip3 install -r requirements-dev.txt` 완료
- [ ] `packaging/online_video_clipper.spec` 존재
- [ ] `create-dmg` 설치 (DMG 생성 시)
- [ ] 앱 번들이 Python 없는 환경에서 정상 구동되는지 확인
- [ ] Gatekeeper 통과 여부 확인 (내부 배포: `xattr -cr`, 외부 배포: 서명 + 공증)
