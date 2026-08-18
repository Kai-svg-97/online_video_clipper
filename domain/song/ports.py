"""노래 컨텍스트의 애플리케이션 레이어가 의존하는 포트(추상화).

가사 조회 제공자(``ILyricsProvider``)와 번역기(``ITranslator``)는 인프라에서
Playwright/requests/deep-translator 등으로 구현되지만, application 레이어는 여기
정의된 Protocol에만 의존한다. 구조적 타이핑으로 어댑터가 이를 만족하며, 구체
인스턴스 주입은 composition root(`main.py`)가 담당한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True, slots=True)
class LyricsResult:
    """가사 제공자 조회 결과.

    ``lines``는 가사 원문 줄 목록(빈 리스트 = 가사 없음). ``timings``는 각 줄의 시작
    시각(ms)으로 ``lines``와 같은 길이이거나, 시간 정보가 없으면 빈 리스트다
    (LRC 싱크 가사를 주는 출처에서만 채워진다). 제공자가 함께 알려주는
    메타데이터(가수·앨범·제목·발매년도)는 부족분을 채우는 데 쓰인다.
    """

    lines: list[str] = field(default_factory=list)
    timings: list[int | None] = field(default_factory=list)
    language: str = ""          # ISO 639-1 (예: "en", "ko") — 미상이면 ""
    source_name: str = ""       # 표시 이름 (예: "LRCLIB")
    source_url: str = ""
    artist: str = ""
    album: str = ""
    title: str = ""
    release_year: str = ""
    # 출처가 알려주는 인기 지표(조회수·재생수 등). 클수록 인기. 0이면 '지표 없음'이며,
    # 이때는 출처가 돌려준 순서를 그대로 존중한다(국내 사이트 검색 결과처럼 순서 자체가
    # 그 사이트의 인기·정확도 랭킹인 경우가 있다).
    popularity: int = 0
    # 곡 길이(초). 같은 제목의 다른 곡을 가려내는 데 쓴다 — 영상 길이와 가까울수록
    # 같은 녹음일 가능성이 높다. 모르면 None.
    duration_sec: int | None = None


# 출처 하나가 돌려줄 후보 수의 기본 상한. 0 이하면 무제한.
#
# 같은 제목의 다른 가수 곡이 흔하므로 1건만 받으면 엉뚱한 곡이 걸린다. 그렇다고 무제한을
# 기본값으로 두면 곡마다 상세 페이지를 한 번씩 긁는 스크래핑 출처(Genius·멜론·벅스·지니)가
# 검색 한 번에 수십 번 요청하게 되어 몇 분씩 걸린다 — 그래서 넉넉하되 유한한 값을 기본으로
# 하고, 필요하면 호출부가 늘리거나 0(무제한)으로 풀 수 있게 인자로 노출한다.
DEFAULT_LYRICS_SEARCH_LIMIT = 10


class ILyricsProvider(Protocol):
    """단일 가사·메타데이터 출처. 구현체는 infrastructure/song/lyrics_providers.py."""

    key: str            # LyricsSource.provider_key와 매칭되는 식별자

    def fetch(
        self, artist: str, title: str, duration_sec: int | None = None
    ) -> LyricsResult | None:
        """가사를 조회한다. 실패/없음이면 None을 반환(예외를 던지지 않는다)."""
        ...


class ILyricsSearchProvider(Protocol):
    """여러 후보를 돌려주는 확장 출처 — 후보 목록 검색이 쓴다.

    ``fetch``가 "가장 그럴듯한 한 곡"을 고르는 것과 달리, ``search``는 **같은 제목의
    다른 가수 곡까지** 그대로 나열한다. 구현이 없는 출처도 있을 수 있으므로 호출부는
    ``hasattr(provider, "search")``로 확인하고 없으면 ``fetch`` 1건으로 폴백한다
    (그래서 별도 Protocol로 뺐다 — ``ILyricsProvider``에 넣으면 모든 구현이 강제된다).
    """

    key: str

    def search(
        self,
        artist: str,
        title: str,
        duration_sec: int | None = None,
        limit: int = DEFAULT_LYRICS_SEARCH_LIMIT,
    ) -> list[LyricsResult]:
        """후보를 최대 ``limit``건 반환한다(0 이하면 무제한). 실패/없음이면 빈 리스트."""
        ...


class ITranslator(Protocol):
    """텍스트 번역기. 구현체는 infrastructure/song/translator.py."""

    def translate(
        self, texts: list[str], target: str = "ko", source: str = "auto"
    ) -> list[str]:
        """``texts``를 ``target`` 언어로 번역해 같은 길이의 리스트로 반환한다.

        번역 불가/실패 시 원문을 그대로 반환한다(길이 보존 — 호출부가 원문/번역을
        1:1로 짝지을 수 있게 한다).
        """
        ...

    def detect_language(self, text: str) -> str:
        """언어 코드(ISO 639-1)를 추정한다. 실패 시 ""."""
        ...


@dataclass(frozen=True, slots=True)
class AlbumTrackInfo:
    """외부 앨범 정보의 수록곡 1건."""

    track_no: int
    title: str
    artist: str = ""
    duration_sec: int | None = None


@dataclass(frozen=True, slots=True)
class AlbumMetadata:
    """외부에서 받은 앨범 정보 — 자켓·설명 재료·수록곡 목록.

    ``description``을 출처가 문장으로 주는 경우는 드물어서(iTunes는 안 준다) 비워 두고,
    표시용 문구는 application 레이어가 장르·발매일·수록곡 수·저작권으로 조립한다.
    출처가 진짜 설명을 주면 그대로 싣는다.
    """

    album_title: str
    artist: str
    artwork_url: str = ""
    release_date: str = ""      # ISO 또는 출처 원문
    genre: str = ""
    copyright: str = ""
    track_count: int = 0
    tracks: list[AlbumTrackInfo] = field(default_factory=list)
    description: str = ""
    source_name: str = ""
    source_url: str = ""


class IAlbumMetadataProvider(Protocol):
    """앨범 정보 출처(무키 iTunes 등). 구현체는 infrastructure/song/album_providers.py.

    두 방향이 모두 필요하다 — 앨범명을 아는 경우(``fetch_album``)와, 곡만 알고 어느
    앨범인지 모르는 경우(``find_album_of_track``, 노래 탭 앨범 값이 빈 영상). 실패·없음은
    예외가 아니라 None으로 알린다(네트워크 출처라 실패가 정상 경로다).
    """

    key: str

    def fetch_album(self, artist: str, album: str) -> AlbumMetadata | None: ...

    def find_album_of_track(self, artist: str, title: str) -> AlbumMetadata | None: ...
