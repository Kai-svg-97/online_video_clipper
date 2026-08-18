"""앨범 정보 제공자 — 자켓·발매일·장르·수록곡 목록.

``domain.song.ports.IAlbumMetadataProvider``를 구조적으로 만족한다. 가사 제공자와 같은
규칙을 따른다: **실패는 예외가 아니라 None**, 네트워크 오류는 트레이스백 없이 WARNING,
반드시 QThread 등 백그라운드에서만 호출.

iTunes Search API를 쓰는 이유는 **키가 필요 없고**(이 앱은 배포자 OAuth 하나 말고는
자격증명을 요구하지 않는다) 한 번의 조회로 자켓·발매일·장르·수록곡 전체를 얻기
때문이다. 국내곡 커버리지가 완벽하지는 않으므로 실패는 정상 경로로 취급하고,
호출부(application)가 라이브러리 정보만으로 앨범을 구성하는 폴백을 갖는다.
"""

from __future__ import annotations

import logging

import requests

from domain.song.album import normalize_name, primary_artist
from domain.song.ports import AlbumMetadata, AlbumTrackInfo

logger = logging.getLogger(__name__)

_SEARCH_URL = "https://itunes.apple.com/search"
_LOOKUP_URL = "https://itunes.apple.com/lookup"
# (connect, read) 초 — 앨범 화면을 여는 도중의 조회라 오래 붙들지 않는다.
_TIMEOUT = (5, 8)
# 자켓은 100x100이 기본으로 오므로 파일명만 바꿔 큰 이미지를 받는다(공식 관례).
_ART_SMALL = "100x100bb"
_ART_LARGE = "600x600bb"


def _log_error(what: str, exc: Exception) -> None:
    if isinstance(exc, requests.exceptions.RequestException):
        logger.warning("iTunes %s 실패(네트워크) — 건너뜀: %s", what, exc.__class__.__name__)
    else:
        logger.exception("iTunes %s 실패", what)


def upgrade_artwork_url(url: str) -> str:
    """자켓 URL을 큰 해상도로 바꾼다(패턴이 다르면 원본 그대로)."""
    return url.replace(_ART_SMALL, _ART_LARGE) if url else ""


