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
# 미디어 경로 이식성 (머신 간 동기화 대비)
#
# DB에는 미디어/썸네일 경로를 DATA_DIR 기준 **상대경로**로 저장해 다른 PC에서도
# 유효하도록 한다. 런타임에는 절대경로로 복원해서 쓴다. DATA_DIR 밖의 경로(사용자가
# 별도 위치를 지정한 경우)는 이식할 수 없으므로 절대경로 그대로 보존한다.
# ---------------------------------------------------------------------------

def to_portable_path(p: str) -> str:
    """절대경로가 DATA_DIR 하위면 상대경로(POSIX 구분자)로 변환한다.

    이미 상대경로거나 빈 값, DATA_DIR 밖의 절대경로는 그대로 반환한다(idempotent).
    """
    if not p:
        return p
    path = Path(p)
    if not path.is_absolute():
        return p
    try:
        return path.relative_to(DATA_DIR).as_posix()
    except ValueError:
        return p  # DATA_DIR 밖 — 이식 불가, 절대경로 보존


def resolve_media_path(p: str) -> str:
    """저장된 경로를 런타임 절대경로로 복원한다.

    상대경로는 DATA_DIR 기준으로 결합하고, 이미 절대경로거나 빈 값은 그대로 둔다.
    """
    if not p:
        return p
    path = Path(p)
    if path.is_absolute():
        return p
    return str(DATA_DIR / path)

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


def _load_float(key: str, default: float) -> float:
    try:
        return float(_load_config().get(key, default))
    except (TypeError, ValueError):
        return default


