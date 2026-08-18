"""상세화면 우측 목록 아래의 '추천 영상' 구역을 검증한다.

두 가지를 못박는다.
1. 연관 영상과 추천 영상이 **각자의 구역**에 쌓인다 — 예전 `_RelatedList`는 한
   레이아웃에 헤더·행·스트레치를 늘어놓고 인덱스로 지웠기 때문에, 구역이 둘이 되면
   삽입/삭제 위치가 조용히 어긋난다.
2. 추천은 **재생목록(`_playlist`)에 들어가지 않는다** — 자동 다음곡이 라이브러리 밖
   영상으로 새어나가면 안 된다.
"""
from __future__ import annotations

from uuid import uuid4

from gui.panels.video_detail_panel import RelatedItem, VideoDetailWidget, _RelatedRow


def _item(title="영상", key=None, payload=None) -> RelatedItem:
    return RelatedItem(
        key=key or title,
        title=title,
        channel="채널",
        duration_sec=100,
        meta_text="",
        payload=payload if payload is not None else uuid4(),
        thumb_path="",
        thumb_url="",          # 네트워크 썸네일 로더가 뜨지 않게 빈 값
        yt_video_id="",
    )


def _rows(layout) -> list[_RelatedRow]:
    return [
        layout.itemAt(i).widget()
        for i in range(layout.count())
        if isinstance(layout.itemAt(i).widget(), _RelatedRow)
    ]


class TestRelatedListSections:
    def test_추천은_연관_영상_아래_별도_구역에_쌓인다(self, qtbot):
        w = VideoDetailWidget()
        qtbot.addWidget(w)
        rel = w._related

        rel.set_items([_item("연관1"), _item("연관2")])
        rel.set_recommendations([_item("추천1")])

        assert [r._item.title for r in _rows(rel._rel_layout)] == ["연관1", "연관2"]
        assert [r._item.title for r in _rows(rel._rec_layout)] == ["추천1"]
        assert rel._rec_header.isVisibleTo(rel)

    def test_연관_목록_갱신이_추천_구역을_지우지_않는다(self, qtbot):
        w = VideoDetailWidget()
        qtbot.addWidget(w)
        rel = w._related
        rel.set_recommendations([_item("추천1")])

        rel.set_items([_item("연관A")])

        assert [r._item.title for r in _rows(rel._rec_layout)] == ["추천1"]

    def test_추천이_없으면_헤더째_감춘다(self, qtbot):
        w = VideoDetailWidget()
        qtbot.addWidget(w)
        rel = w._related
        rel.set_recommendations([_item("추천1")])

        rel.set_recommendations([])

        assert _rows(rel._rec_layout) == []
        assert not rel._rec_header.isVisibleTo(rel)


class TestPlaylistBoundary:
    def test_추천은_재생목록에_포함되지_않는다(self, qtbot):
        w = VideoDetailWidget()
        qtbot.addWidget(w)
        related = [_item("연관1"), _item("연관2")]

        w.set_related(related)
        w.set_recommendations([_item("추천1")])

        assert w._playlist == [it.payload for it in related]
