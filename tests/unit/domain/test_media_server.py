"""미디어 서버 사이드카 생성 규칙(.nfo / .m3u).

서버가 읽는 형식이라 **틀려도 앱에서는 아무 일이 없고**, 며칠 뒤 Jellyfin 목록이
이상하다는 것만 남는다. 그래서 형식의 함정을 하나씩 못 박는다.
"""

from __future__ import annotations

import pytest

from domain.library.media_server import (
    M3uEntry,
    MediaServerEntry,
    build_m3u,
    build_nfo,
    nfo_path_for,
    normalize_date,
)


def _entry(**kw) -> MediaServerEntry:
    base = dict(title="영상 제목", file_path="C:/m/영상.mp4", url="https://youtu.be/x",
                channel_name="채널", description="설명", published_at="2024-05-01",
                duration_sec=185, tags=("태그A", "태그B"))
    base.update(kw)
    return MediaServerEntry(**base)


class TestRoot:
    def test_기본은_movie다(self):
        assert "<movie>" in build_nfo(_entry())

    def test_노래는_musicvideo다(self):
        nfo = build_nfo(_entry(is_song=True, artist="가수", album="앨범"))
        assert "<musicvideo>" in nfo and "</musicvideo>" in nfo

    def test_movie에는_감독으로_채널을_넣는다(self):
        assert "<director>채널</director>" in build_nfo(_entry())

    def test_musicvideo에는_가수와_앨범을_넣는다(self):
        nfo = build_nfo(_entry(is_song=True, artist="가수", album="앨범"))
        assert "<artist>가수</artist>" in nfo
        assert "<album>앨범</album>" in nfo

    def test_가수가_비면_채널을_쓴다(self):
        nfo = build_nfo(_entry(is_song=True, artist="", channel_name="채널"))
        assert "<artist>채널</artist>" in nfo


class TestFields:
    def test_상영시간은_분_단위다(self):
        """초를 그대로 넣으면 3분짜리가 180분이 된다."""
        assert "<runtime>3</runtime>" in build_nfo(_entry(duration_sec=185))

    def test_1분_미만도_0이_아니라_1이다(self):
        assert "<runtime>1</runtime>" in build_nfo(_entry(duration_sec=20))

    def test_길이를_모르면_적지_않는다(self):
        assert "<runtime>" not in build_nfo(_entry(duration_sec=0))

    def test_태그를_각각_적는다(self):
        nfo = build_nfo(_entry(tags=("A", "B")))
        assert nfo.count("<tag>") == 2

    def test_빈_값은_아예_적지_않는다(self):
        """빈 태그를 넣으면 서버가 '값이 있다'로 읽어 기존 정보를 지운다."""
        nfo = build_nfo(_entry(description="", channel_name=""))
        assert "<plot>" not in nfo
        assert "<studio>" not in nfo

    def test_고유_id로_주소를_넣는다(self):
        assert 'uniqueid type="youtube"' in build_nfo(_entry())

    def test_주소가_없으면_고유_id도_없다(self):
        assert "uniqueid" not in build_nfo(_entry(url=""))

    def test_노래는_곡_제목을_쓴다(self):
        """영상 제목의 '(Official MV)' 꼬리표가 음악 목록에 그대로 남으면 안 된다."""
        nfo = build_nfo(_entry(title="가수 - 곡 (Official MV)", is_song=True, song_title="곡"))
        assert "<title>곡</title>" in nfo

    def test_곡_제목이_비면_영상_제목으로_되돌아간다(self):
        nfo = build_nfo(_entry(title="영상 제목", is_song=True, song_title=""))
        assert "<title>영상 제목</title>" in nfo


class TestEscaping:
    def test_XML_특수문자를_이스케이프한다(self):
        """제목에 & 나 < 가 있으면 파일이 깨져 서버가 통째로 무시한다."""
        nfo = build_nfo(_entry(title="A & B <최고>"))
        assert "A &amp; B &lt;최고&gt;" in nfo
        assert "<최고>" not in nfo

    def test_주소의_앰퍼샌드도_이스케이프한다(self):
        nfo = build_nfo(_entry(url="https://y/watch?v=x&t=10"))
        assert "v=x&amp;t=10" in nfo


class TestDate:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("2024-05-01", "2024-05-01"),
            ("20240501", "2024-05-01"),
            ("2024-05-01T12:00:00Z", "2024-05-01"),
            ("2024-05-01T12:00:00+09:00", "2024-05-01"),
        ],
    )
    def test_여러_형태를_받는다(self, raw, expected):
        assert normalize_date(raw) == expected

    @pytest.mark.parametrize("raw", ["", "   ", "언젠가"])
    def test_알아볼_수_없으면_빈_문자열(self, raw):
        assert normalize_date(raw) == ""

    def test_연도를_함께_적는다(self):
        assert "<year>2024</year>" in build_nfo(_entry(published_at="20240501"))

    def test_업로드일이_없으면_발매년도를_쓴다(self):
        nfo = build_nfo(_entry(published_at="", is_song=True, release_year="1999"))
        assert "<year>1999</year>" in nfo


class TestNfoPath:
    @pytest.mark.parametrize(
        "media,expected",
        [
            ("C:/m/영상.mp4", "C:/m/영상.nfo"),
            ("C:/m/영상.여러.점.mkv", "C:/m/영상.여러.점.nfo"),
            (r"C:\m\영상.mp4", r"C:\m\영상.nfo"),
        ],
    )
    def test_확장자만_바꾼다(self, media, expected):
        assert nfo_path_for(media) == expected

    def test_확장자가_없으면_덧붙인다(self):
        assert nfo_path_for("C:/m/영상") == "C:/m/영상.nfo"

    def test_폴더_이름의_점을_확장자로_보지_않는다(self):
        """`C:/my.videos/영상` 처럼 폴더에 점이 있어도 잘라내면 안 된다."""
        assert nfo_path_for("C:/my.videos/영상") == "C:/my.videos/영상.nfo"


class TestM3u:
    def test_헤더로_시작한다(self):
        assert build_m3u([]).startswith("#EXTM3U")

    def test_항목마다_길이와_제목을_적는다(self):
        text = build_m3u([M3uEntry("C:/m/a.mp4", "첫 영상", 120)])
        assert "#EXTINF:120,첫 영상" in text
        assert "C:/m/a.mp4" in text

    def test_길이를_모르면_마이너스1이다(self):
        """0을 넣으면 플레이어가 곧바로 다음 곡으로 넘어간다."""
        assert "#EXTINF:-1," in build_m3u([M3uEntry("C:/m/a.mp4", "제목", 0)])

    def test_제목의_줄바꿈을_없앤다(self):
        """줄바꿈이 남으면 그 다음 줄이 경로로 읽혀 목록이 깨진다."""
        text = build_m3u([M3uEntry("C:/m/a.mp4", "앞\n뒤", 10)])
        assert "#EXTINF:10,앞 뒤" in text

    def test_순서를_지킨다(self):
        text = build_m3u([M3uEntry("a.mp4", "A"), M3uEntry("b.mp4", "B")])
        assert text.index("a.mp4") < text.index("b.mp4")

    def test_끝에_줄바꿈이_있다(self):
        assert build_m3u([M3uEntry("a.mp4")]).endswith("\n")
