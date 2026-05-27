import sys
from functools import lru_cache
from pathlib import Path

import yaml


def _app_root() -> Path:
    """Project root in dev; directory containing the exe in a PyInstaller bundle."""
    if hasattr(sys, "_MEIPASS"):
        return Path(sys.executable).parent
    return Path(__file__).parent.parent


DATA_DIR: Path = _app_root() / "data"
_CONFIG_FILE: Path = DATA_DIR / "config.yaml"


@lru_cache(maxsize=1)
def _load_config() -> dict:
    """전체 config.yaml을 로드한다."""
    if _CONFIG_FILE.exists():
        with open(_CONFIG_FILE, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


def _load_paths() -> dict:
    return _load_config().get("paths", {})


def _resolve(key: str, default: Path) -> Path:
    """Return the configured path for *key*, falling back to *default*."""
    raw = _load_paths().get(key, "")
    if not raw:
        return default
    p = Path(raw)
    # Relative paths are resolved from DATA_DIR
    return p if p.is_absolute() else DATA_DIR / p


def _resolve_str(key: str, default: str) -> str:
    """문자열 설정 값을 반환한다."""
    return _load_config().get(key, default)


# ---------------------------------------------------------------------------
# Public path constants — directories are created by ensure_data_dirs()
# ---------------------------------------------------------------------------

DATABASE_PATH: Path = _resolve("database",   DATA_DIR / "library.db")
DOWNLOAD_DIR:  Path = _resolve("downloads",  DATA_DIR / "downloads")
THUMBNAIL_DIR: Path = _resolve("thumbnails", DATA_DIR / "thumbnails")
LOG_DIR:       Path = _resolve("logs",       DATA_DIR / "logs")
BACKUP_DIR:    Path = _resolve("backups",    DATA_DIR / "backups")

# ---------------------------------------------------------------------------
# Application-level defaults (not path-related)
# ---------------------------------------------------------------------------

DEFAULT_PAGE_SIZE:       int = 50
MAX_CONCURRENT_DOWNLOADS: int = 3
THUMBNAIL_WIDTH:         int = 320
THUMBNAIL_HEIGHT:        int = 180
PIXMAP_CACHE_LIMIT_KB:   int = 30_720   # 30 MB
LRU_THUMBNAIL_MAX:       int = 100

# ---------------------------------------------------------------------------
# 테마 설정
# ---------------------------------------------------------------------------

THEME: str = _resolve_str("theme", "slate")


def save_theme(name: str) -> None:
    """선택한 테마 이름을 config.yaml에 저장한다."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    cfg: dict = {}
    if _CONFIG_FILE.exists():
        with open(_CONFIG_FILE, encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
    cfg["theme"] = name
    with open(_CONFIG_FILE, "w", encoding="utf-8") as f:
        yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False)
    # lru_cache 무효화 — 다음 조회 시 갱신
    _load_config.cache_clear()


def ensure_data_dirs() -> None:
    """Create all required data directories; called once at startup."""
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    THUMBNAIL_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