MAX_CONCURRENT_DOWNLOADS: int = _load_int("max_concurrent_downloads", 3)
MAX_CONCURRENT_FEED_WORKERS: int = _load_int("max_concurrent_feed_workers", 4)
CLIPBOARD_MONITORING: bool = _load_bool("clipboard_monitoring", True)
DEFAULT_QUALITY: str = _resolve_str("default_quality", "best[ext=mp4]/best")
DEFAULT_FORMAT: str = _resolve_str("default_format", "mp4")
AUTO_UPDATE_CHECK: bool = _load_bool("auto_update_check", True)
# ── 다운로드 파일에 부가 정보 굽기(embed) ────────────────────────────────
# 앱 밖(다른 플레이어·차량·폰)에서도 자막·표지·챕터가 따라가게 하는 설정이다.
# `DOWNLOAD_SUBTITLE_LANGS`가 비어 있으면 자막 자체를 받지 않으므로 굽기도 없다.
DOWNLOAD_SUBTITLE_LANGS: str = _resolve_str("download_subtitle_langs", "")
EMBED_SUBTITLES: bool = _load_bool("embed_subtitles", True)
EMBED_THUMBNAIL: bool = _load_bool("embed_thumbnail", True)
EMBED_CHAPTERS: bool = _load_bool("embed_chapters", True)
# 음원(mp3·m4a 등)에 라이브러리의 노래 정보(가수·앨범·발매년도·가사·표지)를 태그로 기록한다.
WRITE_SONG_TAGS: bool = _load_bool("write_song_tags", True)
# ── 음성 인식(전사) ─────────────────────────────────────────────────────
# 모델 키(`domain.library.transcribe.MODELS`). 모델 파일은 DATA_DIR/models/whisper 에
# 받아 두며, 한 번도 쓰지 않으면 아무것도 내려받지 않는다.
TRANSCRIBE_MODEL: str = _resolve_str("transcribe_model", "base")
# ── 다운로드 프리셋 ─────────────────────────────────────────────────────
# 같은 사람이 영상을 받는 방식은 몇 가지로 갈린다(보관용·음악·가볍게). 이름 붙인
# 묶음을 두고 고르게 한다. 내장 프리셋은 코드에 있고(domain/download/download_presets.py)
# 여기에는 **사용자가 만들거나 고친 것**과 숨긴 내장만 담는다.
DOWNLOAD_PRESETS: list = _load_config().get("download_presets") or []
HIDDEN_PRESET_KEYS: list = _load_config().get("hidden_preset_keys") or []
# 다운로드할 때 쓸 프리셋 키. 빈 값이면 프리셋을 쓰지 않고 전역 설정을 그대로 쓴다.
ACTIVE_PRESET_KEY: str = _resolve_str("active_preset_key", "")
# ── 트레이 알림 · 새 영상 감시 ───────────────────────────────────────────
# 다운로드는 몇 분~몇 시간이 걸린다. 그동안 사용자는 이 앱을 보고 있지 않으므로,
# 앱 안의 토스트만으로는 끝났다는 소식이 전달되지 않는다.
TRAY_NOTIFICATIONS: bool = _load_bool("tray_notifications", True)
# 구독 채널에 새 영상이 올라왔는지 배경에서 주기적으로 확인한다.
WATCH_NEW_VIDEOS: bool = _load_bool("watch_new_videos", False)
WATCH_INTERVAL_MIN: int = _load_int("watch_interval_min", 30)
# 지난번 조회에서 본 영상 주소들. 날짜 표기가 출처마다 달라 **주소로 비교한다**
# (domain/monitoring/watch.py 참고).
WATCH_SEEN_URLS: list = _load_config().get("watch_seen_urls") or []
# ── 전송 옵션(속도·연결·프록시) ─────────────────────────────────────────
# `DOWNLOAD_RATE_LIMIT`는 yt-dlp 표기를 그대로 받는다("2M", "500K"). 빈 값 = 무제한.
DOWNLOAD_RATE_LIMIT: str = _resolve_str("download_rate_limit", "")
# 조각 병렬 내려받기 — DASH/HLS 영상에서 체감이 크다. 1이면 끄기와 같다.
CONCURRENT_FRAGMENTS: int = _load_int("concurrent_fragments", 1)
# 프록시 주소("http://host:port", "socks5://host:port"). 빈 값 = 사용 안 함.
DOWNLOAD_PROXY: str = _resolve_str("download_proxy", "")
# ── 예약 다운로드(시간대) ───────────────────────────────────────────────
# 끄면 언제든 받는다. 자정을 넘기는 구간(23~7)도 지원한다.
DOWNLOAD_WINDOW_ENABLED: bool = _load_bool("download_window_enabled", False)
DOWNLOAD_WINDOW_START: int = _load_int("download_window_start", 23)
DOWNLOAD_WINDOW_END: int = _load_int("download_window_end", 7)
# ── SponsorBlock ────────────────────────────────────────────────────────
# 재생 중 건너뛰기는 되돌릴 수 있어 기본 켜고, 다운로드 시 제거는 파일을 실제로
# 잘라내 되돌릴 수 없으므로 기본 끈다.
SPONSORBLOCK_SKIP: bool = _load_bool("sponsorblock_skip", True)
SPONSORBLOCK_REMOVE: bool = _load_bool("sponsorblock_remove", False)
SPONSORBLOCK_CATEGORIES: str = _resolve_str(
    "sponsorblock_categories", "sponsor,selfpromo,interaction"
)
# 단건 등록 직후 요약(비노래)·가사(노래) 자동 보강. 일괄 임포트는 대상이 아니다.
AUTO_ENRICH_ON_ADD: bool = _load_bool("auto_enrich_on_add", True)
# 라이브러리 목록 아래 추천 영상 스트립 — 접힘 상태와 높이(px)를 기억한다.
# 접혀 있으면 추천 조회(네트워크)도 하지 않는다.
RECOMMEND_STRIP_EXPANDED: bool = _load_bool("recommend_strip_expanded", True)
RECOMMEND_STRIP_HEIGHT: int = _load_int("recommend_strip_height", 250)
# 자막 표시 설정 — 전역(영상과 무관한 보기 설정). 비율이라 인라인·전체화면·PiP
# 어디서나 같은 비중으로 보인다. 값 범위 clamp 는 LyricsOverlay 가 담당한다.
SUBTITLE_FONT_SCALE: float = _load_float("subtitle_font_scale", 1.0)
SUBTITLE_BOTTOM_RATIO: float = _load_float("subtitle_bottom_ratio", 0.10)
# 상세 화면에서 "읽는 글"(요약·가사)의 글자 배율 — 전역 보기 설정이다.
DETAIL_TEXT_SCALE: float = _load_float("detail_text_scale", 1.0)
# 영상 자막(YouTube 캡션) — 지난번에 고른 언어를 기억해 다음 영상에도 이어 켠다.
VIDEO_SUBTITLE_LANG_1: str = _resolve_str("video_subtitle_lang_1", "")
VIDEO_SUBTITLE_LANG_2: str = _resolve_str("video_subtitle_lang_2", "")
LAST_UPDATE_CHECK: float = float(_load_config().get("last_update_check", 0) or 0)
SNOOZED_UPDATE_VERSION: str = _resolve_str("snoozed_update_version", "")

