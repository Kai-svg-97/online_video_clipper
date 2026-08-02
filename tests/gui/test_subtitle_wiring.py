"""뷰모델·패널 배선 검증 — 싱크 가사 조회 요청, 오프셋 디바운스 저장.

DB·네트워크 없이 핸들러를 목으로 대체해 '무엇이 호출되는가'만 본다.
"""
from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

from application.song.dtos import LyricsLineDTO, SongInfoDTO
from gui.view_models.song_vm import SongViewModel


def _vm(qapp_instance, **overrides) -> SongViewModel:
    kwargs = dict(
        get_song_info=MagicMock(**{"handle.return_value": None}),
        fetch_song=MagicMock(),
        set_flag=MagicMock(),
        update_field=MagicMock(),
        update_lyrics=MagicMock(),
        translate_lyrics=MagicMock(),
        set_lyrics_offset=MagicMock(),
        list_sources=MagicMock(**{"handle.return_value": []}),
        add_source=MagicMock(),
        update_source=MagicMock(),
        delete_source=MagicMock(),
        reorder_sources=MagicMock(),
    )
    kwargs.update(overrides)
    return SongViewModel(**kwargs)


class TestFetchSyncedLyrics:
    def test_synced_only_커맨드로_조회한다(self, qapp_instance):
        vm = _vm(qapp_instance)
        video_id = uuid4()
        vm.fetch_synced_lyrics(video_id)
        # 워커가 끝날 때까지 기다린다(짧은 목 호출)
        for worker in list(vm._workers):
            worker.wait(3000)
        cmd = vm._fetch.handle.call_args[0][0]
        assert cmd.synced_only is True
        assert cmd.force is True
        assert cmd.fetch_lyrics is True
        assert cmd.video_id == video_id

    def test_같은_영상_중복_조회를_막는다(self, qapp_instance):
        vm = _vm(qapp_instance)
        video_id = uuid4()
        vm._in_flight.add(video_id)
        vm.fetch_synced_lyrics(video_id)
        assert vm._fetch.handle.called is False


class TestSetLyricsOffset:
    def test_핸들러에_오프셋을_넘긴다(self, qapp_instance):
        handler = MagicMock()
        vm = _vm(qapp_instance, set_lyrics_offset=handler)
        video_id = uuid4()
        vm.set_lyrics_offset(video_id, 1500)
        cmd = handler.handle.call_args[0][0]
        assert cmd.video_id == video_id
        assert cmd.offset_ms == 1500

    def test_핸들러_예외는_error_occurred로_보고된다(self, qapp_instance):
        handler = MagicMock()
        handler.handle.side_effect = RuntimeError("실패")
        vm = _vm(qapp_instance, set_lyrics_offset=handler)
        seen: list[str] = []
        vm.error_occurred.connect(seen.append)
        vm.set_lyrics_offset(uuid4(), 100)
        assert seen and "실패" in seen[0]

    def test_핸들러가_없으면_조용히_넘어간다(self, qapp_instance):
        vm = _vm(qapp_instance, set_lyrics_offset=None)
        vm.set_lyrics_offset(uuid4(), 100)   # 예외가 나면 안 된다


class TestDetailWidgetTrack:
    def test_싱크_가사를_주면_플레이어에_트랙이_실린다(self, qapp_instance):
        from gui.panels.video_detail_panel import VideoDetailWidget

        widget = VideoDetailWidget()
        dto = SongInfoDTO(
            video_id=uuid4(), is_song=True,
            lyrics_lines=(
                LyricsLineDTO(original="a", translation="가", start_ms=1000),
                LyricsLineDTO(original="b", start_ms=3000),
            ),
            lyrics_offset_ms=750,
        )
        widget.set_song_info(dto)
        assert widget._player._track is not None
        assert widget._player._track.offset_ms == 750
        assert len(widget._player._track) == 2
        widget.deleteLater()

    def test_시간_정보가_없으면_트랙이_없다(self, qapp_instance):
        from gui.panels.video_detail_panel import VideoDetailWidget

        widget = VideoDetailWidget()
        dto = SongInfoDTO(
            video_id=uuid4(), is_song=True,
            lyrics_lines=(LyricsLineDTO(original="a"),),
        )
        widget.set_song_info(dto)
        assert widget._player._track is None
        widget.deleteLater()

    def test_None_dto도_안전하다(self, qapp_instance):
        from gui.panels.video_detail_panel import VideoDetailWidget

        widget = VideoDetailWidget()
        widget.set_song_info(None)
        assert widget._player._track is None
        widget.deleteLater()
