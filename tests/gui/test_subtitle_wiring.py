"""뷰모델·패널 배선 검증 — 싱크 가사 조회 요청, 오프셋 디바운스 저장.

DB·네트워크 없이 핸들러를 목으로 대체해 '무엇이 호출되는가'만 본다.
"""
from __future__ import annotations

from types import SimpleNamespace
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


class TestOffsetDebounceRace:
    """오프셋 디바운스 저장이 영상 전환과 경합하지 않는지 검증한다(리뷰 지적 사항).

    500ms 타이머를 실제로 기다리지 않고 `_flush_offset()`을 직접 호출해 결정적으로
    검증한다(실제 sleep 없음). `widget._detail`은 `.id`만 있으면 되므로 전체
    VideoDetailDTO 대신 가벼운 스텁으로 영상 전환을 흉내낸다.
    """

    def test_타이머가_끝나기_전에_다음_영상으로_전환해도_원래_영상에_저장된다(self, qapp_instance):
        from gui.panels.video_detail_panel import VideoDetailWidget

        widget = VideoDetailWidget()
        video_a = SimpleNamespace(id=uuid4())
        video_b = SimpleNamespace(id=uuid4())
        widget._detail = video_a
        widget._on_subtitle_offset_changed(500)   # A에서 조정
        widget._detail = video_b                  # 타이머가 끝나기 전 B로 전환(자동재생 등)

        seen: list[tuple] = []
        widget.song_offset_saved.connect(lambda vid, ms: seen.append((vid, ms)))
        widget._flush_offset()

        assert seen == [(video_a.id, 500)]
        widget.deleteLater()

    def test_평상시엔_현재_영상_id로_저장된다(self, qapp_instance):
        from gui.panels.video_detail_panel import VideoDetailWidget

        widget = VideoDetailWidget()
        video_id = uuid4()
        widget._detail = SimpleNamespace(id=video_id)
        widget._on_subtitle_offset_changed(250)

        seen: list[tuple] = []
        widget.song_offset_saved.connect(lambda vid, ms: seen.append((vid, ms)))
        widget._flush_offset()

        assert seen == [(video_id, 250)]
        widget.deleteLater()

    def test_연속_조정은_한_번만_마지막_값으로_저장된다(self, qapp_instance):
        from gui.panels.video_detail_panel import VideoDetailWidget

        widget = VideoDetailWidget()
        video_id = uuid4()
        widget._detail = SimpleNamespace(id=video_id)
        widget._on_subtitle_offset_changed(100)
        widget._on_subtitle_offset_changed(200)
        widget._on_subtitle_offset_changed(300)

        seen: list[tuple] = []
        widget.song_offset_saved.connect(lambda vid, ms: seen.append((vid, ms)))
        widget._flush_offset()

        assert seen == [(video_id, 300)]
        widget.deleteLater()

    def test_스트리밍_중에는_저장하지_않는다(self, qapp_instance):
        from gui.panels.video_detail_panel import VideoDetailWidget

        widget = VideoDetailWidget()
        widget._detail = SimpleNamespace(id=uuid4())
        widget._streaming = True
        widget._on_subtitle_offset_changed(400)

        seen: list[tuple] = []
        widget.song_offset_saved.connect(lambda vid, ms: seen.append((vid, ms)))
        widget._flush_offset()

        assert seen == []
        widget.deleteLater()


class TestLyricsSeekAndHighlight:
    """가사 줄 클릭 seek 연산과 현재 줄 하이라이트 해제 변환 — 한 줄 로직이지만
    부호 반전이나 `subtitle_offset_ms`가 프로퍼티로 바뀌는 리팩터를 회귀로 잡기 위한 테스트."""

    def test_가사_줄_클릭은_오프셋을_더해_seek한다(self, qapp_instance):
        from gui.panels.video_detail_panel import VideoDetailWidget

        widget = VideoDetailWidget()
        widget._player.subtitle_offset_ms = MagicMock(return_value=750)
        widget._player.seek_to_ms = MagicMock()

        widget._on_lyrics_seek(2000)

        widget._player.seek_to_ms.assert_called_once_with(2750)
        widget.deleteLater()

    def test_현재_줄_인덱스가_음수면_하이라이트를_해제한다(self, qapp_instance):
        from gui.panels.video_detail_panel import VideoDetailWidget

        widget = VideoDetailWidget()
        widget._song_tab.set_current_line = MagicMock()

        widget._on_current_line_changed(-1)

        widget._song_tab.set_current_line.assert_called_once_with(None)
        widget.deleteLater()
