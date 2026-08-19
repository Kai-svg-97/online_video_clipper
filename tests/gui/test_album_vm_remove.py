"""AlbumViewModel.remove_track_link — 잘못 붙은 자동 매핑을 지우는 즉시 처리 경로.

DB 삭제 한 줄이라 네트워크가 없다 — QThread 없이 동기로 처리하고, 성공하면 그 슬롯을
'없음'으로 되돌린 DTO를 실어 ``track_removed``를 방출한다. 화면은 전체를 다시 조회하지
않고 그 자리만 갱신해야 다른 슬롯의 자동 채우기 결과가 섞여 들어올 여지가 없다.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from application.song.album_dtos import (
    TRACK_ORIGIN_AUTO,
    TRACK_ORIGIN_LIBRARY,
    TRACK_ORIGIN_MISSING,
    AlbumDetailDTO,
    AlbumTrackDTO,
)
from application.song.album_queries import RemoveAlbumTrackLinkCommand
from gui.view_models.album_vm import AlbumViewModel


def _vm(remove_handler=None) -> AlbumViewModel:
    return AlbumViewModel(
        get_albums=MagicMock(),
        get_detail=MagicMock(),
        remove_track_link=remove_handler,
    )


def _detail_with(*tracks) -> AlbumDetailDTO:
    return AlbumDetailDTO(key="artist\x1falbum", album_title="Album", artist="Artist",
                          tracks=list(tracks))


class TestRemoveTrackLink:
    def test_핸들러에_슬롯을_넘기고_삭제한다(self, qapp_instance):
        handler = MagicMock()
        vm = _vm(handler)
        vm._detail = _detail_with(
            AlbumTrackDTO(track_no=1, title="A", origin=TRACK_ORIGIN_LIBRARY),
            AlbumTrackDTO(track_no=2, title="B", origin=TRACK_ORIGIN_AUTO,
                          stream_url="https://x/v"),
        )

        vm.remove_track_link(disc_no=1, track_no=2)

        handler.handle.assert_called_once_with(
            RemoveAlbumTrackLinkCommand(album_key="artist\x1falbum", disc_no=1, track_no=2)
        )

    def test_성공하면_없음_DTO로_신호를_낸다(self, qapp_instance):
        handler = MagicMock()
        vm = _vm(handler)
        vm._detail = _detail_with(
            AlbumTrackDTO(track_no=2, title="B", artist="Artist", duration_sec=200,
                         origin=TRACK_ORIGIN_AUTO, stream_url="https://x/v"),
        )
        seen: list = []
        vm.track_removed.connect(seen.append)

        vm.remove_track_link(disc_no=1, track_no=2)

        assert len(seen) == 1
        assert seen[0].origin == TRACK_ORIGIN_MISSING
        assert seen[0].title == "B" and seen[0].artist == "Artist"
        assert seen[0].duration_sec == 200
        assert seen[0].stream_url == ""   # 스트림 정보는 지워진다

    def test_해당_슬롯이_없으면_아무_일도_하지_않는다(self, qapp_instance):
        handler = MagicMock()
        vm = _vm(handler)
        vm._detail = _detail_with(
            AlbumTrackDTO(track_no=1, title="A", origin=TRACK_ORIGIN_AUTO),
        )
        seen: list = []
        vm.track_removed.connect(seen.append)

        vm.remove_track_link(disc_no=1, track_no=99)

        handler.handle.assert_not_called()
        assert seen == []

    def test_핸들러가_없으면_아무_일도_하지_않는다(self, qapp_instance):
        vm = _vm(remove_handler=None)
        vm._detail = _detail_with(
            AlbumTrackDTO(track_no=1, title="A", origin=TRACK_ORIGIN_AUTO),
        )
        seen: list = []
        vm.track_removed.connect(seen.append)

        vm.remove_track_link(disc_no=1, track_no=1)   # 예외 없이 조용히 무시

        assert seen == []

    def test_상세가_없으면_아무_일도_하지_않는다(self, qapp_instance):
        handler = MagicMock()
        vm = _vm(handler)

        vm.remove_track_link(disc_no=1, track_no=1)

        handler.handle.assert_not_called()

    def test_실패하면_오류_신호를_내고_삭제_신호는_내지_않는다(self, qapp_instance):
        handler = MagicMock()
        handler.handle.side_effect = RuntimeError("DB 오류")
        vm = _vm(handler)
        vm._detail = _detail_with(
            AlbumTrackDTO(track_no=1, title="A", origin=TRACK_ORIGIN_AUTO),
        )
        removed: list = []
        errors: list = []
        vm.track_removed.connect(removed.append)
        vm.error_occurred.connect(errors.append)

        vm.remove_track_link(disc_no=1, track_no=1)

        assert removed == []
        assert errors and "DB 오류" in errors[0]
