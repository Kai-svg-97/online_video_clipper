from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from config.settings import DOWNLOAD_DIR
from domain.clip.aggregates import ClipAggregate
from domain.clip.repositories import IClipRepository
from domain.clip.value_objects import TimeRange
from domain.shared.ports import IClipExtractor, IEventBus

logger = logging.getLogger(__name__)


@dataclass
class ExtractClipCommand:
    source_video_id: UUID
    source_file_path: str
    title: str
    start_sec: float
    end_sec: float
    output_path: str | None = None


@dataclass
class ExtractClipsCommand:
    """여러 구간을 한 번에 추출한다(챕터 → 클립).

    `ranges`는 (제목, 시작초, 끝초) 목록이다. **순차로 처리한다** — ffmpeg를 여러 개
    동시에 띄우면 저사양 PC(이 앱의 목표 사양)에서 디스크·CPU가 먼저 막힌다.
    """

    source_video_id: UUID
    source_file_path: str
    ranges: list[tuple[str, float, float]]


@dataclass
class DeleteClipCommand:
    clip_id: UUID
    delete_file: bool = False


class ExtractClipHandler:
    def __init__(
        self,
        repo: IClipRepository,
        ffmpeg: IClipExtractor,
        event_bus: IEventBus,
    ) -> None:
        self._repo = repo
        self._ffmpeg = ffmpeg
        self._bus = event_bus

    def handle(self, cmd: ExtractClipCommand) -> ClipAggregate:
        """Run in a background QThread — ffmpeg I/O blocks."""
        time_range = TimeRange(cmd.start_sec, cmd.end_sec)
        agg = ClipAggregate.create(cmd.source_video_id, cmd.title, time_range)

        out_path = (
            Path(cmd.output_path)
            if cmd.output_path
            else DOWNLOAD_DIR / "clips" / f"{agg.id}.mp4"
        )
        result_path = self._ffmpeg.extract_clip(
            Path(cmd.source_file_path), time_range, out_path
        )
        agg.set_file_path(str(result_path))
        self._repo.save(agg)
        self._bus.publish_all(agg.pull_events())
        return agg


class ExtractClipsHandler:
    """여러 구간을 순차 추출. 배경 QThread에서 호출한다.

    **한 구간이 실패해도 멈추지 않는다** — 챕터 20개 중 3번째가 깨졌다고 나머지
    17개를 버리면 사용자는 어디까지 됐는지 알 수 없다. 실패는 모아서 돌려준다.
    """

    def __init__(self, extract: ExtractClipHandler) -> None:
        self._extract = extract

    def handle(
        self,
        cmd: ExtractClipsCommand,
        on_progress: Callable[[int, int, str], None] | None = None,
    ) -> tuple[list[ClipAggregate], list[tuple[str, str]]]:
        """(성공한 클립들, [(제목, 오류메시지), ...])."""
        done: list[ClipAggregate] = []
        failed: list[tuple[str, str]] = []
        total = len(cmd.ranges)
        for i, (title, start, end) in enumerate(cmd.ranges, start=1):
            if on_progress is not None:
                on_progress(i, total, title)
            try:
                done.append(
                    self._extract.handle(
                        ExtractClipCommand(
                            source_video_id=cmd.source_video_id,
                            source_file_path=cmd.source_file_path,
                            title=title,
                            start_sec=start,
                            end_sec=end,
                        )
                    )
                )
            except Exception as exc:
                logger.exception("챕터 클립 추출 실패: %s", title)
                failed.append((title, str(exc)))
        return done, failed


class DeleteClipHandler:
    def __init__(self, repo: IClipRepository, event_bus: IEventBus) -> None:
        self._repo = repo
        self._bus = event_bus

    def handle(self, cmd: DeleteClipCommand) -> None:
        agg = self._repo.get_by_id(cmd.clip_id)
        if agg is None:
            return
        if cmd.delete_file and agg.clip.file_path:
            Path(agg.clip.file_path).unlink(missing_ok=True)
        agg.delete()
        self._repo.delete(cmd.clip_id)
        self._bus.publish_all(agg.pull_events())
