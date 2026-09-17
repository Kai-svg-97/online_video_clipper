"""자막 색인 저장소 인터페이스와 값 객체.

**왜 library 컨텍스트인가**: 자막은 Video에 딸린 부속 정보라 Video의 수명을 따른다
(영상을 지우면 자막도 사라진다). 별도 컨텍스트로 떼면 그 수명 규칙을 두 곳에서
지켜야 한다.

재생용 자막(`infrastructure/subtitle/`)은 매번 네트워크로 받아 쓰는 **일회성**이고,
여기 저장하는 것은 **검색용 색인**이다. 같은 데이터지만 쓰임과 수명이 달라 경로를
나눠 둔다 — 재생이 자막을 받은 김에 색인도 채우는 것이 가장 싼 수집 경로다.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class SubtitleLine:
    """자막 한 줄 — 검색 결과에서 그대로 시점 이동에 쓴다."""

    start_ms: int
    end_ms: int
    text: str


@dataclass(frozen=True, slots=True)
class SubtitleIndexInfo:
    """어떤 영상의 어떤 언어가 언제 색인됐는지."""

    lang: str
    label: str
    line_count: int
    indexed_at: datetime


class ISubtitleRepository(ABC):
    """자막 색인 저장소."""

    @abstractmethod
    def replace_lines(
        self, video_id: UUID, lang: str, label: str, lines: list[SubtitleLine]
    ) -> None:
        """그 영상·언어의 자막을 **통째로 교체**한다.

        부분 갱신을 두지 않는 이유: 자막은 원본이 통째로 바뀌는 데이터라
        (자동 자막이 나중에 사람 자막으로 대체되는 일이 흔하다) 줄 단위 병합은
        중복만 만든다. 빈 목록을 주면 그 언어의 색인을 지운다.
        """

    @abstractmethod
    def list_lines(self, video_id: UUID, lang: str | None = None) -> list[SubtitleLine]:
        """시작 시각 순 자막 줄. 언어를 지정하지 않으면 색인된 첫 언어를 쓴다."""

    @abstractmethod
    def list_indexes(self, video_id: UUID) -> list[SubtitleIndexInfo]:
        """그 영상에 색인된 언어 목록(없으면 빈 목록)."""

    @abstractmethod
    def search_lines(
        self, video_id: UUID, text: str, limit: int = 200
    ) -> list[SubtitleLine]:
        """한 영상 안에서 부분 일치하는 줄(시작 시각 순)."""

    @abstractmethod
    def indexed_video_ids(self) -> set[UUID]:
        """색인이 하나라도 있는 영상 id — 일괄 색인에서 건너뛸 대상 판정용."""

    @abstractmethod
    def delete(self, video_id: UUID) -> None:
        """그 영상의 색인을 전부 지운다."""
