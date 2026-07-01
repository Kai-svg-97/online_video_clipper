from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from domain.download.aggregates import DownloadQueueAggregate
from domain.download.entities import DownloadJob
from domain.download.repositories import IDownloadRepository
from domain.download.value_objects import DownloadSettings
from domain.shared.ports import IEventBus, IMediaSource, MediaSourceFactory

logger = logging.getLogger(__name__)


@dataclass
class StartDownloadCommand:
    url: str
    title: str
    settings: DownloadSettings | None = None
    output_dir: Path | None = None


@dataclass
class CancelDownloadCommand:
    job_id: UUID


@dataclass
class RetryDownloadCommand:
    job_id: UUID


# ------------------------------------------------------------------
# Handlers
# ------------------------------------------------------------------

class StartDownloadHandler:
    def __init__(
        self,
        queue: DownloadQueueAggregate,
        repo: IDownloadRepository,
        ytdlp: IMediaSource,
        event_bus: IEventBus,
        make_downloader: MediaSourceFactory | None = None,
        add_video_handler=None,
        gemini_extractor=None,
    ) -> None:
        self._queue = queue
        self._repo = repo
        self._ytdlp = ytdlp
        self._bus = event_bus
        # 다운로드는 작업별 진행률 훅이 필요해 새 인스턴스를 만들어야 한다.
        # composition root가 팩토리를 주입하지 않으면 진행률 없이 주입된 소스를 쓴다.
        self._make_downloader = make_downloader
        self._add_video = add_video_handler
        self._gemini = gemini_extractor

    def handle(self, cmd: StartDownloadCommand) -> DownloadJob:
        job = DownloadJob.create(
            url=cmd.url,
            title=cmd.title,
            settings=cmd.settings,
        )
        self._queue.enqueue(job)
        self._repo.save(job)
        return job

    def execute_job(self, job_id: UUID, output_dir: Path | None = None) -> None:
        """Run the actual download. Call from a background QThread."""
        self._queue.start(job_id)
        self._bus.publish_all(self._queue.pull_events())

        job = next((j for j in self._queue.running_jobs() if j.id == job_id), None)
        if job is None:
            return

        def on_progress(progress):
            self._queue.update_progress(job_id, progress)
            self._bus.publish_all(self._queue.pull_events())

        adapter = (
            self._make_downloader(on_progress)
            if self._make_downloader is not None
            else self._ytdlp
        )
        try:
            file_path = adapter.download(job.url, job.settings, output_dir)
            self._queue.complete(job_id, str(file_path))
            job.file_path = str(file_path)
            # Same url+quality+format: keep only the newest file
            self._repo.delete_completed_duplicates(
                job.url,
                job.settings.quality.value,
                job.settings.format.value,
                job_id,
            )
            self._repo.save(job)
            # 다운로드 성공 시에만 Gemini 요약 캡처 시도
            if job.settings.capture_gemini and self._gemini is not None:
                logger.info("Gemini 요약 추출 시작: %s", job.url)
                self._save_gemini_to_library(job.url)
        except Exception as exc:
            self._queue.fail(job_id, str(exc))
            self._repo.save(job)  # job already has FAILED status + error_msg set by fail()
        finally:
            self._bus.publish_all(self._queue.pull_events())

    def _save_gemini_to_library(self, url: str) -> None:
        """Gemini 요약 텍스트를 추출해 라이브러리 영상 메모에 저장한다.

        실패해도 다운로드 결과에 영향을 주지 않는다.
        """
        if self._add_video is None:
            return
        try:
            summary = self._gemini.extract(url)
            if not summary:
                logger.debug("Gemini 요약 없음 (버튼 미발견 또는 미로그인): %s", url)
                return
            from application.library.commands import AddVideoCommand  # noqa: PLC0415
            self._add_video.handle(AddVideoCommand(url=url, initial_gemini_summary=summary))
            logger.info("Gemini 요약 메모 저장 완료 (%d자): %s", len(summary), url)
        except Exception:
            logger.exception("Gemini 요약 라이브러리 저장 실패 (무시)")


class CancelDownloadHandler:
    def __init__(self, queue: DownloadQueueAggregate, event_bus: IEventBus) -> None:
        self._queue = queue
        self._bus = event_bus

    def handle(self, cmd: CancelDownloadCommand) -> None:
        self._queue.cancel(cmd.job_id)
        self._bus.publish_all(self._queue.pull_events())
