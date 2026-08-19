"""영상 자막 트랙 목록 조회 + 내려받기 (yt-dlp 정보 + HTTP).

**QThread에서만 호출한다** — yt-dlp 조회도 자막 내려받기도 네트워크다.

자동 번역은 우리가 문장을 번역하지 않고 **YouTube의 번역 트랙을 그대로 받는다**
(캡션 URL에 `tlang=<코드>`를 붙이면 번역본이 온다). 이유는 두 가지다.

1. 정확도·속도 모두 낫다. 문장을 하나씩 번역기에 보내면 자막 한 편에 수백 번의
   왕복이 생기고, 문맥이 끊겨 품질도 떨어진다.
2. 이미 있는 기능이다. 가사 번역(`deep-translator`)은 짧은 텍스트 한 덩어리라
   사정이 다르다 — 같은 도구를 자막에 쓰면 감당이 안 된다.

번역 트랙은 **자동 생성 자막에만 안정적으로 붙는다**(YouTube 제약). 수동 자막에도
붙여 볼 수는 있으나 실패하면 원본을 그대로 쓴다 — 자막을 통째로 잃는 것보다 낫다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import requests

from infrastructure.subtitle.parsers import Cue, parse_cues

logger = logging.getLogger(__name__)

# 우선순위가 높은 형식부터 — json3가 가장 깨끗하다(parsers 모듈 설명 참고).
_PREFERRED_EXTS = ("json3", "vtt", "srv3", "srv1")
_TIMEOUT = (5, 10)          # (연결, 읽기) — 느린 트랙 때문에 재생을 붙잡지 않는다
_MAX_BYTES = 8 * 1024 * 1024

# 자동 번역 대상 — 흔히 쓰는 것만 짧게 둔다(메뉴가 길면 고르기 어렵다).
TRANSLATE_TARGETS: tuple[tuple[str, str], ...] = (
    ("ko", "한국어"),
    ("en", "English"),
    ("ja", "日本語"),
    ("zh-Hans", "中文(简体)"),
    ("es", "Español"),
)


@dataclass(frozen=True, slots=True)
class SubtitleTrackInfo:
    """고를 수 있는 자막 트랙 하나."""

    lang: str            # "ko", "en", "en-US"
    name: str            # 사람이 읽는 이름
    url: str
    ext: str             # "json3" | "vtt" | ...
    auto: bool           # 자동 생성 여부
    translate_to: str = ""   # 자동 번역 대상 언어(빈 값이면 원본)

    @property
    def key(self) -> str:
        """선택 상태 비교용 식별자 — 같은 언어의 원본/번역을 구분한다."""
        return f"{'auto' if self.auto else 'sub'}:{self.lang}:{self.translate_to}"

    @property
    def label(self) -> str:
        """메뉴에 적는 이름."""
        base = self.name or self.lang
        if self.auto and "자동" not in base:
            base = f"{base} (자동 생성)"
        if self.translate_to:
            target = dict(TRANSLATE_TARGETS).get(self.translate_to, self.translate_to)
            base = f"{base} → {target} 번역"
        return base


def _is_translation(entry: dict) -> bool:
    """이미 번역된 트랙인지 — URL에 `tlang`이 붙어 있으면 YouTube가 번역한 것이다.

    **이 걸러내기가 없으면 메뉴가 쓸 수 없게 된다.** YouTube의 자동 자막 목록에는
    번역 가능한 **모든 언어**(수백 개)가 들어 있어서, 그대로 나열하면 원래 언어가
    어느 것인지도 알 수 없다. 번역은 우리 '자동 번역' 항목이 따로 담당한다.
    """
    return "tlang=" in (entry.get("url") or "")


def _normalize_lang(lang: str) -> str:
    """자동 자막의 `en-en` 같은 키를 `en`으로 줄인다.

    실측: 번역이 아닌 원본 자동 자막의 키는 `<대상>-<출처>` 꼴이고 둘이 같다
    (`en-en`, `de-de`). 그대로 두면 수동 자막 `de`와 다른 언어로 보여 목록에 같은
    언어가 두 번 뜨고, "지난번에 고른 언어"도 영상마다 어긋난다.
    """
    parts = (lang or "").split("-")
    if len(parts) == 2 and parts[0] == parts[1]:
        return parts[0]
    return lang


def _pick_ext(entries: list[dict]) -> dict | None:
    """한 언어의 여러 형식 중 우리가 잘 다루는 것을 고른다(번역본은 제외)."""
    by_ext = {(e.get("ext") or "").lower(): e
              for e in entries if e.get("url") and not _is_translation(e)}
    for ext in _PREFERRED_EXTS:
        if ext in by_ext:
            return by_ext[ext]
    return next(iter(by_ext.values()), None)


def list_tracks(info: dict) -> list[SubtitleTrackInfo]:
    """yt-dlp info dict에서 자막 트랙 목록을 뽑는다(수동 자막 우선, 자동 생성은 뒤).

    같은 언어가 수동·자동 양쪽에 있으면 **수동만** 남긴다 — 사람이 단 자막이 항상 낫고,
    목록에 같은 언어가 두 번 뜨면 무엇을 고를지 알 수 없다.
    """
    out: list[SubtitleTrackInfo] = []
    seen: set[str] = set()
    for auto, block in ((False, info.get("subtitles")), (True, info.get("automatic_captions"))):
        for raw_lang, entries in (block or {}).items():
            lang = _normalize_lang(raw_lang)
            if lang in seen or not entries:
                continue
            chosen = _pick_ext(list(entries))
            if not chosen:
                continue
            seen.add(lang)
            out.append(
                SubtitleTrackInfo(
                    lang=lang,
                    name=chosen.get("name") or lang,
                    url=chosen["url"],
                    ext=(chosen.get("ext") or "").lower(),
                    auto=auto,
                )
            )
    out.sort(key=lambda t: (t.auto, t.lang))
    return out


def translated(track: SubtitleTrackInfo, target_lang: str) -> SubtitleTrackInfo:
    """같은 트랙의 '번역본' 정보를 만든다(URL에 tlang을 붙인다)."""
    return SubtitleTrackInfo(
        lang=track.lang, name=track.name, url=track.url, ext=track.ext,
        auto=track.auto, translate_to=target_lang,
    )


def _with_tlang(url: str, target_lang: str) -> str:
    """캡션 URL에 번역 대상 언어를 넣는다(이미 있으면 갈아 끼운다)."""
    parts = urlparse(url)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if k != "tlang"]
    query.append(("tlang", target_lang))
    return urlunparse(parts._replace(query=urlencode(query)))


def fetch_cues(track: SubtitleTrackInfo, session: requests.Session | None = None) -> list[Cue]:
    """자막 파일을 내려받아 큐 목록으로 만든다(실패하면 빈 목록).

    번역 트랙을 받다 실패하면 **원본으로 한 번 더 시도**한다 — 번역이 없다고 자막
    자체를 잃을 이유는 없다.
    """
    http = session or requests
    urls = [track.url]
    if track.translate_to:
        urls = [_with_tlang(track.url, track.translate_to), track.url]
    for attempt, url in enumerate(urls):
        try:
            resp = http.get(url, timeout=_TIMEOUT)
            resp.raise_for_status()
            raw = resp.text[:_MAX_BYTES]
        except Exception as exc:
            # 네트워크 실패는 트레이스백 없이 — 자막은 없어도 재생은 계속된다.
            logger.warning("자막 내려받기 실패(%s): %s", track.lang, exc)
            continue
        cues = parse_cues(raw, track.ext)
        if cues:
            if attempt and track.translate_to:
                logger.info("자막 번역본을 받지 못해 원본으로 표시합니다(%s)", track.lang)
            return cues
        logger.warning("자막을 해석하지 못했습니다(lang=%s, ext=%s)", track.lang, track.ext)
    return []


def fetch_tracks_for_url(url: str, cookie_opts: dict | None = None) -> list[SubtitleTrackInfo]:
    """영상 URL에서 자막 트랙 목록을 조회한다(yt-dlp). QThread에서만 호출한다."""
    from yt_dlp import YoutubeDL  # noqa: PLC0415 (무거운 import는 호출 시점에)

    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        # 자막 목록만 필요하다 — 포맷 목록까지 받아 오면 느려진다.
        "writesubtitles": True,
        "writeautomaticsub": True,
        **(cookie_opts or {}),
    }
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    return list_tracks(info or {})
