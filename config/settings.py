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
def _load_paths() -> dict:
    if _CONFIG_FILE.exists():
        with open(_CONFIG_FILE, encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        return cfg.get("paths", {})
    return {}


def _resolve(key: str, default: Path) -> Path:
    """Return the configured path for *key*, falling back to *default*."""
    raw = _load_paths().get(key, "")
    if not raw:
        return default
    p = Path(raw)
    # Relative paths are resolved from DATA_DIR
    return p if p.is_absolute() else DATA_DIR / p


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


def ensure_data_dirs() -> None:
    """Create all required data directories; called once at startup."""
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    THUMBNAIL_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
