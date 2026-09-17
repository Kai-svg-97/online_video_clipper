"""음원 태그 기록 — 가사 직렬화와 `DownloadCompleted` 구독 규칙.

이 서비스의 위험은 "조용히 안 도는 것"이다(태깅은 실패해도 다운로드가 성공으로
보고된다). 그래서 **돌지 않아야 할 조건**을 하나씩 고정한다.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from application.song.tagging import SongTagWriter, build_audio_tags, build_lyrics_text
from domain.download.events import DownloadCompleted
from domain.song.entities import SongInfo
from domain.song.value_objects import LyricsLine


def _song(**kw) -> SongInfo:
    base = dict(video_id=uuid4(), is_song=True, artist="아티스트", album="앨범",
                song_title="제목", release_year="2024")
    base.update(kw)
    return SongInfo(**base)


class TestLyricsText:
    def test_싱크가_없으면_평문이다(self):
        info = _song(lyrics_lines=[LyricsLine("첫 줄"), LyricsLine("둘째 줄")])
        assert build_lyrics_text(info) == "첫 줄\n둘째 줄"

    def test_싱크가_있으면_LRC_시간표기가_붙는다(self):
        info = _song(lyrics_lines=[LyricsLine("첫 줄", start_ms=0),
                                   LyricsLine("둘째 줄", start_ms=65_430)])
        assert build_lyrics_text(info) == "[00:00.00]첫 줄\n[01:05.43]둘째 줄"

    def test_번역은_원문_아래_같은_시각으로_들어간다(self):
        info = _song(lyrics_lines=[LyricsLine("hello", translation="안녕", start_ms=1_000)])
        assert build_lyrics_text(info) == "[00:01.00]hello\n[00:01.00]안녕"

    def test_싱크_보정값은_반영하지_않는다(self):
        """보정값은 '이 영상과 이 가사'의 어긋남이라 다른 플레이어에선 뜻이 없다."""
        info = _song(lyrics_lines=[LyricsLine("줄", start_ms=1_000)], lyrics_offset_ms=5_000)
        assert build_lyrics_text(info) == "[00:01.00]줄"

    def test_가사가_없으면_빈_문자열(self):
        assert build_lyrics_text(_song(lyrics_lines=[])) == ""


class TestBuildTags:
    def test_빈_필드는_빈_채로_둔다(self):
        tags = build_audio_tags(_song(album="", release_year=""), None)
        assert tags.album == ""
        assert tags.year == ""
        assert tags.artist == "아티스트"

    def test_아무것도_없으면_is_empty(self):
        info = SongInfo(video_id=uuid4(), is_song=True)
        assert build_audio_tags(info, None).is_empty()


# ----------------------------------------------------------------------
# 구독 규칙
# ----------------------------------------------------------------------

class _Bus:
    def __init__(self):
        self.handler = None

    def subscribe(self, event_type, handler):
        self.handler = handler


class _VideoAgg:
    def __init__(self, vid):
        self.id = vid
        self.video = type("V", (), {"thumbnail_path": ""})()


class _VideoRepo:
    def __init__(self, agg=None):
        self._agg = agg

    def get_by_url(self, url):
        return self._agg


class _SongRepo:
    def __init__(self, info=None):
        self._info = info

    def get(self, video_id):
        if self._info is None:
            return None
        return type("Agg", (), {"info": self._info})()


class _Tagger:
    def __init__(self):
        self.calls: list[tuple[Path, object]] = []

    def write_tags(self, file_path, tags):
        self.calls.append((file_path, tags))
        return True


@pytest.fixture
def wired(monkeypatch):
    """구독자 + 협력자 묶음. `WRITE_SONG_TAGS`는 켠 상태로 시작한다."""
    from config import settings as cfg
    monkeypatch.setattr(cfg, "WRITE_SONG_TAGS", True, raising=False)

    _DEFAULT = object()

    def build(*, video_agg=_DEFAULT, song_info=None):
        bus = _Bus()
        tagger = _Tagger()
        agg = _VideoAgg(uuid4()) if video_agg is _DEFAULT else video_agg
        SongTagWriter(bus, _VideoRepo(agg), _SongRepo(song_info), tagger)
        return bus, tagger

    return build


def _fire(bus, path: str, url: str = "https://y/1"):
    bus.handler(DownloadCompleted(job_id=uuid4(), url=url, file_path=path))


class TestSubscription:
    def test_음원이면_태그를_쓴다(self, wired):
        bus, tagger = wired(song_info=_song())
        _fire(bus, "C:/x/노래.mp3")
        assert len(tagger.calls) == 1
        assert tagger.calls[0][1].artist == "아티스트"

    def test_영상_파일은_건너뛴다(self, wired):
        bus, tagger = wired(song_info=_song())
        _fire(bus, "C:/x/영상.mp4")
        assert tagger.calls == []

    def test_노래로_표시되지_않았으면_건너뛴다(self, wired):
        bus, tagger = wired(song_info=_song(is_song=False))
        _fire(bus, "C:/x/노래.mp3")
        assert tagger.calls == []

    def test_노래_정보가_없으면_건너뛴다(self, wired):
        bus, tagger = wired(song_info=None)
        _fire(bus, "C:/x/노래.mp3")
        assert tagger.calls == []

    def test_라이브러리에_없는_URL이면_건너뛴다(self, wired):
        bus, tagger = wired(video_agg=None, song_info=_song())
        # _VideoRepo(None).get_by_url → None
        _fire(bus, "C:/x/노래.mp3")
        assert tagger.calls == []

    def test_설정을_끄면_돌지_않는다(self, wired, monkeypatch):
        bus, tagger = wired(song_info=_song())
        from config import settings as cfg
        monkeypatch.setattr(cfg, "WRITE_SONG_TAGS", False, raising=False)
        _fire(bus, "C:/x/노래.mp3")
        assert tagger.calls == []

    def test_태깅이_터져도_예외가_밖으로_나가지_않는다(self, wired):
        """이벤트 버스 위에서 터지면 다운로드 완료 처리 전체가 흔들린다."""
        bus, tagger = wired(song_info=_song())

        def boom(*_a, **_k):
            raise RuntimeError("디스크 오류")

        tagger.write_tags = boom
        _fire(bus, "C:/x/노래.mp3")  # 예외가 나면 이 줄에서 테스트가 실패한다
