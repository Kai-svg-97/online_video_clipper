from __future__ import annotations

from enum import Enum


class Quality(str, Enum):
    BEST    = "best"
    P2160   = "2160p"
    P1080   = "1080p"
    P720    = "720p"
    P480    = "480p"
    P360    = "360p"
    WORST   = "worst"
    AUDIO   = "audio"


class MediaFormat(str, Enum):
    MP4  = "mp4"
    MKV  = "mkv"
    WEBM = "webm"
    MP3  = "mp3"
    M4A  = "m4a"


# 음원으로 취급하는 확장자 — 목록 화면의 영상/음원 배지 판정에 사용한다.
# MediaFormat 밖의 값(yt-dlp 가 남긴 flac·opus 등)도 이력에 남을 수 있어 함께 담는다.
AUDIO_FORMAT_VALUES = frozenset(
    ("mp3", "m4a", "aac", "flac", "opus", "wav", "ogg")
)


class DownloadSettings:
    """다운로드 1건의 방식 — 품질·포맷과 **부가 정보를 파일에 어떻게 남길지**.

    ``include_*``는 **곁에 파일로 저장**(썸네일 .jpg, 자막 .vtt)을, ``embed_*``는
    **미디어 파일 안에 굽기**를 뜻한다. 둘은 독립이다 — 자막을 굽고 .vtt는 남기지
    않는 조합이 기본값이다(앱 밖에서 파일 하나만 옮겨도 자막이 따라간다).

    영속되는 것은 ``quality``·``format``·``subtitle_langs``·``include_*``뿐이다
    (`download_history` 컬럼). ``embed_*``와 ``capture_gemini``는 사용자 전역
    설정에서 매번 다시 채워지는 값이라 이력에 남기지 않는다 — 재시도 시
    `application.download.defaults`가 현재 설정으로 다시 채운다.
    """

    __slots__ = (
        "quality",
        "format",
        "subtitle_langs",
        "include_thumbnail",
        "include_metadata",
        "capture_gemini",
        "embed_subtitles",
        "embed_thumbnail",
        "embed_chapters",
        "sponsorblock_remove",
        "rate_limit",
        "concurrent_fragments",
        "proxy",
    )

    def __init__(
        self,
        quality: Quality = Quality.P1080,
        fmt: MediaFormat = MediaFormat.MP4,
        subtitle_langs: tuple[str, ...] = (),
        include_thumbnail: bool = True,
        include_metadata: bool = True,
        capture_gemini: bool = False,
        embed_subtitles: bool = False,
        embed_thumbnail: bool = False,
        embed_chapters: bool = False,
        sponsorblock_remove: tuple[str, ...] = (),
        rate_limit: str = "",
        concurrent_fragments: int = 1,
        proxy: str = "",
    ) -> None:
        self.quality = quality
        self.format = fmt
        self.subtitle_langs = subtitle_langs
        self.include_thumbnail = include_thumbnail
        self.include_metadata = include_metadata
        self.capture_gemini = capture_gemini
        self.embed_subtitles = embed_subtitles
        self.embed_thumbnail = embed_thumbnail
        self.embed_chapters = embed_chapters
        # 비어 있으면 끔. 값이 있으면 그 카테고리 구간을 **파일에서 잘라낸다**.
        self.sponsorblock_remove = sponsorblock_remove
        # 전송 옵션 — yt-dlp 표기를 그대로 전달한다("2M", "500K").
        self.rate_limit = rate_limit
        self.concurrent_fragments = concurrent_fragments
        self.proxy = proxy

    @property
    def is_audio(self) -> bool:
        """음원 산출물인가 — 자막 굽기 제외·ID3 태깅 대상 판정에 쓴다."""
        return self.format.value in AUDIO_FORMAT_VALUES

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, DownloadSettings):
            return NotImplemented
        return all(
            getattr(self, name) == getattr(other, name) for name in self.__slots__
        )

    def __hash__(self) -> int:
        return hash((self.quality, self.format, self.subtitle_langs, self.capture_gemini))


class DownloadProgress:
    """진행 상황. **총량을 모를 수 있다** — 라이브 방송이 그렇다.

    라이브는 끝을 모르므로 yt-dlp가 퍼센트 자리에 `NA`를 준다. 그대로 두면 화면이
    영원히 0%에 머물러 멈춘 것처럼 보이므로, `is_indeterminate`로 구분해 경과 시간과
    받은 용량으로 대신 알린다(`domain.download.live.format_recording_progress`).
    """

    __slots__ = (
        "percent",
        "speed_bps",
        "eta_sec",
        "downloaded_bytes",
        "total_bytes",
        "elapsed_sec",
    )

    def __init__(
        self,
        percent: float = 0.0,
        speed_bps: float = 0.0,
        eta_sec: int = 0,
        downloaded_bytes: int = 0,
        total_bytes: int = 0,
        elapsed_sec: float = 0.0,
    ) -> None:
        self.percent = percent
        self.speed_bps = speed_bps
        self.eta_sec = eta_sec
        self.downloaded_bytes = downloaded_bytes
        # 0 = 모름(라이브). 추정치라도 있으면 채운다.
        self.total_bytes = total_bytes
        self.elapsed_sec = elapsed_sec

    @property
    def is_indeterminate(self) -> bool:
        """총량을 모르는가 — 퍼센트를 보여줄 수 없는 상태."""
        return self.total_bytes <= 0

    def speed_formatted(self) -> str:
        if self.speed_bps < 1024:
            return f"{self.speed_bps:.0f} B/s"
        if self.speed_bps < 1024 ** 2:
            return f"{self.speed_bps / 1024:.1f} KB/s"
        return f"{self.speed_bps / 1024 ** 2:.1f} MB/s"
