"""가사·메타데이터 조회 제공자들.

각 제공자는 ``domain.song.ports.ILyricsProvider``를 구조적으로 만족한다
(``key`` 속성 + ``fetch(artist, title, duration)`` → ``LyricsResult | None``).
모든 네트워크 실패·파싱 실패는 격리해 None을 반환한다(예외를 던지지 않는다).
반드시 QThread 등 백그라운드에서만 호출한다.

신뢰도: LRCLIB(무키 공개 API)가 가장 안정적이며 기본 1순위다. Genius·멜론·벅스·지니는
페이지 스크래핑이라 사이트 구조 변경에 취약하다 — 그래서 관리형 레지스트리로
켜고/끄고 순서를 조정할 수 있게 설계했고, 실패 시 다음 출처로 이어진다.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import quote

import requests

from domain.song.ports import DEFAULT_LYRICS_SEARCH_LIMIT, LyricsResult
from infrastructure.song.lrc import parse_lrc

logger = logging.getLogger(__name__)

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
# (connect, read) 초 — 접근이 느린/막힌 출처에서 빨리 다음 출처로 넘어가도록 짧게 잡는다.
_TIMEOUT = (5, 8)


def _log_provider_error(name: str, exc: Exception) -> None:
    """제공자 조회 실패 로깅 — 네트워크 오류(타임아웃·연결 실패)는 예상 가능한
    일시적 상황이므로 트레이스백 없이 WARNING으로 간단히 남기고, 그 외 예기치 못한
    오류만 전체 트레이스백(exception)으로 남긴다.
    """
    if isinstance(exc, requests.exceptions.RequestException):
        logger.warning("%s 가사 조회 실패(네트워크) — 건너뜀: %s", name, exc.__class__.__name__)
    else:
        logger.exception("%s 가사 조회 실패", name)


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": _UA, "Accept-Language": "ko,en;q=0.9"})
    return s


def _dedupe_key(result: LyricsResult) -> tuple:
    """같은 곡이 두 번 실리는 것을 막는 키 — 가수·제목·가사 첫 줄.

    출처 안에서 정확 조회 결과와 검색 결과가 겹치거나, 가수 포함/제외 검색이 같은 곡을
    돌려주는 일이 흔하다. 앨범은 재발매판마다 달라 키에 넣지 않는다.
    """
    first = next((ln.strip() for ln in result.lines if ln.strip()), "")
    return (result.artist.strip().lower(), result.title.strip().lower(), first)


def _sort_by_duration_match(
    results: list[LyricsResult], duration_sec: int | None
) -> list[LyricsResult]:
    """영상 길이에 가까운 곡을 앞으로 올린다(인기 지표가 없는 출처의 차선책).

    길이를 모르는 후보는 뒤로 보내되 버리지는 않는다. 파이썬 정렬은 안정적이라
    길이 차가 같은 후보끼리는 출처가 준 원래 순서(= 그 사이트의 관련도 랭킹)를 지킨다.
    """
    if not duration_sec:
        return results
    unknown = 10 ** 6   # 길이 미상은 항상 뒤로
    return sorted(
        results,
        key=lambda r: abs(r.duration_sec - duration_sec) if r.duration_sec else unknown,
    )


def _split_lines(text: str) -> list[str]:
    """가사 원문을 줄 목록으로 정규화한다(앞뒤 빈 줄 제거, 내부 빈 줄은 단락 구분 유지)."""
    lines = [ln.rstrip() for ln in (text or "").replace("\r\n", "\n").split("\n")]
    # 앞뒤 빈 줄 트리밍
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return lines


class LrclibProvider:
    """LRCLIB(https://lrclib.net) — 무키 공개 API, 싱크/일반 가사 제공. 가장 안정적."""

    key = "lrclib"

    def fetch(self, artist: str, title: str, duration_sec: int | None = None) -> LyricsResult | None:
        # search가 이미 '정확 조회 → 가수+제목 검색 → 제목만 검색' 순서를 밟으므로 그대로
        # 재사용한다. 따로 구현하면 두 경로의 폴백 범위가 어긋나, 후보 목록엔 뜨는 곡을
        # 체인 검색(등록 시 자동 보강 등)은 못 찾는 일이 생긴다.
        results = self.search(artist, title, duration_sec, limit=1)
        return results[0] if results else None

    def search(
        self, artist: str, title: str, duration_sec: int | None = None,
        limit: int = DEFAULT_LYRICS_SEARCH_LIMIT,
    ) -> list[LyricsResult]:
        """제목이 같은 여러 곡을 나열한다(같은 제목·다른 가수 구분용).

        정확 조회 결과가 있으면 맨 앞에 두고, 그 뒤에 검색 결과를 잇는다. 가수를 지정한
        검색만으로는 '다른 가수의 같은 제목' 곡이 안 나오므로 **제목만으로 한 번 더**
        검색해 이어 붙인다(중복은 `_dedupe_key`로 제거).

        LRCLIB은 조회수 같은 인기 지표를 주지 않는다. 대신 곡 길이를 주므로,
        **영상 길이와 가까운 순**으로 정렬해 같은 녹음일 가능성이 높은 후보를 위로
        올린다. 자르기는 정렬 **뒤에** 한다 — 먼저 자르면 뒤쪽에 있던 정답이 날아간다.
        (목록 API라 후보를 다 모아도 추가 요청이 없어 이 순서가 공짜다.)
        """
        if not title:
            return []
        sess = _session()
        out: list[LyricsResult] = []
        seen: set[tuple] = set()

        def _add(entry: dict) -> None:
            result = self._to_result(entry)
            if result is None:
                return
            key = _dedupe_key(result)
            if key in seen:
                return
            seen.add(key)
            out.append(result)

        try:
            exact = self._exact(sess, artist, title, duration_sec)
            if exact:
                _add(exact)
            for entry in self._search_raw(sess, artist, title):
                _add(entry)
            # 가수를 함께 넣어 검색했다면, 제목만으로 한 번 더 훑어 다른 가수 곡도 모은다.
            if artist:
                for entry in self._search_raw(sess, "", title):
                    _add(entry)
        except Exception as exc:
            _log_provider_error("LRCLIB", exc)

        out = _sort_by_duration_match(out, duration_sec)
        return out[:limit] if limit > 0 else out

    @staticmethod
    def _exact(sess, artist: str, title: str, duration_sec: int | None) -> dict | None:
        params = {"artist_name": artist or "", "track_name": title}
        if duration_sec:
            params["duration"] = int(duration_sec)
        resp = sess.get("https://lrclib.net/api/get", params=params, timeout=_TIMEOUT)
        if resp.status_code != 200:
            return None
        data = resp.json()
        if not data or not (data.get("plainLyrics") or data.get("syncedLyrics")):
            return None
        return data

    @staticmethod
    def _search_raw(sess, artist: str, title: str) -> list[dict]:
        """LRCLIB 검색 결과 중 가사가 실린 항목만 순서대로 돌려준다."""
        params = {"track_name": title}
        if artist:
            params["artist_name"] = artist
        resp = sess.get("https://lrclib.net/api/search", params=params, timeout=_TIMEOUT)
        if resp.status_code != 200:
            return []
        return [
            cand
            for cand in (resp.json() or [])
            if cand.get("plainLyrics") or cand.get("syncedLyrics")
        ]

    @staticmethod
    def _to_result(data: dict) -> LyricsResult | None:
        # 싱크 가사(syncedLyrics)가 있으면 우선 채택한다 — 텍스트 내용은 plainLyrics와
        # 같고 줄별 시각까지 얻을 수 있어, 자막·싱크 기능의 유일한 타이밍 출처다.
        lines: list[str] = []
        timings: list[int | None] = []
        synced = data.get("syncedLyrics") or ""
        if synced:
            parsed = parse_lrc(synced)
            if any(ms is not None for ms, _ in parsed):
                # 맨 뒤에 몰린 '타임스탬프 없는 빈 줄'은 표시상 의미가 없어 잘라낸다.
                while parsed and parsed[-1][0] is None and not parsed[-1][1].strip():
                    parsed.pop()
                lines = [text for _, text in parsed]
                timings = [ms for ms, _ in parsed]
            else:
                logger.debug("LRCLIB syncedLyrics에 타임스탬프가 없음 — plain으로 폴백")
        if not lines:
            lines = _split_lines(data.get("plainLyrics") or "")
            timings = []
        if not lines:
            return None
        raw_duration = data.get("duration")
        return LyricsResult(
            lines=lines,
            timings=timings,
            language="",
            source_name="LRCLIB",
            source_url="https://lrclib.net",
            artist=data.get("artistName") or "",
            album=data.get("albumName") or "",
            title=data.get("trackName") or "",
            duration_sec=int(raw_duration) if raw_duration else None,
        )


class GeniusProvider:
    """Genius(https://genius.com) — 검색 API + 가사 페이지 스크래핑(best-effort)."""

    key = "genius"

    def fetch(self, artist: str, title: str, duration_sec: int | None = None) -> LyricsResult | None:
        results = self.search(artist, title, duration_sec, limit=1)
        return results[0] if results else None

    def search(
        self, artist: str, title: str, duration_sec: int | None = None,
        limit: int = DEFAULT_LYRICS_SEARCH_LIMIT,
    ) -> list[LyricsResult]:
        """검색 히트를 **조회수 내림차순**으로 훑어 가사 페이지를 긁는다(곡마다 요청 1회).

        Genius 검색 응답은 곡마다 ``stats.pageviews``(페이지 조회수)를 준다 — 이 출처에서
        얻을 수 있는 유일한 인기 지표라 이것으로 정렬한다. **정렬을 페이지 요청 전에**
        해야 하는 이유는 ``limit``이 곧 요청 수이기 때문이다: 나중에 정렬하면 인기 곡이
        상한 밖으로 밀려 아예 조회되지 않는다.
        """
        if not title:
            return []
        sess = _session()
        out: list[LyricsResult] = []
        seen: set[tuple] = set()
        try:
            q = f"{artist} {title}".strip()
            resp = sess.get(
                "https://genius.com/api/search/multi",
                params={"q": q},
                timeout=_TIMEOUT,
            )
            if resp.status_code != 200:
                return []
            hits = self._song_hits(resp.json())
        except Exception as exc:
            _log_provider_error("Genius", exc)
            return []

        for song_url, pageviews in hits:
            if 0 < limit <= len(out):
                break
            try:
                page = sess.get(song_url, timeout=_TIMEOUT)
                if page.status_code != 200:
                    continue
                lines, r_artist, r_title = self._parse_page(page.text)
            except Exception as exc:
                # 곡 하나가 실패해도 나머지 후보는 계속 모은다.
                _log_provider_error("Genius", exc)
                continue
            if not lines:
                continue
            result = LyricsResult(
                lines=lines,
                language="",
                source_name="Genius",
                source_url=song_url,
                artist=r_artist,
                title=r_title,
                popularity=pageviews,
            )
            key = _dedupe_key(result)
            if key in seen:
                continue
            seen.add(key)
            out.append(result)
        return out

    @staticmethod
    def _song_hits(payload: dict) -> list[tuple[str, int]]:
        """검색 응답에서 (곡 URL, 조회수)를 모아 조회수 내림차순으로 돌려준다.

        조회수가 없는 히트는 0으로 두며, 안정 정렬이라 같은 값끼리는 Genius가 준 원래
        순서(관련도)를 유지한다.
        """
        hits: list[tuple[str, int]] = []
        urls: set[str] = set()
        sections = (payload or {}).get("response", {}).get("sections", [])
        for sec in sections:
            for hit in sec.get("hits", []):
                if hit.get("type") != "song":
                    continue
                res = hit.get("result") or {}
                url = res.get("url")
                if not url or url in urls:
                    continue
                urls.add(url)
                views = (res.get("stats") or {}).get("pageviews") or 0
                hits.append((url, int(views)))
        hits.sort(key=lambda pair: pair[1], reverse=True)
        return hits

    @staticmethod
    def _parse_page(html: str) -> tuple[list[str], str, str]:
        from bs4 import BeautifulSoup  # noqa: PLC0415

        soup = BeautifulSoup(html, "html.parser")
        containers = soup.select('[data-lyrics-container="true"]')
        parts: list[str] = []
        for c in containers:
            for br in c.find_all("br"):
                br.replace_with("\n")
            parts.append(c.get_text())
        text = "\n".join(parts)
        # Genius 페이지 머리말/꼬리말 제거:
        #  - 앞: "N ContributorsTranslations…<곡명> Lyrics" 프리앰블
        #  - 앞: "[아이유 "좋은 날" 가사]" 같은 곡 제목 주석 헤더 줄
        #  - 뒤: "123Embed" 꼬리
        text = re.sub(r"^\s*\d*\s*Contributors.*?Lyrics", "", text, count=1, flags=re.S)
        text = re.sub(r"^\s*\[[^\]\n]*가사\]\s*", "", text)
        text = re.sub(r"\d*Embed\s*$", "", text)
        lines = _split_lines(text)
        artist = ""
        title = ""
        og = soup.find("meta", property="og:title")
        if og and og.get("content"):
            # "Title by Artist" 패턴
            m = re.match(r"^(.*)\s+by\s+(.*?)(?:\s*\|.*)?$", og["content"])
            if m:
                title, artist = m.group(1).strip(), m.group(2).strip()
        return lines, artist, title


def _first_id(text: str, patterns: tuple[str, ...]) -> list[str]:
    """검색 페이지 HTML에서 곡 id를 **등장 순서대로 전부** 뽑는다(중복 제거).

    예전에는 `re.search`로 첫 id 하나만 봤다 — 같은 제목의 다른 가수 곡이 검색 결과에
    나란히 있어도 항상 맨 위 한 곡만 조회됐다는 뜻이다.
    """
    ids: list[str] = []
    for pattern in patterns:
        for m in re.finditer(pattern, text):
            song_id = m.group(1)
            if song_id not in ids:
                ids.append(song_id)
        if ids:
            break   # 앞선 패턴으로 잡혔으면 폴백 패턴은 쓰지 않는다
    return ids


def _text_of(soup, *selectors: str) -> str:
    """주어진 셀렉터를 순서대로 시도해 첫 번째로 잡히는 텍스트를 돌려준다."""
    for sel in selectors:
        node = soup.select_one(sel)
        if node is not None:
            text = node.get_text(" ", strip=True)
            if text:
                return text
    return ""


class _KoreanScrapeProvider:
    """멜론/벅스/지니 등 국내 사이트 공통 베이스 — 검색 후 가사 페이지 스크래핑.

    사이트 구조가 자주 바뀌고 봇 차단이 있어 best-effort다. 실패 시 빈 결과.
    검색 결과의 곡을 **여러 건** 훑으므로 상세 페이지 요청이 곡 수만큼 발생한다.

    이 사이트들은 API가 없어 조회수 같은 인기 지표를 얻을 수 없다. 다만 **검색 결과
    페이지의 순서 자체가 그 사이트의 인기·정확도 랭킹**이므로 그 순서를 그대로 지킨다
    (재정렬하면 오히려 랭킹 정보를 버리는 셈이다). 그래서 `popularity`는 0으로 둔다 —
    호출부의 정렬은 지표가 하나라도 있을 때만 개입한다.
    """

    key = ""
    display = ""

    def fetch(self, artist: str, title: str, duration_sec: int | None = None) -> LyricsResult | None:
        results = self.search(artist, title, duration_sec, limit=1)
        return results[0] if results else None

    def search(
        self, artist: str, title: str, duration_sec: int | None = None,
        limit: int = DEFAULT_LYRICS_SEARCH_LIMIT,
    ) -> list[LyricsResult]:
        if not title:
            return []
        sess = self._make_session()
        try:
            song_ids = self._search_ids(sess, artist, title)
        except Exception as exc:
            _log_provider_error(self.display or self.key, exc)
            return []

        out: list[LyricsResult] = []
        seen: set[tuple] = set()
        for song_id in song_ids:
            if 0 < limit <= len(out):
                break
            url = self._detail_url(song_id)
            try:
                lines, r_artist, r_title = self._parse_detail(sess, url)
            except Exception as exc:
                # 곡 하나가 실패해도 나머지 후보는 계속 모은다.
                _log_provider_error(self.display or self.key, exc)
                continue
            if not lines:
                continue
            result = LyricsResult(
                lines=lines,
                language="ko",   # 국내 사이트 가사는 한국어로 가정(번역 생략)
                source_name=self.display,
                source_url=url,
                artist=r_artist,
                title=r_title,
            )
            key = _dedupe_key(result)
            if key in seen:
                continue
            seen.add(key)
            out.append(result)
        return out

    def _make_session(self):
        return _session()

    # ── 사이트별 구현 ────────────────────────────────────────────
    def _search_ids(self, sess, artist: str, title: str) -> list[str]:  # pragma: no cover
        raise NotImplementedError

    def _detail_url(self, song_id: str) -> str:  # pragma: no cover
        raise NotImplementedError

    def _parse_detail(self, sess, url: str) -> tuple[list[str], str, str]:  # pragma: no cover
        raise NotImplementedError


class MelonProvider(_KoreanScrapeProvider):
    key = "melon"
    display = "멜론"

    def _make_session(self):
        sess = _session()
        sess.headers["Referer"] = "https://www.melon.com/"
        return sess

    def _search_ids(self, sess, artist: str, title: str) -> list[str]:
        q = quote(f"{artist} {title}".strip())
        search = sess.get(
            f"https://www.melon.com/search/song/index.htm?q={q}&section=song",
            timeout=_TIMEOUT,
        )
        return _first_id(search.text, (r"goSongDetail\('(\d+)'\)", r"songId=(\d+)"))

    def _detail_url(self, song_id: str) -> str:
        return f"https://www.melon.com/song/detail.htm?songId={song_id}"

    def _parse_detail(self, sess, url: str) -> tuple[list[str], str, str]:
        from bs4 import BeautifulSoup  # noqa: PLC0415

        detail = sess.get(url, timeout=_TIMEOUT)
        soup = BeautifulSoup(detail.text, "html.parser")
        box = soup.select_one("div.lyric")
        if not box:
            return [], "", ""
        for br in box.find_all("br"):
            br.replace_with("\n")
        artist = _text_of(soup, "div.artist a.artist_name", "div.artist")
        title = _text_of(soup, "div.song_name")
        # "곡명 <제목>" 형태라 라벨을 떼어낸다.
        title = re.sub(r"^\s*곡명\s*", "", title).strip()
        return _split_lines(box.get_text()), artist, title


class BugsProvider(_KoreanScrapeProvider):
    key = "bugs"
    display = "벅스"

    def _search_ids(self, sess, artist: str, title: str) -> list[str]:
        q = quote(f"{artist} {title}".strip())
        search = sess.get(
            f"https://music.bugs.co.kr/search/track?q={q}", timeout=_TIMEOUT
        )
        return _first_id(search.text, (r"/track/(\d+)",))

    def _detail_url(self, song_id: str) -> str:
        return f"https://music.bugs.co.kr/track/{song_id}"

    def _parse_detail(self, sess, url: str) -> tuple[list[str], str, str]:
        from bs4 import BeautifulSoup  # noqa: PLC0415

        detail = sess.get(url, timeout=_TIMEOUT)
        soup = BeautifulSoup(detail.text, "html.parser")
        box = soup.select_one("div.lyricsContainer xmp") or soup.select_one("div.lyricsContainer")
        if not box:
            return [], "", ""
        artist = _text_of(soup, 'table.info a[href*="/artist/"]', "p.artist a")
        title = _text_of(soup, "header h1", "h1.trackTitle")
        return _split_lines(box.get_text()), artist, title


class GenieProvider(_KoreanScrapeProvider):
    key = "genie"
    display = "지니"

    def _search_ids(self, sess, artist: str, title: str) -> list[str]:
        q = quote(f"{artist} {title}".strip())
        search = sess.get(
            f"https://www.genie.co.kr/search/searchMain?query={q}", timeout=_TIMEOUT
        )
        return _first_id(search.text, (r"fnViewSongInfo\('(\d+)'", r"xgnm=(\d+)"))

    def _detail_url(self, song_id: str) -> str:
        return f"https://www.genie.co.kr/detail/songInfo?xgnm={song_id}"

    def _parse_detail(self, sess, url: str) -> tuple[list[str], str, str]:
        from bs4 import BeautifulSoup  # noqa: PLC0415

        detail = sess.get(url, timeout=_TIMEOUT)
        soup = BeautifulSoup(detail.text, "html.parser")
        box = soup.select_one("#pLyrics p") or soup.select_one("pre#pLyrics")
        if not box:
            return [], "", ""
        for br in box.find_all("br"):
            br.replace_with("\n")
        artist = _text_of(soup, ".info-zone .artist", ".info-zone a.artist")
        title = _text_of(soup, ".info-zone h2.name", ".info-zone .name")
        return _split_lines(box.get_text()), artist, title


def build_default_providers() -> dict[str, object]:
    """provider_key → 제공자 인스턴스 매핑(composition root에서 주입)."""
    providers = [
        LrclibProvider(),
        GeniusProvider(),
        MelonProvider(),
        BugsProvider(),
        GenieProvider(),
    ]
    return {p.key: p for p in providers}
