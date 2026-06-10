"""애플리케이션 레이어가 의존하는 포트(추상화) 정의.

DDD 의존성 규칙(`gui → application → domain ← infrastructure`)에 따라
application 레이어는 infrastructure의 구체 클래스(EventBus, YtDlpAdapter,
FfmpegAdapter)를 직접 import 해서는 안 된다. 대신 여기 정의된 Protocol에
의존하고, infrastructure의 어댑터들이 구조적 타이핑(structural typing)으로
이 Protocol을 만족시킨다 — 어댑터는 상속·등록 없이 메서드 시그니처만 맞으면 된다.

런타임 배선은 composition root(`main.py`)가 구체 어댑터를 주입한다.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Protocol
from uuid import UUID

from domain.clip.value_objects import TimeRange
from domain.download.value_objects import DownloadSettings


class IEventBus(Protocol):
    """인프로세스 도메인 이벤트 디스패처 추상화 (infrastructure.event_bus.EventBus)."""

    def subscribe(self, event_type: type, handler: Callable) -> None: ...
    def unsubscribe(self, event_type: type, handler: Callable) -> None: ...
    def publish(self, event: object) -> None: ...
    def publish_all(self, events: list) -> None: ...


class IMediaSource(Protocol):
    """동영상 메타데이터 조회·다운로드·재생목록/구독 조회 공급자 추상화.

    구현체: infrastructure.downloader.ytdlp_adapter.YtDlpAdapter
    """

    def fetch_metadata(self, url: str) -> dict: ...

    def download_thumbnail(
        self, video_id: UUID, thumbnail_url: str, force: bool = False
    ) -> str | None: ...

    def download(
        self, url: str, settings: DownloadSettings, output_dir: Path | None = None
    ) -> Path: ...

    def fetch_user_playlists(self, cookie_opts: dict | None = None) -> list[dict]: ...

    def fetch_playlist_videos(
        self, playlist_id: str, cookie_opts: dict | None = None
    ) -> tuple[str, list[dict]]: ...

    def fetch_subscription_feed(
        self, limit: int = 100, cookie_opts: dict | None = None
    ) -> list[dict]: ...

    def fetch_subscribed_channels(self, cookie_opts: dict | None = None) -> list[dict]: ...

    def fetch_channel_videos(
        self, channel_url: str, limit: int = 30, cookie_opts: dict | None = None
    ) -> list[dict]: ...


# 진행률 콜백을 받아 미디어 소스 인스턴스를 생성하는 팩토리.
# 다운로드는 작업별 진행률 훅이 필요해 인스턴스를 새로 만들어야 하므로,
# composition root가 `lambda cb: YtDlpAdapter(on_progress=cb)` 형태로 주입한다.
MediaSourceFactory = Callable[[Callable[[object], None]], IMediaSource]


class IClipExtractor(Protocol):
    """ffmpeg 기반 클립/썸네일 추출 추상화.

    구현체: infrastructure.ffmpeg.ffmpeg_adapter.FfmpegAdapter
    """

    def extract_clip(
        self, source_path: Path, time_range: TimeRange, output_path: Path
    ) -> Path: ...

    def extract_thumbnail(
        self,
        source_path: Path,
        timestamp_sec: float,
        output_path: Path,
        width: int = 160,
        height: int = 90,
    ) -> Path: ...