# ---------------------------------------------------------------------------
# 테마 설정
# ---------------------------------------------------------------------------

THEME: str = _resolve_str("theme", "slate")

# ---------------------------------------------------------------------------
# YouTube 인증 설정
# ---------------------------------------------------------------------------

YT_AUTH_BROWSER: str = _resolve_str("yt_auth_browser", "chrome")
YT_AUTH_PROFILE: str | None = _load_config().get("yt_auth_profile")
YT_AUTH_COOKIEFILE: str | None = _load_config().get("yt_auth_cookiefile")
YT_AUTH_ACCOUNT_NAME: str | None = _load_config().get("yt_auth_account_name")


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
        "max_concurrent_feed_workers": "MAX_CONCURRENT_FEED_WORKERS",
        "clipboard_monitoring": "CLIPBOARD_MONITORING",
        "default_quality": "DEFAULT_QUALITY",
        "default_format": "DEFAULT_FORMAT",
        "theme": "THEME",
        "auto_update_check": "AUTO_UPDATE_CHECK",
        "auto_enrich_on_add": "AUTO_ENRICH_ON_ADD",
        "download_subtitle_langs": "DOWNLOAD_SUBTITLE_LANGS",
        "embed_subtitles": "EMBED_SUBTITLES",
        "embed_thumbnail": "EMBED_THUMBNAIL",
        "embed_chapters": "EMBED_CHAPTERS",
        "write_song_tags": "WRITE_SONG_TAGS",
        "transcribe_model": "TRANSCRIBE_MODEL",
        "download_presets": "DOWNLOAD_PRESETS",
        "hidden_preset_keys": "HIDDEN_PRESET_KEYS",
        "active_preset_key": "ACTIVE_PRESET_KEY",
        "tray_notifications": "TRAY_NOTIFICATIONS",
        "watch_new_videos": "WATCH_NEW_VIDEOS",
        "watch_interval_min": "WATCH_INTERVAL_MIN",
        "watch_seen_urls": "WATCH_SEEN_URLS",
        "download_rate_limit": "DOWNLOAD_RATE_LIMIT",
        "concurrent_fragments": "CONCURRENT_FRAGMENTS",
        "download_proxy": "DOWNLOAD_PROXY",
        "download_window_enabled": "DOWNLOAD_WINDOW_ENABLED",
        "download_window_start": "DOWNLOAD_WINDOW_START",
        "download_window_end": "DOWNLOAD_WINDOW_END",
        "sponsorblock_skip": "SPONSORBLOCK_SKIP",
        "sponsorblock_remove": "SPONSORBLOCK_REMOVE",
        "sponsorblock_categories": "SPONSORBLOCK_CATEGORIES",
        "recommend_strip_expanded": "RECOMMEND_STRIP_EXPANDED",
        "recommend_strip_height": "RECOMMEND_STRIP_HEIGHT",
        "subtitle_font_scale": "SUBTITLE_FONT_SCALE",
        "subtitle_bottom_ratio": "SUBTITLE_BOTTOM_RATIO",
        "detail_text_scale": "DETAIL_TEXT_SCALE",
        "video_subtitle_lang_1": "VIDEO_SUBTITLE_LANG_1",
        "video_subtitle_lang_2": "VIDEO_SUBTITLE_LANG_2",
        "last_update_check": "LAST_UPDATE_CHECK",
        "snoozed_update_version": "SNOOZED_UPDATE_VERSION",
        "yt_auth_browser": "YT_AUTH_BROWSER",
        "yt_auth_profile": "YT_AUTH_PROFILE",
        "yt_auth_cookiefile": "YT_AUTH_COOKIEFILE",
        "yt_auth_account_name": "YT_AUTH_ACCOUNT_NAME",
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
