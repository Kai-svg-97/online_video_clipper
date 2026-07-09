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

    ``lines``는 가사 원문 줄 목록(빈 리스트 = 가사 없음). 제공자가 함께 알려주는
    메타데이터(가수·앨범·제목·발매년도)는 부족분을 채우는 데 쓰인다.
    """

    lines: list[str] = field(default_factory=list)
    language: str = ""          # ISO 639-1 (예: "en", "ko") — 미상이면 ""
    source_name: str = ""       # 표시 이름 (예: "LRCLIB")
    source_url: str = ""
    artist: str = ""
    album: str = ""
    title: str = ""
    release_year: str = ""


class ILyricsProvider(Protocol):
    """단일 가사·메타데이터 출처. 구현체는 infrastructure/song/lyrics_providers.py."""

    key: str            # LyricsSource.provider_key와 매칭되는 식별자

    def fetch(
        self, artist: str, title: str, duration_sec: int | None = None
    ) -> LyricsResult | None:
        """가사를 조회한다. 실패/없음이면 None을 반환(예외를 던지지 않는다)."""
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
