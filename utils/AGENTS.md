<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-06-20 | Updated: 2026-06-20 -->

# utils

## Purpose
앱 전반에서 사용하는 공통 유틸리티 두 가지: 리소스 경로 해결(`resources.py`)과 로깅 초기화(`logging_config.py`).

## Key Files

| File | Description |
|------|-------------|
| `__init__.py` | 패키지 마커 |
| `resources.py` | `get_resource_path()` — 개발 환경과 PyInstaller 번들 환경 모두에서 올바른 리소스 경로 반환 |
| `logging_config.py` | `setup_logging()` — 회전 파일(`LOG_DIR/app.log`) + 콘솔 로거 설정; `main.py`에서 1회 호출 |

## For AI Agents

### Working In This Directory
- `get_resource_path()`는 번들 환경(`sys._MEIPASS`)과 개발 환경(`Path(__file__)`) 양쪽을 처리 — 리소스 경로는 반드시 이 함수를 경유할 것.
- `setup_logging()`은 `main.py` 진입점에서 정확히 1회만 호출.
- 모듈마다 `logger = logging.getLogger(__name__)` 선언 필수.
- **예외를 조용히 삼키지 말 것** — `except Exception: pass` 패턴 금지; 항상 `logger.exception("맥락")`.

### Common Patterns
```python
# 리소스 경로 — 항상 get_resource_path() 경유
from utils.resources import get_resource_path
icon_path = get_resource_path("assets/icon.ico")

# 로깅 — 모듈 상단 선언
import logging
logger = logging.getLogger(__name__)

# 예외 처리 규칙
try:
    result = some_api_call()
except Exception:
    logger.exception("API 호출 실패")  # ✅ 흔적 남김
    return None
```

## Dependencies

### External
- `platformdirs` — 사용자 데이터 디렉터리 위치 결정

<!-- MANUAL: -->
