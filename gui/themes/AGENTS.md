<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-06-20 | Updated: 2026-06-20 -->

# gui/themes

## Purpose
앱 전체 테마 시스템. `ThemeManager` 싱글턴이 전역 QSS를 교체하고 `theme_changed` 시그널을 방출한다.
토큰 기반 디자인 시스템으로 색상·간격·폰트를 관리한다.

## Key Files

| File | Description |
|------|-------------|
| `__init__.py` | 패키지 마커 |
| `manager.py` | `ThemeManager` 싱글턴 — `apply_theme(name)`, `theme_changed` 시그널 |
| `tokens.py` | `ThemeTokens` dataclass + `PRESETS` 딕셔너리 (slate, dark, light 등) |
| `stylesheet.py` | `build_qss(tokens: ThemeTokens) → str` — 토큰으로 전체 QSS 문자열 생성 |

## For AI Agents

### Working In This Directory
- 새 테마 추가: `tokens.py`의 `PRESETS`에 `ThemeTokens` 인스턴스 추가.
- QSS 변경: `stylesheet.py`의 `build_qss()` 함수 수정.
- 테마 저장/로드: `config.settings.save_theme()` 및 `THEME` 상수 사용.
- `ThemeManager`는 싱글턴 — `ThemeManager.instance()` 패턴.

## Dependencies

### Internal
- `config/settings.py` — THEME 설정 로드·저장

### External
- `PyQt6.QtWidgets` — QApplication.setStyleSheet()

<!-- MANUAL: -->
