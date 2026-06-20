<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-06-20 | Updated: 2026-06-20 -->

# gui/dialogs

## Purpose
독립 다이얼로그 창 모음. YouTube OAuth 인증 플로우와 일괄 다운로드 URL 입력을 제공한다.

## Key Files

| File | Description |
|------|-------------|
| `__init__.py` | 패키지 마커 |
| `youtube_auth_dialog.py` | YouTube OAuth 인증 플로우 다이얼로그 — `infrastructure.auth.youtube_auth` 직접 참조 (수용된 경계) |
| `batch_download_dialog.py` | 일괄 다운로드 URL 입력 다이얼로그 |

## For AI Agents

### Working In This Directory
- `youtube_auth_dialog.py`가 `infrastructure.auth`를 직접 참조하는 것은 설계 의도 — 로그인 플로우의 본질적 인프라 의존 때문.
- OAuth 플로우 변경 시 `infrastructure/auth/youtube_auth.py`와 함께 수정.
- **GUI 파일 수정 후 `/verify` 스킬 실행 필수**.

## Dependencies

### Internal
- `infrastructure/auth/youtube_auth.py` — YouTubeAuthService (youtube_auth_dialog에서 직접)

<!-- MANUAL: -->
