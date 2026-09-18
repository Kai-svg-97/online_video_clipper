"""모든 목록 델리게이트를 **실제로 그려 본다** — 죽지 않는가만 본다.

`paint()` 안에서 난 파이썬 예외는 PyQt가 프로세스 종료로 처리한다(0xC0000409).
로그도 예외 메시지도 남지 않고 앱이 사라지므로, 이 경로는 **직접 그려 보는 것** 말고
막을 방법이 없다(`CLAUDE.md` — 델리게이트 paint 규칙).

값이 맞는지는 각 기능의 테스트가 본다. 여기서는 **DTO에 필드가 늘거나 줄 때 그리는
쪽이 따라오지 못한 경우**를 잡는 게 목적이라, 극단값(None·0·빈 문자열·아주 긴 제목)을
섞어 모든 분기를 밟는다.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from PyQt6.QtCore import QRect, QSize
from PyQt6.QtGui import QPainter, QPixmap
from PyQt6.QtWidgets import QStyleOptionViewItem

from application.library.dtos import VideoDTO
from gui.panels.library.delegates import _IconDelegate, _ListDelegate
from gui.panels.library.models import VideoListModel


def _video(**over) -> VideoDTO:
    base = dict(
        id=uuid4(), url="https://youtu.be/abcdefghijk", title="영상",
        channel_name="채널", thumbnail_path="", duration_sec=600,
        favorite=False, watched=False, category_id=None,
    )
    base.update(over)
    return VideoDTO(**base)


# 그리는 쪽이 갈리는 지점들 — 하나라도 빠지면 그 분기가 검사되지 않는다.
CASES = {
    "기본": _video(),
    "길이_모름": _video(duration_sec=None),
    "길이_0": _video(duration_sec=0),
    "제목_빈값": _video(title=""),
    "제목_아주_김": _video(title="가" * 300),
    "즐겨찾기_시청함": _video(favorite=True, watched=True),
    "이어보기_중간": _video(last_position_ms=120_000, duration_sec=600),
    "이어보기_길이_모름": _video(last_position_ms=120_000, duration_sec=None),
    "태그_많음": _video(tag_names=tuple(f"태그{i}" for i in range(20))),
    "검색_일치_표시": _video(match_fields=("title", "channel_name", "subtitle")),
    "카테고리_이름_있음": _video(category_id=uuid4(), category_name="음악"),
    "조회수_없음": _video(view_count=None, published_at=None, created_at=None),
    "썸네일_경로_없는_파일": _video(thumbnail_path="Z:/없는/경로.jpg"),
}


@pytest.fixture
def model(qapp_instance):
    return VideoListModel()


def _paint(delegate, model, width=260, height=220) -> None:
    pm = QPixmap(QSize(width, height))
    pm.fill()
    painter = QPainter(pm)
    try:
        option = QStyleOptionViewItem()
        option.rect = QRect(0, 0, width, height)
        delegate.paint(painter, option, model.index(0, 0))
    finally:
        painter.end()


@pytest.mark.parametrize("case", list(CASES))
class TestLibraryDelegatesSurvive:
    def test_아이콘_카드를_그린다(self, model, case):
        model.set_videos([CASES[case]])
        _paint(_IconDelegate(), model)

    def test_리스트_줄을_그린다(self, model, case):
        model.set_videos([CASES[case]])
        _paint(_ListDelegate(), model, width=800, height=90)


class TestSelectedState:
    def test_선택된_상태로도_그린다(self, model):
        """선택 표시는 별도 분기라 기본 상태만 그려서는 밟지 않는다."""
        from PyQt6.QtWidgets import QStyle

        model.set_videos([_video()])
        pm = QPixmap(QSize(260, 220))
        pm.fill()
        painter = QPainter(pm)
        try:
            option = QStyleOptionViewItem()
            option.rect = QRect(0, 0, 260, 220)
            option.state |= QStyle.StateFlag.State_Selected
            _IconDelegate().paint(painter, option, model.index(0, 0))
        finally:
            painter.end()

    def test_빈_모델은_그릴_것이_없다(self, model):
        model.set_videos([])
        assert model.rowCount() == 0
