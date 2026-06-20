<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-06-20 | Updated: 2026-06-20 -->

# infrastructure/auth

## Purpose
YouTube 브라우저 인증 서비스. 로컬 브라우저 프로필을 탐지하고 Playwright를 통해 OAuth 쿠키를 추출한다.
이 모듈은 `gui/dialogs/youtube_auth_dialog.py`와 `gui/main_window.py`에서 직접 참조하는 수용된 경계(composition-root 인접)다.

## Key Files

| File | Description |
|------|-------------|
| `__init__.py` | 패키지 마커 |
| `youtube_auth.py` | `YouTubeAuthService` — 브라우저 프로필 탐지, Playwright 로그인, Netscape 쿠키 파일 추출 |

## For AI Agents

### Working In This Directory
- GUI 레이어가 이 모듈을 직접 참조하는 것은 **설계 의도** — 로그인 플로우가 본질적으로 인프라라서 포트로 감싸도 런타임 의존이 사라지지 않음.
- application 레이어는 이 모듈을 절대 import하지 않아야 함.
- `config.settings`의 `YT_AUTH_BROWSER`, `YT_AUTH_PROFILE`, `YT_AUTH_COOKIEFILE` 설정 참조.

## Dependencies

### External
- `playwright` — 브라우저 자동화, 쿠키 추출

<!-- MANUAL: -->
