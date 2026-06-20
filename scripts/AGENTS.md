<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-06-20 | Updated: 2026-06-20 -->

# scripts

## Purpose
플랫폼별 빌드 자동화 스크립트. PyInstaller 실행, ffmpeg 바이너리 다운로드, 설치 프로그램 생성을 순서대로 처리한다.

## Key Files

| File | Description |
|------|-------------|
| `build_windows.ps1` | PowerShell: ffmpeg 다운로드 → PyInstaller → Inno Setup 실행 |
| `build_linux.sh` | Bash: ffmpeg 다운로드 → PyInstaller → appimagetool 실행 |

## For AI Agents

### Working In This Directory
- 빌드 스크립트는 `packaging/online_video_clipper.spec`을 참조하며 `build/` 산출물 디렉터리에 결과를 생성.
- ffmpeg 바이너리는 빌드 시점에 다운로드되므로 `bin/` 디렉터리가 비어있어도 정상.
- 전체 빌드 절차는 `planning/packaging_plan.md` 및 `docs/packaging-windows.md`, `docs/packaging-linux.md` 참조.

<!-- MANUAL: -->
