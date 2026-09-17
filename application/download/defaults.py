"""사용자 전역 설정에서 다운로드 부가 옵션을 채우는 곳 — **여기 한 곳뿐**이다.

`DownloadSettings`의 ``embed_*``·``subtitle_langs``는
`download_history`에 남지 않는다(도메인 값객체 주석 참조). 그래서 새 작업을 만들
때도, 이력에서 되살린 작업을 재시도할 때도 **현재 설정으로 다시 채워야** 한다.
호출부마다 `config.settings`를 읽으면 그 규칙이 흩어지므로 이 모듈로 모은다.

`domain/`은 외부 의존이 없어야 하므로 config 접근은 application 레이어인 여기서
한다(`application/clip/commands.py`가 `DOWNLOAD_DIR`를 읽는 것과 같은 선례).
"""

from __future__ import annotations

from domain.clip.sponsor import DEFAULT_SKIP_CATEGORIES
from domain.download.value_objects import DownloadSettings, MediaFormat, Quality


def parse_subtitle_langs(raw: str) -> tuple[str, ...]:
    """``"ko, en , "`` → ``("ko", "en")``. 빈 문자열이면 빈 튜플(자막 안 받음)."""
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def build_download_settings(
    quality: Quality = Quality.P1080,
    fmt: MediaFormat = MediaFormat.MP4,
    *,
    capture_gemini: bool = False,
) -> DownloadSettings:
    """현재 사용자 설정을 반영한 `DownloadSettings`를 만든다."""
    settings = DownloadSettings(quality=quality, fmt=fmt, capture_gemini=capture_gemini)
    return apply_user_defaults(settings)


def apply_user_defaults(settings: DownloadSettings) -> DownloadSettings:
    """``embed_*``·``subtitle_langs``를 현재 설정으로 채워 돌려준다.

    값객체를 제자리에서 고치지 않고 새 인스턴스를 만든다 — 이미 큐에 들어간 작업이
    설정 변경에 따라 소급해 바뀌면 진행 중 다운로드의 동작이 도중에 달라진다.
    """
    from config import settings as cfg  # noqa: PLC0415 (런타임 값이라 호출 시점에 읽는다)

    langs = settings.subtitle_langs or parse_subtitle_langs(cfg.DOWNLOAD_SUBTITLE_LANGS)
    return DownloadSettings(
        quality=settings.quality,
        fmt=settings.format,
        subtitle_langs=langs,
        include_thumbnail=settings.include_thumbnail,
        include_metadata=settings.include_metadata,
        capture_gemini=settings.capture_gemini,
        embed_subtitles=bool(cfg.EMBED_SUBTITLES),
        embed_thumbnail=bool(cfg.EMBED_THUMBNAIL),
        embed_chapters=bool(cfg.EMBED_CHAPTERS),
        sponsorblock_remove=_removal_categories(cfg),
        rate_limit=(cfg.DOWNLOAD_RATE_LIMIT or "").strip(),
        concurrent_fragments=max(1, int(cfg.CONCURRENT_FRAGMENTS or 1)),
        proxy=(cfg.DOWNLOAD_PROXY or "").strip(),
    )


def _removal_categories(cfg) -> tuple[str, ...]:
    """다운로드 파일에서 **잘라낼** SponsorBlock 카테고리(꺼져 있으면 빈 튜플).

    재생 중 건너뛰기와 같은 카테고리 목록을 쓰되, 켜고 끄는 스위치는 따로다 —
    건너뛰기는 되돌릴 수 있지만 잘라내기는 파일을 실제로 바꾼다.
    """
    if not cfg.SPONSORBLOCK_REMOVE:
        return ()
    raw = (cfg.SPONSORBLOCK_CATEGORIES or "").split(",")
    picked = tuple(part.strip() for part in raw if part.strip())
    return picked or DEFAULT_SKIP_CATEGORIES
