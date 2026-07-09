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

from domain.song.ports import LyricsResult

logger = logging.getLogger(__name__)

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
_TIMEOUT = 12
_LRC_TS_RE = re.compile(r"^\s*(?:\[\d{1,2}:\d{2}(?:\.\d{1,3})?\]\s*)+")


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": _UA, "Accept-Language": "ko,en;q=0.9"})
    return s


def _split_lines(text: str) -> list[str]:
    """가사 원문을 줄 목록으로 정규화한다(앞뒤 빈 줄 제거, 내부 빈 줄은 단락 구분 유지)."""
    lines = [ln.rstrip() for ln in (text or "").replace("\r\n", "\n").split("\n")]
    # 앞뒤 빈 줄 트리밍
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return lines


def _strip_lrc_timestamps(text: str) -> str:
    return "\n".join(_LRC_TS_RE.sub("", ln) for ln in text.splitlines())


class LrclibProvider:
    """LRCLIB(https://lrclib.net) — 무키 공개 API, 싱크/일반 가사 제공. 가장 안정적."""

    key = "lrclib"

    def fetch(self, artist: str, title: str, duration_sec: int | None = None) -> LyricsResult | None:
        if not title:
            return None
        sess = _session()
        try:
            # 1) 정확 조회
            params = {"artist_name": artist or "", "track_name": title}
            if duration_sec:
                params["duration"] = int(duration_sec)
            resp = sess.get("https://lrclib.net/api/get", params=params, timeout=_TIMEOUT)
            data = resp.json() if resp.status_code == 200 else None
            # 2) 실패 시 검색 후 첫 후보
            if not data or not (data.get("plainLyrics") or data.get("syncedLyrics")):
                q = f"{artist} {title}".strip()
                sresp = sess.get(
                    "https://lrclib.net/api/search", params={"q": q}, timeout=_TIMEOUT
                )
                if sresp.status_code == 200:
                    for cand in sresp.json() or []:
                        if cand.get("plainLyrics") or cand.get("syncedLyrics"):
                            data = cand
                            break
        except Exception:
            logger.exception("LRCLIB 조회 실패")
            return None
        if not data:
            return None

        raw = data.get("plainLyrics") or ""
        if not raw and data.get("syncedLyrics"):
            raw = _strip_lrc_timestamps(data["syncedLyrics"])
        lines = _split_lines(raw)
        if not lines:
            return None
        return LyricsResult(
            lines=lines,
            language="",
            source_name="LRCLIB",
            source_url="https://lrclib.net",
            artist=data.get("artistName") or "",
            album=data.get("albumName") or "",
            title=data.get("trackName") or "",
        )


class GeniusProvider:
    """Genius(https://genius.com) — 검색 API + 가사 페이지 스크래핑(best-effort)."""

    key = "genius"

    def fetch(self, artist: str, title: str, duration_sec: int | None = None) -> LyricsResult | None:
        if not title:
            return None
        sess = _session()
        try:
            q = f"{artist} {title}".strip()
            resp = sess.get(
                "https://genius.com/api/search/multi",
                params={"q": q},
                timeout=_TIMEOUT,
            )
            if resp.status_code != 200:
                return None
            song_url = self._first_song_url(resp.json())
            if not song_url:
                return None
            page = sess.get(song_url, timeout=_TIMEOUT)
            if page.status_code != 200:
                return None
            lines, r_artist, r_title = self._parse_page(page.text)
        except Exception:
            logger.exception("Genius 조회 실패")
            return None
        if not lines:
            return None
        return LyricsResult(
            lines=lines,
            language="",
            source_name="Genius",
            source_url=song_url,
            artist=r_artist,
            title=r_title,
        )

    @staticmethod
    def _first_song_url(payload: dict) -> str:
        sections = (payload or {}).get("response", {}).get("sections", [])
        for sec in sections:
            for hit in sec.get("hits", []):
                if hit.get("type") == "song":
                    res = hit.get("result", {})
                    url = res.get("url")
                    if url:
                        return url
        return ""

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
        lines = _split_lines("\n".join(parts))
        artist = ""
        title = ""
        og = soup.find("meta", property="og:title")
        if og and og.get("content"):
            # "Title by Artist" 패턴
            m = re.match(r"^(.*)\s+by\s+(.*?)(?:\s*\|.*)?$", og["content"])
            if m:
                title, artist = m.group(1).strip(), m.group(2).strip()
        return lines, artist, title


