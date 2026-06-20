<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-06-20 | Updated: 2026-06-20 -->

# packaging

## Purpose
배포 패키지 생성 설정 파일 모음. PyInstaller spec(Windows/Linux 공용)과 Inno Setup 설치 스크립트, AppImage 레시피를 포함한다.

## Key Files

| File | Description |
|------|-------------|
| `online_video_clipper.spec` | PyInstaller spec — Windows + Linux 빌드 정의, 바이너리·데이터 파일 포함 규칙 |
| `installer.iss` | Inno Setup 스크립트 — Windows `.exe` 설치 프로그램 생성 |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `bin/` | 패키징용 ffmpeg 바이너리 (git 추적 안 됨 — 빌드 스크립트로 다운로드) |

## For AI Agents

### Working In This Directory
- `bin/`의 ffmpeg 바이너리는 VCS에 없음 — `scripts/build_windows.ps1` 또는 `scripts/build_linux.sh`로 자동 다운로드.
- 모든 리소스 경로는 `utils/resources.get_resource_path()`를 통해 번들 호환.
- 사용자 데이터(DB·로그·다운로드)는 `platformdirs.user_data_dir()`에 저장 — 앱 설치 디렉터리에 쓰면 안 됨.
- 빌드 결과물은 `build/` 디렉터리 — 소스와 혼동 주의.
- 전체 빌드 체크리스트는 `planning/packaging_plan.md` 참조.

## Dependencies

### External
- `pyinstaller` — 번들링 (`requirements-dev.txt`)
- Inno Setup (Windows 별도 설치) — 설치 프로그램 생성
- appimagetool (Linux 별도 설치) — AppImage 생성

<!-- MANUAL: -->
