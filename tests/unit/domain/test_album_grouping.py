"""앨범 그루핑·수록곡 매칭 규칙을 고정한다(I/O 없음).

이 규칙이 흔들리면 화면 결과가 통째로 바뀐다 — 같은 앨범이 둘로 갈라지거나,
가지고 있는 곡을 '없음'으로 표시하거나, 짧은 곡명이 아무 영상에나 붙는다.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from uuid import uuid4

from domain.song.album import (
    NO_ALBUM_TITLE,
    SongRef,
    earliest_registered,
    group_songs_into_albums,
    make_album_key,
    match_track_to_songs,
    normalize_name,
    pick_official_audio,
    primary_artist,
)


def _song(title="곡", artist="가수", album="앨범", video_title=None, created_at=None):
    return SongRef(
        video_id=uuid4(),
        video_title=video_title if video_title is not None else title,
        song_title=title,
        artist=artist,
        album=album,
        created_at=created_at,
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


class TestEarliestRegistered:
    """앨범 식별의 기준(앵커) — 가장 먼저 등록한 곡을 고른다."""

    def test_등록_시각이_가장_이른_곡을_고른다(self):
        base = datetime(2026, 1, 1)
        first = _song("Palette", created_at=base)
        second = _song("밤편지", created_at=base + timedelta(days=1))
        third = _song("이런 엔딩", created_at=base + timedelta(days=2))

        assert earliest_registered([third, first, second]) is first

    def test_등록_시각이_없으면_첫_항목으로_폴백한다(self):
        a = _song("A")
        b = _song("B")

        assert earliest_registered([a, b]) is a

    def test_빈_목록은_None이다(self):
        assert earliest_registered([]) is None


class TestPickOfficialAudio:
    """자동 채우기 후보 검증 — 커버·리액션·동명이곡을 걸러 낸다.

    실제 신고: 앨범 보기에서 '자신의 음원이 아닌' 영상이 수록곡에 붙는 사고가 있었다.
    """

    def _entry(self, title, channel="", duration_sec=None, url="https://x/v"):
        return {"url": url, "title": title, "channel_name": channel,
                "duration_sec": duration_sec}

    def test_동명이곡은_배제한다(self):
        """찾던 곡과 다른 제목이면 그 후보는 절대 붙지 않는다."""
        candidates = [self._entry("IU - 밤편지 (Official Audio)", duration_sec=254)]

        assert pick_official_audio(candidates, title="이런 엔딩", artist="IU") is None

    def test_제목이_일치하면_붙인다(self):
        candidates = [self._entry("IU - 밤편지 (Official Audio)", duration_sec=254)]

        picked = pick_official_audio(candidates, title="밤편지", artist="IU")

        assert picked is not None and picked["url"] == "https://x/v"

    def test_커버_영상은_배제한다(self):
        candidates = [self._entry("밤편지 Cover by 누군가", duration_sec=254)]

        assert pick_official_audio(candidates, title="밤편지", artist="IU") is None

    def test_리액션_영상은_배제한다(self):
        candidates = [self._entry("IU 밤편지 리액션", duration_sec=254)]

        assert pick_official_audio(candidates, title="밤편지", artist="IU") is None

    def test_대상_제목_자체에_있는_표기는_배제하지_않는다(self):
        """정식 발매곡이 '(Remix)'라면 후보도 당연히 그 표기를 담고 있어야 한다."""
        candidates = [self._entry("Song (Remix) - Official Audio")]

        assert pick_official_audio(candidates, title="Song (Remix)") is not None

    def test_길이가_많이_다르면_배제한다(self):
        """1시간 루프·컴필레이션처럼 다른 버전일 가능성이 높은 후보를 거른다."""
        candidates = [self._entry("IU 밤편지 1 Hour Loop", duration_sec=3600)]

        assert pick_official_audio(candidates, title="밤편지", artist="IU",
                                   expected_duration_sec=254) is None

    def test_길이_정보가_없으면_판정하지_않는다(self):
        """모르는 정보로 거르면 정상 후보까지 놓친다."""
        candidates = [self._entry("IU - 밤편지 (Official Audio)")]

        picked = pick_official_audio(candidates, title="밤편지", artist="IU",
                                     expected_duration_sec=254)

        assert picked is not None

    def test_Topic_채널을_우선한다(self):
        """'- Topic'은 YouTube가 자동 생성하는 공식 음원 채널이다."""
        candidates = [
            self._entry("밤편지 - Cover", channel="누군가", url="https://x/cover"),
            self._entry("IU - 밤편지", channel="IU - Topic", url="https://x/topic"),
        ]

        picked = pick_official_audio(candidates, title="밤편지", artist="IU")

        assert picked["url"] == "https://x/topic"

    def test_가수_이름이_보이는_후보를_우선한다(self):
        candidates = [
            self._entry("밤편지 (Official Audio)", channel="음악채널", url="https://x/a"),
            self._entry("IU 밤편지 (Official Audio)", channel="1theK", url="https://x/b"),
        ]

        picked = pick_official_audio(candidates, title="밤편지", artist="IU")

        assert picked["url"] == "https://x/b"

    def test_가수가_다른_동명이곡은_배제한다(self):
        """실측 사고: Mr.Children 'HOME'의 수록곡에 남의 곡이 붙었다.

        "Wake Me Up!"에 Avicii, "Piano Man"에 Billy Joel, "Houkiboshi"에 규현.
        셋 다 제목만 같고 가수가 다르다 — 가수가 점수 가산 요소일 뿐이라 아무도
        막지 못했다. 이제 가수 근거가 없으면 통과시키지 않는다.
        """
        candidates = [
            self._entry("Avicii - Wake Me Up (Official Video)", channel="Avicii",
                        duration_sec=273),
            self._entry("Aloe Blacc - Wake Me Up (Official)", channel="Aloe Blacc",
                        duration_sec=268),
        ]

        assert pick_official_audio(candidates, title="Wake Me Up!",
                                   artist="Mr.Children") is None

    def test_가수를_모르면_거르지_않는다(self):
        """모르는 정보로 거르면 정상 후보까지 놓친다(길이 판정과 같은 원칙)."""
        candidates = [self._entry("Avicii - Wake Me Up (Official Video)")]

        assert pick_official_audio(candidates, title="Wake Me Up") is not None

    def test_채널_핸들이_붙여쓰기여도_그_가수로_인정한다(self):
        """YouTube 채널 핸들은 띄어쓰기를 지운 표기가 흔하다("ImagineDragons").

        낱말 경계만 보면 정작 그 가수의 **공식 채널**을 남의 채널로 판정해,
        진짜 음원이 '없음'으로 남는다.
        """
        candidates = [
            self._entry("Enemy (from the series Arcane League of Legends)",
                        channel="ImagineDragons", duration_sec=174, url="https://x/official"),
        ]

        picked = pick_official_audio(candidates, title="Enemy", artist="Imagine Dragons",
                                     expected_duration_sec=173)

        assert picked is not None and picked["url"] == "https://x/official"

    def test_짧은_활동명은_다른_단어_속에_걸리지_않는다(self):
        """ASCII 이름을 부분문자열로 찾으면 "IU"가 "studious"에 걸린다."""
        candidates = [self._entry("밤편지 studious session", channel="누군가")]

        assert pick_official_audio(candidates, title="밤편지", artist="IU") is None

    def test_한글_가수명은_붙여쓴_표기도_인정한다(self):
        """한국어·일본어는 조사가 붙어 띄어쓰기 없이 이어지는 표기가 흔하다."""
        candidates = [self._entry("아이유의밤편지", channel="음악채널")]

        picked = pick_official_audio(candidates, title="밤편지", artist="아이유")

        assert picked is not None

    def test_공식_채널_후보를_제목에만_가수가_있는_후보보다_우선한다(self):
        """제목에 가수를 적어 둔 팬 편집본보다 그 가수의 채널이 훨씬 믿을 만하다."""
        candidates = [
            self._entry("Imagine Dragons - Enemy (without rap) Original Version",
                        channel="shhro", duration_sec=174, url="https://x/fan"),
            self._entry("Enemy (from the series Arcane League of Legends)",
                        channel="ImagineDragons", duration_sec=174, url="https://x/official"),
        ]

        picked = pick_official_audio(candidates, title="Enemy", artist="Imagine Dragons",
                                     expected_duration_sec=173)

        assert picked["url"] == "https://x/official"

    def test_길이가_더_가까운_후보를_우선한다(self):
        candidates = [
            self._entry("IU 밤편지", duration_sec=180, url="https://x/far"),
            self._entry("IU 밤편지", duration_sec=253, url="https://x/close"),
        ]

        picked = pick_official_audio(candidates, title="밤편지", artist="IU",
                                     expected_duration_sec=254)

        assert picked["url"] == "https://x/close"

    def test_모두_배제되면_None이다(self):
        candidates = [self._entry("전혀 다른 곡")]

        assert pick_official_audio(candidates, title="밤편지", artist="IU") is None

    def test_url이_없는_후보는_무시한다(self):
        candidates = [{"title": "밤편지", "channel_name": "", "duration_sec": None, "url": ""}]

        assert pick_official_audio(candidates, title="밤편지") is None

    def test_빈_제목은_바로_None이다(self):
        assert pick_official_audio([self._entry("아무거나")], title="") is None

    def test_빈_후보_목록은_None이다(self):
        assert pick_official_audio([], title="밤편지") is None

    def test_외부_제목의_꼬리표가_붙어도_찾는다(self):
        """iTunes 수록곡 제목에는 괄호 밖 꼬리표가 붙는다 —
        "Enemy (with JID) - from the series Arcane…". 전체 문자열로만 견주면 실제
        공식 영상조차 일치하지 않아 영영 '없음'으로 남는다(실측)."""
        target = "Enemy (with JID) - from the series Arcane League of Legends"
        candidates = [self._entry("Imagine Dragons, JID - Enemy (from the series Arcane)",
                                  channel="Imagine Dragons", duration_sec=173)]

        assert pick_official_audio(candidates, title=target,
                                   artist="Imagine Dragons") is not None

    def test_배제_키워드는_단어_단위로_본다(self):
        """부분문자열로 찾으면 "Amrit"의 `mr`, "Alive"의 `live`처럼 멀쩡한 제목이
        걸려 정답 후보가 조용히 버려진다(실측)."""
        amrit = [self._entry("Bones (Official Audio) | Amrit Records", duration_sec=174,
                             channel="ImagineDragons")]
        assert pick_official_audio(amrit, title="Bones", artist="Imagine Dragons") is not None

        alive = [self._entry("Stayin' Alive (Official Audio)", channel="Bee Gees - Topic")]
        assert pick_official_audio(alive, title="Stayin' Alive", artist="Bee Gees") is not None

    def test_단어_단위여도_진짜_라이브는_배제한다(self):
        candidates = [self._entry("Bones - Live at Wembley", duration_sec=180,
                                  channel="ImagineDragons")]

        assert pick_official_audio(candidates, title="Bones", artist="Imagine Dragons") is None

    def test_한글_키워드는_붙여_써도_잡는다(self):
        """한글은 띄어쓰기 없이 붙는 일이 흔하다("영상리액션") — 경계로 찾으면 놓친다."""
        candidates = [self._entry("IU - 밤편지 영상리액션", duration_sec=254)]

        assert pick_official_audio(candidates, title="밤편지", artist="IU") is None