class _KoreanScrapeProvider:
    """멜론/벅스/지니 등 국내 사이트 공통 베이스 — 검색 후 가사 페이지 스크래핑.

    사이트 구조가 자주 바뀌고 봇 차단이 있어 best-effort다. 실패 시 None.
    """

    key = ""
    display = ""

    def fetch(self, artist: str, title: str, duration_sec: int | None = None) -> LyricsResult | None:
        if not title:
            return None
        try:
            lines, url = self._scrape(artist, title)
        except Exception:
            logger.exception("%s 조회 실패", self.display or self.key)
            return None
        if not lines:
            return None
        return LyricsResult(
            lines=lines,
            language="ko",   # 국내 사이트 가사는 한국어로 가정(번역 생략)
            source_name=self.display,
            source_url=url,
        )

    def _scrape(self, artist: str, title: str) -> tuple[list[str], str]:  # pragma: no cover
        raise NotImplementedError


class MelonProvider(_KoreanScrapeProvider):
    key = "melon"
    display = "멜론"

    def _scrape(self, artist: str, title: str) -> tuple[list[str], str]:
        from bs4 import BeautifulSoup  # noqa: PLC0415

        sess = _session()
        sess.headers["Referer"] = "https://www.melon.com/"
        q = quote(f"{artist} {title}".strip())
        search = sess.get(
            f"https://www.melon.com/search/song/index.htm?q={q}&section=song",
            timeout=_TIMEOUT,
        )
        m = re.search(r"goSongDetail\('(\d+)'\)", search.text) or re.search(
            r"songId=(\d+)", search.text
        )
        if not m:
            return [], ""
        song_id = m.group(1)
        detail_url = f"https://www.melon.com/song/detail.htm?songId={song_id}"
        detail = sess.get(detail_url, timeout=_TIMEOUT)
        soup = BeautifulSoup(detail.text, "html.parser")
        box = soup.select_one("div.lyric")
        if not box:
            return [], detail_url
        for br in box.find_all("br"):
            br.replace_with("\n")
        return _split_lines(box.get_text()), detail_url


class BugsProvider(_KoreanScrapeProvider):
    key = "bugs"
    display = "벅스"

    def _scrape(self, artist: str, title: str) -> tuple[list[str], str]:
        from bs4 import BeautifulSoup  # noqa: PLC0415

        sess = _session()
        q = quote(f"{artist} {title}".strip())
        search = sess.get(
            f"https://music.bugs.co.kr/search/track?q={q}", timeout=_TIMEOUT
        )
        m = re.search(r"/track/(\d+)", search.text)
        if not m:
            return [], ""
        track_id = m.group(1)
        detail_url = f"https://music.bugs.co.kr/track/{track_id}"
        detail = sess.get(detail_url, timeout=_TIMEOUT)
        soup = BeautifulSoup(detail.text, "html.parser")
        box = soup.select_one("div.lyricsContainer xmp") or soup.select_one("div.lyricsContainer")
        if not box:
            return [], detail_url
        return _split_lines(box.get_text()), detail_url


class GenieProvider(_KoreanScrapeProvider):
    key = "genie"
    display = "지니"

    def _scrape(self, artist: str, title: str) -> tuple[list[str], str]:
        from bs4 import BeautifulSoup  # noqa: PLC0415

        sess = _session()
        q = quote(f"{artist} {title}".strip())
        search = sess.get(
            f"https://www.genie.co.kr/search/searchMain?query={q}", timeout=_TIMEOUT
        )
        m = re.search(r"fnViewSongInfo\('(\d+)'", search.text) or re.search(
            r"xgnm=(\d+)", search.text
        )
        if not m:
            return [], ""
        song_id = m.group(1)
        detail_url = f"https://www.genie.co.kr/detail/songInfo?xgnm={song_id}"
        detail = sess.get(detail_url, timeout=_TIMEOUT)
        soup = BeautifulSoup(detail.text, "html.parser")
        box = soup.select_one("#pLyrics p") or soup.select_one("pre#pLyrics")
        if not box:
            return [], detail_url
        for br in box.find_all("br"):
            br.replace_with("\n")
        return _split_lines(box.get_text()), detail_url


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
