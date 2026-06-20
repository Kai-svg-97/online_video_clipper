# Auto-Update Feature Spec
Generated: 2026-06-20

## Summary
GitHub Releases 기반 자동 업데이트. 사용자가 `v*` 태그를 푸시하면 GitHub Actions가 Windows installer를 빌드·업로드하고, 배포된 앱이 시작 시 + 수동으로 최신 버전을 확인하여 사용자 승인 후 installer를 실행한다.

## Repo
- `Kai-svg-97/online_video_clipper` (public)
- API: `https://api.github.com/repos/Kai-svg-97/online_video_clipper/releases/latest`

## Key Decisions
1. Apply: Inno Setup installer `/SILENT /CLOSEAPPLICATIONS` → `QApplication.quit()`
2. Version source: `version.py` (single source, `__version__ = "1.0.0"`)
3. Semver compare: hand-rolled (no `packaging` dep)
4. Check trigger: startup (async, 24h throttle) + manual button
5. Linux v1: notify only (open releases page)
6. Checksum: `assets[].sha256` if available, else skip with warning

## New Files
- `version.py`
- `application/updater/__init__.py`, `version_compare.py`, `dtos.py`, `queries.py`, `commands.py`
- `infrastructure/updater/__init__.py`, `update_checker.py`
- `gui/updater/__init__.py`, `update_checker_worker.py`, `update_dialog.py`, `update_controller.py`
- `.github/workflows/release.yml`
- `tests/unit/application/updater/__init__.py`, `test_version_compare.py`

## Modified Files
- `domain/shared/ports.py` — IUpdateChecker Protocol + UpdateInfo VO
- `config/settings.py` — AUTO_UPDATE_CHECK, LAST_UPDATE_CHECK constants
- `main.py` — wire checker/handlers/controller
- `gui/main_window.py` — set_update_controller(), startup QTimer, closeEvent
- `gui/panels/settings_panel.py` — update settings section
- `packaging/installer.iss` — parameterize AppVersion
- `scripts/build_windows.ps1` — -AppVersion param → /DAppVersion to ISCC
