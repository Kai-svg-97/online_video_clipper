<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-06-20 | Updated: 2026-06-20 -->

# gui/dialogs

## Purpose
독립 다이얼로그 창 모음. YouTube OAuth 인증 플로우와 일괄 다운로드 URL 입력을 제공한다.

## Key Files

| File | Description |
|------|-------------|
| `__init__.py` | 패키지 마커 |
| `youtube_auth_dialog.py` | YouTube 쿠키 인증 다이얼로그 — `IYouTubeAuth`를 생성자로 받는다 |
| `batch_download_dialog.py` | 일괄 다운로드 URL 입력 다이얼로그 |

## For AI Agents

### Working In This Directory
- `youtube_auth_dialog.py`는 `infrastructure`를 임포트하지 않는다 — `IYouTubeAuth`(`domain/shared/ports.py`)를 생성자로 받는다(`tests/unit/test_gui_does_not_import_infrastructure.py`).
- OAuth 플로우 변경 시 `infrastructure/auth/youtube_auth.py`와 함께 수정.
- **GUI 파일 수정 후 `/verify` 스킬 실행 필수**.

## Dependencies

### Internal
- `domain/shared/ports.py` — `IYouTubeAuth` (구현 `infrastructure/auth/youtube_auth.py:YouTubeAuthService`, 조립 루트가 주입)

<!-- MANUAL: -->