class ITunesAlbumProvider:
    """iTunes Search API 기반 앨범 정보 제공자(무키)."""

    key = "itunes"
    name = "iTunes"

    def __init__(self, session: "requests.Session | None" = None, country: str = "KR") -> None:
        # 세션 주입은 테스트용 — 실제 네트워크 없이 왕복을 검증한다.
        self._session = session or requests.Session()
        self._country = country

    # ── 공개 API ────────────────────────────────────────────────────────
    def fetch_album(self, artist: str, album: str) -> AlbumMetadata | None:
        """(가수, 앨범) → 앨범 정보. 못 찾으면 None."""
        if not album:
            return None
        term = f"{primary_artist(artist)} {album}".strip()
        collection = self._best_collection(term, album, artist)
        if collection is None:
            return None
        return self._with_tracks(collection)

    def find_album_of_track(self, artist: str, title: str) -> AlbumMetadata | None:
        """곡만 알 때 그 곡이 실린 앨범을 찾는다(노래 탭 앨범 값이 빈 영상용)."""
        if not title:
            return None
        term = f"{primary_artist(artist)} {title}".strip()
        payload = self._get(
            _SEARCH_URL,
            {"term": term, "entity": "song", "limit": 10, "country": self._country},
        )
        if not payload:
            return None
        target = normalize_name(title)
        artist_norm = normalize_name(primary_artist(artist)) if artist else ""
        best = None
        for item in payload.get("results", []):
            if not item.get("collectionId"):
                continue
            if normalize_name(item.get("trackName", "")) != target:
                continue
            if artist_norm and normalize_name(
                primary_artist(item.get("artistName", ""))
            ) != artist_norm:
                # 가수가 다르면 같은 제목의 다른 곡이다 — 차선책으로만 둔다.
                best = best or item
                continue
            best = item
            break
        if best is None:
            return None
        return self._lookup_collection(int(best["collectionId"]))

    # ── 내부 ───────────────────────────────────────────────────────────
    def _get(self, url: str, params: dict) -> dict | None:
        try:
            resp = self._session.get(url, params=params, timeout=_TIMEOUT)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:   # noqa: BLE001 — 실패는 정상 경로(None 반환)
            _log_error("조회", exc)
            return None

    def _best_collection(self, term: str, album: str, artist: str) -> dict | None:
        """앨범 검색 결과 중 이름이 가장 잘 맞는 것을 고른다."""
        payload = self._get(
            _SEARCH_URL,
            {"term": term, "entity": "album", "limit": 10, "country": self._country},
        )
        if not payload:
            return None
        album_norm = normalize_name(album)
        artist_norm = normalize_name(primary_artist(artist)) if artist else ""
        fallback = None
        for item in payload.get("results", []):
            name_norm = normalize_name(item.get("collectionName", ""))
            if not name_norm:
                continue
            same_artist = (
                not artist_norm
                or normalize_name(primary_artist(item.get("artistName", ""))) == artist_norm
            )
            if name_norm == album_norm and same_artist:
                return item
            if fallback is None and (album_norm in name_norm or name_norm in album_norm):
                fallback = item
        return fallback

    def _lookup_collection(self, collection_id: int) -> AlbumMetadata | None:
        # **country를 보내지 않는다.** 실측 결과 `lookup`에 country=KR을 붙이면 수록곡이
        # 통째로 빠지고 앨범(collection) 한 건만 돌아온다(같은 앨범도 country를 빼면 14곡이
        # 모두 온다). 수록곡이 없으면 "가진 곡 1개짜리 앨범"으로 조용히 잘못 보이므로
        # 여기서는 스토어를 지정하지 않는다. limit은 수록곡이 많은 앨범 대비 상한.
        payload = self._get(
            _LOOKUP_URL, {"id": collection_id, "entity": "song", "limit": 200}
        )
        if not payload:
            return None
        results = payload.get("results", [])
        collection = next(
            (r for r in results if r.get("wrapperType") == "collection"), None
        )
        if collection is None:
            return None
        return self._to_metadata(collection, results)

    def _with_tracks(self, collection: dict) -> AlbumMetadata | None:
        collection_id = collection.get("collectionId")
        if not collection_id:
            return None
        detailed = self._lookup_collection(int(collection_id))
        # 수록곡 조회가 실패해도 자켓·발매일은 이미 손에 있다 — 앨범 카드는 띄울 수 있게
        # 메타데이터만이라도 돌려준다.
        return detailed or self._to_metadata(collection, [])

    def _to_metadata(self, collection: dict, results: list[dict]) -> AlbumMetadata:
        tracks = [
            AlbumTrackInfo(
                track_no=int(r.get("trackNumber") or 0),
                title=r.get("trackName", ""),
                artist=r.get("artistName", ""),
                duration_sec=(
                    int(r["trackTimeMillis"] // 1000) if r.get("trackTimeMillis") else None
                ),
                # 2장짜리 앨범은 디스크마다 1번부터 다시 매겨진다 — 이 값을 빼면
                # 서로 다른 곡이 같은 번호로 겹쳐 한 곡으로 뭉개진다.
                disc_no=int(r.get("discNumber") or 1),
            )
            for r in results
            if r.get("wrapperType") == "track" and r.get("trackName")
        ]
        tracks.sort(key=lambda t: (t.disc_no or 1, t.track_no or 10_000))
        return AlbumMetadata(
            album_title=collection.get("collectionName", ""),
            artist=collection.get("artistName", ""),
            artwork_url=upgrade_artwork_url(collection.get("artworkUrl100", "")),
            release_date=str(collection.get("releaseDate", "") or "")[:10],
            genre=collection.get("primaryGenreName", "") or "",
            copyright=collection.get("copyright", "") or "",
            track_count=int(collection.get("trackCount") or len(tracks)),
            tracks=tracks,
            source_name=self.name,
            source_url=collection.get("collectionViewUrl", "") or "",
        )


def build_default_album_provider() -> ITunesAlbumProvider:
    """composition root가 주입할 기본 제공자."""
    return ITunesAlbumProvider()
