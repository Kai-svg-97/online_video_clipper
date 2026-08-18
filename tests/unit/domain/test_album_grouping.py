"""앨범 그루핑·수록곡 매칭 규칙을 고정한다(I/O 없음).

이 규칙이 흔들리면 화면 결과가 통째로 바뀐다 — 같은 앨범이 둘로 갈라지거나,
가지고 있는 곡을 '없음'으로 표시하거나, 짧은 곡명이 아무 영상에나 붙는다.
"""
from __future__ import annotations

from uuid import uuid4

from domain.song.album import (
    NO_ALBUM_TITLE,
    SongRef,
    group_songs_into_albums,
    make_album_key,
    match_track_to_songs,
    normalize_name,
    primary_artist,
)


def _song(title="곡", artist="가수", album="앨범", video_title=None):
    return SongRef(
        video_id=uuid4(),
        video_title=video_title if video_title is not None else title,
        song_title=title,
        artist=artist,
        album=album,
    )


class TestNormalize:
    def test_괄호_꼬리표를_걷어낸다(self):
        assert normalize_name("밤편지 (Official Audio)") == "밤편지"
        assert normalize_name("Love poem [MV]") == "love poem"

    def test_구분선_뒤_꼬리표도_걷어낸다(self):
        assert normalize_name("Palette - Single") == "palette"

    def test_제목_속_하이픈은_단어를_붙여_유지한다(self):
        # 하이픈을 통째로 자르면 "Rock-A-Bye" 같은 곡이 사라진다.
        assert normalize_name("Rock-A-Bye") == "rock a bye"

    def test_대소문자와_공백_기호를_무시한다(self):
        assert normalize_name("  LOVE   POEM!! ") == normalize_name("love poem")


class TestPrimaryArtist:
    def test_협업_표기에서_첫_아티스트를_고른다(self):
        assert primary_artist("NIKI, Phil Collins") == "NIKI"
        assert primary_artist("아이유 feat. 슈가") == "아이유"

    def test_단독_아티스트는_그대로다(self):
        assert primary_artist("IU") == "IU"


class TestAlbumKey:
    def test_표기가_달라도_같은_앨범이면_같은_키다(self):
        assert make_album_key("IU", "Love poem") == make_album_key("iu", "  LOVE POEM ")

    def test_협업_표기는_주_아티스트로_묶인다(self):
        assert make_album_key("IU, SUGA", "Love poem") == make_album_key("IU", "Love poem")

    def test_null_같은_자리표시자는_앨범명이_아니다(self):
        # 실제 DB에서 앨범 필드에 문자열 "null"이 저장된 사례를 확인했다.
        # 이걸 앨범명으로 믿으면 무관한 곡들이 'null' 앨범 하나로 뭉친다.
        for junk in ("null", "None", "N/A", "unknown", "미상"):
            assert make_album_key("IU", junk) == "", junk

    def test_앨범명이_없으면_키가_없다(self):
        # 가수만으로 묶으면 그 가수의 미상 곡이 전부 한 덩어리가 된다.
        assert make_album_key("IU", "") == ""
        assert make_album_key("IU", "   ") == ""


class TestGrouping:
    def test_같은_앨범끼리_묶고_원문_표기를_보여준다(self):
        songs = [
            _song("밤편지", "아이유", "Palette"),
            _song("팔레트", "아이유", "palette"),   # 표기만 다름
            _song("Through the Night", "IU", "Palette"),
        ]

        groups = group_songs_into_albums(songs)

        assert len(groups) == 2       # 아이유/Palette + IU/Palette (가수 표기가 다름)
        titles = {g.album_title for g in groups}
        assert "Palette" in titles    # 정규화된 "palette"가 아니라 원문 다수 표기

    def test_앨범이_없는_노래는_미상으로_모인다(self):
        songs = [_song("A", "가수", ""), _song("B", "가수", ""), _song("C", "가수", "정규앨범")]

        groups = group_songs_into_albums(songs)

        assert groups[-1].album_title == NO_ALBUM_TITLE
        assert groups[-1].is_unknown is True
        assert len(groups[-1].songs) == 2

    def test_미상_묶음은_항상_맨_뒤다(self):
        songs = [_song("A", "가수", ""), _song("B", "가수", "ZZZ 앨범")]

        groups = group_songs_into_albums(songs)

        assert groups[0].album_title == "ZZZ 앨범"
        assert groups[-1].is_unknown

    def test_빈_입력은_빈_결과다(self):
        assert group_songs_into_albums([]) == []


class TestTrackMatching:
    def test_영상_제목에_꼬리표가_붙어도_찾는다(self):
        song = SongRef(
            video_id=uuid4(),
            video_title="아이유(IU) - 밤편지 (Official Audio)",
            song_title="",
            artist="아이유",
            album="",
        )

        assert match_track_to_songs("밤편지", [song]) is song

    def test_짧은_곡명은_부분일치로_붙이지_않는다(self):
        # "Go"가 "Good Day"에 걸리면 엉뚱한 곡이 수록곡에 매핑된다.
        song = _song("Good Day", "IU", "")

        assert match_track_to_songs("Go", [song]) is None

    def test_같은_제목이면_가수로_가른다(self):
        mine = _song("Hello", "Adele", "25")
        other = _song("Hello", "다른가수", "그앨범")

        assert match_track_to_songs("Hello", [other, mine], track_artist="Adele") is mine

    def test_없는_곡은_None이다(self):
        assert match_track_to_songs("존재하지 않는 곡", [_song("밤편지")]) is None
