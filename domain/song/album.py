"""앨범 그루핑 — 노래 정보에서 '앨범'이라는 묶음을 만들어 내는 순수 로직.

이 앱에 앨범이라는 저장 단위는 없다. 영상마다 붙은 노래 정보(가수·앨범·제목)를
**파생 그룹**으로 묶어 앨범처럼 보여 주는 것이므로, 묶는 규칙 자체가 기능의 전부다.
규칙을 도메인 순수 함수로 떼어 둔 이유:

* 같은 앨범인데 다르게 적힌 표기("Love Poem" vs "love poem (Deluxe)")를 한 묶음으로
  볼지 말지가 화면 결과를 통째로 바꾼다 — 네트워크·DB 없이 테스트로 고정해야 한다.
* 외부(iTunes)에서 받은 수록곡 제목을 **내 라이브러리 영상 제목**에 맞춰 붙이는 매칭도
  같은 정규화 규칙을 쓴다. 두 곳이 어긋나면 "가진 곡인데 없다고 나오는" 사고가 난다.

I/O 없음. 외부 조회·DB·GUI는 이 규칙을 **사용**할 뿐 다시 정의하지 않는다.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

# 앨범 값이 비어 있고 외부 조회로도 못 찾은 노래를 모으는 그룹 이름.
NO_ALBUM_TITLE = "앨범 미상"

# 앨범 키 구분자 — 가수/앨범 경계. 사용자 입력에 나올 수 없는 제어문자를 쓴다.
_KEY_SEP = "\x1f"

# 제목·앨범명에서 떼어낼 부가 표기. 영상 제목은 여기에 온갖 꼬리표가 붙는다
# ("(Official Audio)", "[MV]", "- Single", "(Feat. …)"). 이걸 남겨 두면 같은 곡이
# 서로 다른 앨범으로 갈라진다.
_BRACKET_RE = re.compile(r"[\(\[\{][^\)\]\}]*[\)\]\}]")
_NOISE_WORDS = (
    "official audio", "official video", "official music video", "official mv",
    "music video", "lyric video", "lyrics video", "audio", "mv", "m/v",
    "feat", "featuring", "ft", "with", "prod", "inst", "instrumental",
    "single", "ep", "album", "deluxe", "remaster", "remastered", "edition",
    "special", "repackage", "ost", "explicit", "clean", "hd", "4k", "live",
    "color coded", "가사", "한글자막", "자막", "뮤직비디오", "공식",
)
_NOISE_RE = re.compile(
    r"\b(" + "|".join(re.escape(w) for w in _NOISE_WORDS) + r")\b", re.IGNORECASE
)
_NON_WORD_RE = re.compile(r"[^0-9a-z가-힣]+")

# 아티스트 문자열은 협업 표기로 이어 붙는다("NIKI, Phil Collins"). 앨범 묶음은
# 주 아티스트 기준이어야 같은 앨범이 갈라지지 않는다(가사 체인의 _primary_artist와
# 같은 판단 — 그쪽은 조회용, 이쪽은 그룹핑용이라 규칙만 공유하고 코드는 각자 둔다).
_ARTIST_SPLIT_RE = re.compile(
    r"\s*(?:,|;|/|&|\bfeat\.?\b|\bft\.?\b|\bwith\b|\bx\b|\bvs\.?\b)\s*", re.IGNORECASE
)


def primary_artist(artist: str) -> str:
    """협업 표기에서 주(첫) 아티스트만 뽑는다. 빈 값이면 빈 문자열."""
    if not artist:
        return ""
    parts = [p.strip() for p in _ARTIST_SPLIT_RE.split(artist) if p.strip()]
    return parts[0] if parts else artist.strip()


def normalize_name(text: str) -> str:
    """비교용 정규화 — 괄호 부가표기·꼬리표·기호·공백을 걷어낸 소문자 문자열.

    비교에만 쓰고 **표시에는 절대 쓰지 않는다**(원문 표기는 그대로 보존한다).
    """
    if not text:
        return ""
    s = unicodedata.normalize("NFKC", text).lower()
    s = _BRACKET_RE.sub(" ", s)
    # 구분선 뒤 꼬리표("... - Single", "... — Official Audio")도 잡아야 하지만,
    # 제목 자체에 하이픈이 있는 곡("Rock-A-Bye")까지 자르면 안 되므로 단어 단위로만
    # 지운다(_NOISE_RE). 여기서는 구분선을 공백으로 바꿔 토큰 경계만 만든다.
    s = s.replace("—", " ").replace("–", " ").replace("-", " ")
    s = _NOISE_RE.sub(" ", s)
    s = _NON_WORD_RE.sub(" ", s)
    return " ".join(s.split())


# 자동 수집이 남긴 '값 아닌 값'. 실제 데이터에서 앨범 필드에 문자열 "null"이 그대로
# 저장된 사례를 확인했다(yt-dlp 메타데이터의 null이 문자열로 굳은 경우). 이런 값을
# 앨범명으로 믿으면 서로 무관한 곡들이 'null'이라는 앨범 하나로 묶인다.
_PLACEHOLDER_VALUES = frozenset(
    {"null", "none", "nil", "nan", "n a", "na", "undefined", "unknown", "미상", "없음"}
)


def is_placeholder(text: str) -> bool:
    """값이 실제 이름이 아니라 '비어 있음'을 뜻하는 자리표시자인지."""
    return normalize_name(text) in _PLACEHOLDER_VALUES


def make_album_key(artist: str, album: str) -> str:
    """(가수, 앨범) → 그룹 키. 표기가 달라도 같은 앨범이면 같은 키가 나온다.

    앨범명이 비면 가수만으로 키를 만들지 않는다 — 그러면 그 가수의 모든 미상 곡이
    한 앨범으로 뭉쳐 '앨범'이라 부를 수 없는 덩어리가 된다. 대신 빈 키를 돌려주고
    호출부가 '앨범 미상'으로 따로 모은다.
    """
    album_norm = normalize_name(album)
    if not album_norm or album_norm in _PLACEHOLDER_VALUES:
        return ""
    return f"{normalize_name(primary_artist(artist))}{_KEY_SEP}{album_norm}"


@dataclass(frozen=True, slots=True)
class SongRef:
    """앨범 그루핑 입력 — 영상 1건의 노래 정보(리포지토리가 채워 넘긴다)."""

    video_id: object          # UUID
    video_title: str          # 영상 제목(노래 제목이 비었을 때의 폴백)
    song_title: str = ""
    artist: str = ""
    album: str = ""
    thumbnail_path: str = ""
    duration_sec: int | None = None

    @property
    def effective_title(self) -> str:
        """수록곡 매칭에 쓸 곡 제목 — 노래 정보 우선, 없으면 영상 제목."""
        return self.song_title or self.video_title


@dataclass(slots=True)
class AlbumGroup:
    """앨범 한 묶음(파생). key가 ""이면 '앨범 미상' 묶음이다."""

    key: str
    album_title: str
    artist: str
    songs: list[SongRef] = field(default_factory=list)

    @property
    def is_unknown(self) -> bool:
        return not self.key


def group_songs_into_albums(songs: list[SongRef]) -> list[AlbumGroup]:
    """노래 목록을 앨범 묶음으로 나눈다.

    * 앨범 값이 있는 노래는 (주 아티스트, 앨범) 정규화 키로 묶는다.
    * 앨범 값이 없는 노래는 전부 '앨범 미상' 묶음 하나로 모은다(호출부가 외부 조회로
      앨범을 추정해 채우면 다음 조회부터 자연히 제 앨범으로 옮겨 간다).
    * 표시용 제목·가수는 **그 묶음에서 가장 흔한 원문 표기**를 쓴다 — 정규화 값을
      그대로 보여 주면 "love poem"처럼 대소문자가 뭉개진 이름이 화면에 나온다.
    * 정렬은 가수 → 앨범명(원문 기준, 대소문자 무시), '앨범 미상'은 항상 맨 뒤.
    """
    groups: dict[str, AlbumGroup] = {}
    unknown = AlbumGroup(key="", album_title=NO_ALBUM_TITLE, artist="")
    title_votes: dict[str, dict[str, int]] = {}
    artist_votes: dict[str, dict[str, int]] = {}

    for song in songs:
        key = make_album_key(song.artist, song.album)
        if not key:
            unknown.songs.append(song)
            continue
        group = groups.get(key)
        if group is None:
            group = AlbumGroup(key=key, album_title=song.album.strip(),
                               artist=(song.artist or "").strip())
            groups[key] = group
            title_votes[key] = {}
            artist_votes[key] = {}
        group.songs.append(song)
        if song.album.strip():
            title_votes[key][song.album.strip()] = title_votes[key].get(song.album.strip(), 0) + 1
        if (song.artist or "").strip():
            a = song.artist.strip()
            artist_votes[key][a] = artist_votes[key].get(a, 0) + 1

    for key, group in groups.items():
        if title_votes[key]:
            group.album_title = max(title_votes[key].items(), key=lambda kv: (kv[1], kv[0]))[0]
        if artist_votes[key]:
            group.artist = max(artist_votes[key].items(), key=lambda kv: (kv[1], kv[0]))[0]

    ordered = sorted(
        groups.values(), key=lambda g: (g.artist.lower(), g.album_title.lower())
    )
    if unknown.songs:
        ordered.append(unknown)
    return ordered


def match_track_to_songs(
    track_title: str, songs: list[SongRef], track_artist: str = ""
) -> SongRef | None:
    """외부 수록곡 제목에 대응하는 라이브러리 노래를 찾는다(없으면 None).

    영상 제목에는 가수명·꼬리표가 섞여 있어("아이유 - 밤편지 (Official Audio)")
    정확 일치로는 거의 안 맞는다. 그래서 정규화한 뒤 ① 완전 일치 ② 한쪽이 다른 쪽을
    포함(영상 제목 안에 곡명이 들어 있는 흔한 형태) 순으로 본다. 포함 판정은 **곡명이
    너무 짧으면 오탐**("Go"가 아무 제목에나 걸린다)이라 3글자 이상일 때만 허용한다.
    """
    target = normalize_name(track_title)
    if not target:
        return None
    artist_norm = normalize_name(primary_artist(track_artist)) if track_artist else ""

    exact: list[SongRef] = []
    partial: list[SongRef] = []
    for song in songs:
        song_norm = normalize_name(song.effective_title)
        if not song_norm:
            continue
        if song_norm == target:
            exact.append(song)
        elif len(target) >= 3 and (target in song_norm or song_norm in target):
            partial.append(song)

    for bucket in (exact, partial):
        if not bucket:
            continue
        if artist_norm and len(bucket) > 1:
            # 같은 제목의 다른 가수 곡이 섞였을 때 가수까지 맞는 쪽을 고른다.
            for song in bucket:
                if normalize_name(primary_artist(song.artist)) == artist_norm:
                    return song
        return bucket[0]
    return None
