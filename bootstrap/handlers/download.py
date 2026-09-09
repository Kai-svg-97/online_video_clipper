"""다운로드 큐·이력 유스케이스 조립."""

from __future__ import annotations

from application.download.commands import CancelDownloadHandler, StartDownloadHandler
from application.download.event_bridge import DownloadEventBridge
from application.download.queries import GetDownloadHistoryHandler, GetDownloadQueueHandler
from infrastructure.downloader.ytdlp_adapter import YtDlpAdapter

from bootstrap.context import DownloadHandlers, LibraryHandlers, Repositories, Services


def build(
    repos: Repositories,
    services: Services,
    library: LibraryHandlers,
) -> DownloadHandlers:
    return DownloadHandlers(
        start=StartDownloadHandler(
            services.download_queue,
            repos.download,
            services.media_source,
            services.event_bus,
            # 작업마다 진행률 훅이 달라 어댑터를 새로 만든다 — 그래서 인스턴스가
            # 아니라 **팩토리 콜백**을 주입한다(프로젝트의 ports 규약).
            make_downloader=lambda cb: YtDlpAdapter(on_progress=cb),
            add_video_handler=library.add_video,
            gemini_extractor=services.summary_source,
        ),
        cancel=CancelDownloadHandler(services.download_queue, services.event_bus),
        get_queue=GetDownloadQueueHandler(services.download_queue),
        get_history=GetDownloadHistoryHandler(repos.download),
        # 도메인 이벤트 → 애플리케이션 콜백 변환
        event_bridge=DownloadEventBridge(services.event_bus),
    )
