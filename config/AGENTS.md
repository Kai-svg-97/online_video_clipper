<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-06-20 | Updated: 2026-06-20 -->

# config

## Purpose
사용자 설정 관리. `data/config.yaml`을 읽어 경로·테마·다운로드 옵션 등의 설정을 모듈 수준 상수로 노출하고,
런타임 변경을 `save_setting()` / `save_path_setting()`으로 즉시 반영한다.

## Key Files

| File | Description |
|------|-------------|
| `__init__.py` | 패키지 마커 |
| `settings.py` | 설정 상수(`DATABASE_PATH`, `DOWNLOAD_DIR` 등) + `ensure_data_dirs()` + `save_setting()` |

## For AI Agents

### Working In This Directory
- `data/config.yaml`은 **런타임 사용자 데이터** — git에 커밋하지 말 것 (`.gitignore` 처리됨).
- `data/config.yaml.example`은 설정 예시 파일 — 새 설정 추가 시 이 파일도 업데이트.
- 새 설정 키 추가 시 `settings.py`의 `mapping` 딕셔너리와 `save_setting()`에도 반영.
- PyInstaller 번들 환경에서는 `sys._MEIPASS`가 설정되므로 `_app_root()`가 exe 디렉터리를 반환.

### Common Patterns
```python
# 설정 읽기 — 모듈 상수 직접 참조
from config.settings import DOWNLOAD_DIR, DEFAULT_QUALITY

# 설정 저장 — 즉시 모듈 변수도 갱신됨
from config.settings import save_setting
save_setting("default_quality", "720p")

# 데이터 디렉터리 보장 — 앱 시작 시 1회
from config.settings import ensure_data_dirs
ensure_data_dirs()
```

### Key Constants
| Constant | Default |
|----------|---------|
| `DATABASE_PATH` | `data/library.db` |
| `DOWNLOAD_DIR` | `data/downloads` |
| `THUMBNAIL_DIR` | `data/thumbnails` |
| `LOG_DIR` | `data/logs` |
| `DEFAULT_PAGE_SIZE` | `50` |
| `LRU_THUMBNAIL_MAX` | `100` |
| `PIXMAP_CACHE_LIMIT_KB` | `30720` (30 MB) |
| `MAX_CONCURRENT_DOWNLOADS` | `3` |
| `MAX_CONCURRENT_FEED_WORKERS` | `4` |

## Dependencies

### External
- `PyYAML` — config.yaml 파싱

<!-- MANUAL: -->
