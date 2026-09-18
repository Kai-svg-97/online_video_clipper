"""다운로드 카드를 **실제로 그려 본다**.

`QStyledItemDelegate.paint()` 안에서 난 파이썬 예외는 PyQt 가 프로세스 종료로
처리한다(Windows 에서 0xC0000409). 그래서 이 경로의 실수는 예외 메시지도 없이
**앱이 그냥 사라지는** 형태로 나타난다 — 로그도 남지 않는다.

실제로 그런 일이 있었다. v1.27.0 의 라이브 녹화 진행 표시가 `progress.is_indeterminate`
를 읽는데, 화면으로 나가는 `DownloadProgressDTO` 에는 그 속성이 없었다(도메인
`DownloadProgress` 에만 있었다). 다운로드 카드가 하나라도 보이는 순간 앱이 죽었다.

그래서 여기서는 '값을 잘 계산했나'가 아니라 **그리다가 죽지 않는가**를 본다.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from PyQt6.QtCore import QRect, QSize
from PyQt6.QtGui import QPainter, QPixmap
from PyQt6.QtWidgets import QStyleOptionViewItem

from application.download.dtos import DownloadJobDTO, DownloadProgressDTO
from application.download.queries import _to_dto
from domain.download.entities import DownloadJob
from domain.download.value_objects import DownloadProgress
from gui.panels.download_panel import _HistoryCardDelegate, _HistoryModel


def _paint(model: _HistoryModel, row: int = 0) -> None:
    """한 줄을 실제로 그린다 — 그리다 죽으면 테스트가 아니라 프로세스가 끝난다."""
    pm = QPixmap(QSize(400, 300))
    pm.fill()
    painter = QPainter(pm)
    try:
        option = QStyleOptionViewItem()
        option.rect = QRect(0, 0, 400, 300)
        _HistoryCardDelegate().paint(painter, option, model.index(row, 0))
    finally:
        painter.end()


def _job(progress: DownloadProgressDTO, status: str = "downloading") -> DownloadJobDTO:
    return DownloadJobDTO(
        id=uuid4(), url="https://youtu.be/abcdefghijk", title="영상",
        status=status, progress=progress,
    )


@pytest.fixture
def model(qapp_instance):
    return _HistoryModel()


class TestDtoCarriesEverythingPaintNeeds:
    def test_진행_DTO에_총량_정보가_있다(self):
        """없으면 카드를 그리는 순간 앱이 죽는다 — 필드가 사라지면 여기서 걸린다."""
        dto = DownloadProgressDTO()
        assert hasattr(dto, "is_indeterminate")
        assert hasattr(dto, "downloaded_bytes")
        assert hasattr(dto, "elapsed_sec")

    def test_도메인_값을_빠짐없이_옮긴다(self):
        job = DownloadJob.create(url="https://youtu.be/abcdefghijk", title="영상")
        job.progress = DownloadProgress(
            percent=42.0, speed_bps=1024.0, eta_sec=10,
            downloaded_bytes=2048, total_bytes=4096, elapsed_sec=7.5,
        )

        dto = _to_dto(job).progress

        assert dto.percent == 42.0
        assert dto.downloaded_bytes == 2048
        assert dto.total_bytes == 4096
        assert dto.elapsed_sec == 7.5
        assert dto.is_indeterminate is False

    def test_총량을_모르면_그렇다고_옮긴다(self):
        job = DownloadJob.create(url="https://youtu.be/abcdefghijk", title="방송")
        job.progress = DownloadProgress(
            downloaded_bytes=999, total_bytes=0, elapsed_sec=61.0
        )
        assert _to_dto(job).progress.is_indeterminate is True


class TestPaintDoesNotDie:
    def test_진행_중_카드를_그린다(self, model):
        model.set_all(
            [_job(DownloadProgressDTO(percent=37.0, total_bytes=4096,
                                      downloaded_bytes=1516))],
            [],
        )
        _paint(model)

    def test_라이브_녹화_카드를_그린다(self, model):
        """총량을 모르는 카드 — 여기서 실제로 앱이 죽었다."""
        model.set_all(
            [_job(DownloadProgressDTO(downloaded_bytes=10_485_760, elapsed_sec=125.0))],
            [],
        )
        _paint(model)

    def test_대기_중_카드를_그린다(self, model):
        job = _job(DownloadProgressDTO(), status="pending")
        model.set_all([job], [], waiting_ids={job.id})
        _paint(model)

    def test_기본값만_있는_카드를_그린다(self, model):
        """막 큐에 들어가 아무 값도 안 채워진 상태."""
        model.set_all([_job(DownloadProgressDTO())], [])
        _paint(model)

    def test_끝난_카드를_그린다(self, model):
        model.set_all([], [_job(DownloadProgressDTO(percent=100.0), status="completed")])
        _paint(model)

    def test_실패_카드를_그린다(self, model):
        model.set_all([], [_job(DownloadProgressDTO(), status="failed")])
        _paint(model)
