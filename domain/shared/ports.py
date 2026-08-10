"""애플리케이션 레이어가 의존하는 포트(추상화) 정의.

UpdateInfo와 IUpdateChecker도 여기 정의한다 — 업데이트 확인은
application → domain/shared 의존만 허용한다.

DDD 의존성 규칙(`gui → application → domain ← infrastructure`)에 따라
application 레이어는 infrastructure의 구체 클래스(EventBus, YtDlpAdapter,
FfmpegAdapter)를 직접 import 해서는 안 된다. 대신 여기 정의된 Protocol에
의존하고, infrastructure의 어댑터들이 구조적 타이핑(structural typing)으로
이 Protocol을 만족시킨다 — 어댑터는 상속·등록 없이 메서드 시그니처만 맞으면 된다.

런타임 배선은 composition root(`main.py`)가 구체 어댑터를 주입한다.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from uuid import UUID

from domain.clip.value_objects import TimeRange
from domain.download.value_objects import DownloadSettings


@dataclass(frozen=True, slots=True)
class UpdateInfo:
    """GitHub 릴리스 자산 정보 — 도메인 값객체."""

    version: str          # '1.0.1' (v 접두사 없음)
    asset_name: str       # 'YouTubeContentManager-setup.exe'
    download_url: str
    size_bytes: int
    sha256: str | None    # 체크섬 (있으면 검증, 없으면 크기 검증)
    release_notes: str    # GitHub Release 본문


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
        self,
        video_id: UUID,
        thumbnail_url: str,
        force: bool = False,
        max_age_days: int | None = None,
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


class IUpdateChecker(Protocol):
    """GitHub Releases 기반 업데이트 확인·다운로드 추상화.

    구현체: infrastructure.updater.update_checker.GithubUpdateChecker
    """

    def check_latest(self) -> UpdateInfo | None: ...

    def download_asset(
        self,
        info: UpdateInfo,
        dest_dir: Path,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> Path: ...


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


class ILibraryPackageWriter(Protocol):
    """포터블 라이브러리 패키지(zip) 작성 추상화.

    구현체: infrastructure.transfer.portable_package.ZipLibraryPackageWriter

    `manifest`/`data`는 순수 dict(JSON 직렬화 가능)이다. `data["videos"][i]`에
    `thumbnail_path`(THUMBNAIL_DIR 기준 상대경로)가 있으면 구현체가 실제 파일을
    찾아 패키지에 포함하고, 패키지 내부 참조용 `thumbnail_rel` 키를 같은 딱셔너리에
    채워 넣은 뒤 저장한다 — application 레이어는 절대경로/THUMBNAIL_DIR를 몰라도 된다.
    """

    def write(self, dest_path: str, manifest: dict, data: dict) -> None: ...


class ILibraryPackageReader(Protocol):
    """포터블 라이브러리 패키지(zip) 읽기 추상화.

    구현체: infrastructure.transfer.portable_package.ZipLibraryPackageReader
    """

    def read(self, src_path: str) -> tuple[dict, dict]:
        """(manifest, data) — write()가 만든 것과 동일한 순수 dict."""
        ...

    def import_thumbnail(self, src_path: str, thumbnail_rel: str, video_id: UUID) -> str | None:
        """패키지 속 썸네일을 로컬 THUMBNAIL_DIR로 복사하고 상대경로를 반환한다.

        `IMediaSource.download_thumbnail`과 동일한 반환 규약(THUMBNAIL_DIR 기준
        상대경로 또는 실패 시 None)이라 application 레이어의 처리 방식이 같다.
        """
        ...


class ISummarySource(Protocol):
    """YouTube Gemini AI 요약 추출 추상화.

    구현체: infrastructure.browser.gemini_extractor.GeminiExtractor

    로그인 쿠키가 없거나 요약 버튼을 찾지 못하면 예외 대신 빈 문자열 또는 None을
    반환한다(호출 측은 falsy 검사로 실패를 판별한다).
    """

    def extract(self, url: str) -> str | None: ...
