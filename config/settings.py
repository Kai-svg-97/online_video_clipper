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
THUMBNAIL_WIDTH:         int = 320
THUMBNAIL_HEIGHT:        int = 180
PIXMAP_CACHE_LIMIT_KB:   int = 30_720   # 30 MB
LRU_THUMBNAIL_MAX:       int = 100

# ---------------------------------------------------------------------------
# 사용자 설정 (config.yaml에서 로드, 런타임에 변경 가능)
# ---------------------------------------------------------------------------

def _load_int(key: str, default: int) -> int:
    try:
        return int(_load_config().get(key, default))
    except (TypeError, ValueError):
        return default


def _load_bool(key: str, default: bool) -> bool:
    v = _load_config().get(key)
    if v is None:
        return default
    return bool(v)


MAX_CONCURRENT_DOWNLOADS: int = _load_int("max_concurrent_downloads", 3)
CLIPBOARD_MONITORING: bool = _load_bool("clipboard_monitoring", True)
DEFAULT_QUALITY: str = _resolve_str("default_quality", "best[ext=mp4]/best")
DEFAULT_FORMAT: str = _resolve_str("default_format", "mp4")

# ---------------------------------------------------------------------------
# 테마 설정
# ---------------------------------------------------------------------------

THEME: str = _resolve_str("theme", "slate")


def save_setting(key: str, value) -> None:
    """단일 설정 키-값을 config.yaml에 저장하고 모듈 변수를 갱신한다."""
    import config.settings as _self  # noqa: PLC0415
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    cfg: dict = {}
    if _CONFIG_FILE.exists():
        with open(_CONFIG_FILE, encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
    cfg[key] = value
    with open(_CONFIG_FILE, "w", encoding="utf-8") as f:
        yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False)
    _load_config.cache_clear()
    # 모듈 변수 즉시 갱신
    mapping = {
        "max_concurrent_downloads": "MAX_CONCURRENT_DOWNLOADS",
        "clipboard_monitoring": "CLIPBOARD_MONITORING",
        "default_quality": "DEFAULT_QUALITY",
        "default_format": "DEFAULT_FORMAT",
        "theme": "THEME",
    }
    if key in mapping:
        setattr(_self, mapping[key], value)


def save_path_setting(key: str, path_str: str) -> None:
    """경로 설정(paths.*)을 config.yaml의 paths 섹션에 저장하고 모듈 변수를 갱신한다."""
    import config.settings as _self  # noqa: PLC0415
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    cfg: dict = {}
    if _CONFIG_FILE.exists():
        with open(_CONFIG_FILE, encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
    if "paths" not in cfg:
        cfg["paths"] = {}
    cfg["paths"][key] = path_str
    with open(_CONFIG_FILE, "w", encoding="utf-8") as f:
        yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False)
    _load_config.cache_clear()
    p = Path(path_str)
    path_mapping = {
        "database": "DATABASE_PATH",
        "downloads": "DOWNLOAD_DIR",
        "thumbnails": "THUMBNAIL_DIR",
        "logs": "LOG_DIR",
        "backups": "BACKUP_DIR",
    }
    if key in path_mapping:
        setattr(_self, path_mapping[key], p)


def save_theme(name: str) -> None:
    """선택한 테마 이름을 config.yaml에 저장한다."""
    save_setting("theme", name)


# ---------------------------------------------------------------------------
# 숨김 태그 관리
# ---------------------------------------------------------------------------

_HIDDEN_TAGS_KEY = "hidden_tag_names"


def load_hidden_tag_names() -> set[str]:
    """태그 목록에서 숨길 태그 이름 집합을 반환한다."""
    raw = _load_config().get(_HIDDEN_TAGS_KEY, [])
    return set(raw) if isinstance(raw, list) else set()


def save_hidden_tag_names(names: set[str]) -> None:
    """숨길 태그 이름 집합을 config.yaml에 저장하고 캐시를 갱신한다."""
    save_setting(_HIDDEN_TAGS_KEY, sorted(names))


def ensure_data_dirs() -> None:
    """Create all required data directories; called once at startup."""
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    THUMBNAIL_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
