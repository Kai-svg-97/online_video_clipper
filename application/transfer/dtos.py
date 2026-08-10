"""라이브러리 가져오기/내보내기 DTO."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ImportCategoryOptionDTO:
    """가져오기 대상 선택 트리에 쓰는 패키지 내부 카테고리 항목.

    `id`/`parent_id`는 패키지 안에서만 의미 있는 문자열 키다(로컬 DB의 UUID와는
    별개 공간) — 병합 시 이름+부모 경로로 로컬 카테고리에 매핑된다.
    """
    id: str
    name: str
    parent_id: str | None
    video_count: int


@dataclass(frozen=True)
class ImportPreviewDTO:
    categories: tuple[ImportCategoryOptionDTO, ...]
    total_video_count: int


@dataclass(frozen=True)
class ImportFieldDiffDTO:
    """존재하는 영상과 가져올 영상 사이에 값이 다른 필드 하나.

    `existing_filled`/`incoming_filled`는 각 값이 비어있지 않은지를 나타내
    "채워진 정보가 어느 쪽에 있는지" 한눈에 판단할 수 있게 한다.
    """
    field: str
    label: str
    existing_value: str
    incoming_value: str
    existing_filled: bool
    incoming_filled: bool
    default_choice: str   # "existing" | "incoming"


@dataclass(frozen=True)
class ImportConflictDTO:
    """이미 로컬에 있는 영상(URL 일치)과 값이 다른 필드가 하나라도 있는 경우."""
    url: str
    title: str
    fields: tuple[ImportFieldDiffDTO, ...]


@dataclass(frozen=True)
class ImportConflictsDTO:
    conflicts: tuple[ImportConflictDTO, ...]
    new_video_count: int


@dataclass(frozen=True)
class ImportResultDTO:
    created_count: int
    merged_count: int
    category_count: int


@dataclass(frozen=True)
class ExportResultDTO:
    path: str
    category_count: int
    video_count: int
