from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from uuid import UUID

from domain.library.aggregates import VideoAggregate
from domain.library.entities import Category, Playlist, PlaylistFolder, Tag


_ALLOWED_SORT_COLUMNS = frozenset({"created_at", "title", "channel_name", "duration_sec"})

# 검색 일치 속성 식별자 — 표시 순서를 고정한다. 한글 라벨 매핑은 GUI가 갖는다.
MATCH_FIELD_KEYS: tuple[str, ...] = (
    "title", "tags", "description", "notes", "summary", "song", "lyrics",
)

# 가사 검색을 허용할 최상위(루트) 카테고리 이름 — trim + 소문자로 비교한다.
# 검색 계약의 일부라 도메인에 둔다(테스트가 import 해 규칙을 고정).
MUSIC_ROOT_CATEGORY_NAMES: frozenset[str] = frozenset({"music", "음악", "노래"})


@dataclass
class SearchQuery:
    text: str = ""
    category_id: UUID | None = None
    category_ids: list[UUID] = field(default_factory=list)
    tag_ids: list[UUID] = field(default_factory=list)
    video_ids: list[UUID] = field(default_factory=list)  # 재생목록 필터 — 빈 리스트 = 필터 없음
    categorized_only: bool = False     # True = 카테고리에 속한 영상만(category_id IS NOT NULL)
    favorite_only: bool = False
    watched: bool | None = None        # None = both
    limit: int = 50
    offset: int = 0
    sort_by: str = "created_at"        # created_at | title | channel_name | duration_sec
    sort_asc: bool = False
    min_duration_sec: int | None = None
    max_duration_sec: int | None = None


class IVideoRepository(ABC):
    @abstractmethod
    def save(self, aggregate: VideoAggregate) -> None: ...

    @abstractmethod
    def get_by_id(self, video_id: UUID) -> VideoAggregate | None: ...

    @abstractmethod
    def search(self, query: SearchQuery) -> list[VideoAggregate]: ...

    @abstractmethod
    def get_summary_status(self, video_id: UUID) -> str:
        """Gemini 요약 실패 사유를 반환한다(없으면 빈 문자열).

        상세 화면이 "질문하기 버튼이 없어 실패"와 일반 오류를 구분해 안내하는 데 쓴다.
        """

    @abstractmethod
    def set_summary_status(self, video_id: UUID, status: str) -> None:
        """Gemini 요약 실패 사유를 기록한다(기존 값 덮어씀)."""

    @abstractmethod
    def clear_summary_status(self, video_id: UUID) -> None:
        """요약을 성공적으로 가져왔을 때 실패 사유를 지운다(없어도 예외 없음)."""

    @abstractmethod
    def match_fields_for(
        self, video_ids: list[UUID], text: str
    ) -> dict[UUID, tuple[str, ...]]:
        """각 영상이 검색어와 어느 속성에서 일치했는지 반환한다.

        반환 값은 MATCH_FIELD_KEYS 순서를 따른다. 일치가 없는 영상은 키를 생략한다.
        현재 페이지 분량(기본 50건)만 넘겨 호출하는 것을 전제로 한다.
        """

    @abstractmethod
    def count(self, query: SearchQuery) -> int: ...

    @abstractmethod
    def delete(self, video_id: UUID) -> None: ...

    @abstractmethod
    def exists_by_url(self, url: str) -> bool: ...

    @abstractmethod
    def get_by_url(self, url: str) -> VideoAggregate | None: ...

    # Category management
    @abstractmethod
    def list_categories(self) -> list[Category]: ...

    @abstractmethod
    def list_category_video_counts(self) -> dict[UUID, int]: ...

    @abstractmethod
    def save_category(self, category: Category) -> None: ...

    @abstractmethod
    def delete_category(self, category_id: UUID) -> None: ...

    # Tag management
    @abstractmethod
    def list_tags(self) -> list[Tag]: ...

    @abstractmethod
    def list_tags_with_counts(
        self,
        *,
        category_ids: list[UUID] | None = None,
        video_ids: list[UUID] | None = None,
    ) -> list[tuple[Tag, int]]:
        """태그별 사용 횟수. 스코프 지정 시 해당 영상들에 달린 태그만 집계."""
        ...

    @abstractmethod
    def save_tag(self, tag: Tag) -> None: ...

    @abstractmethod
    def get_or_create_tag(self, name: str) -> Tag: ...

    @abstractmethod
    def delete_tag(self, tag_id: UUID) -> None: ...

    @abstractmethod
    def delete_zero_count_tags(self) -> int:
        """Delete tags not linked to any video. Returns count of deleted tags."""
        ...

    # Category video order
    @abstractmethod
    def get_category_video_order(self, category_id: UUID) -> list[UUID]:
        """카테고리 내 수동 영상 순서를 반환한다. 없으면 빈 리스트."""
        ...

    @abstractmethod
    def set_category_video_order(self, category_id: UUID, video_ids: list[UUID]) -> None:
        """카테고리 내 영상 순서를 전체 교체 저장한다."""
        ...


class IPlaylistRepository(ABC):
    @abstractmethod
    def save(self, playlist: Playlist) -> None: ...

    @abstractmethod
    def get_by_id(self, playlist_id: UUID) -> Playlist | None: ...

    @abstractmethod
    def list_all(self) -> list[Playlist]: ...

    @abstractmethod
    def delete(self, playlist_id: UUID) -> None: ...

    @abstractmethod
    def get_by_yt_id(self, yt_playlist_id: str) -> Playlist | None: ...

    @abstractmethod
    def get_items(self, playlist_id: UUID) -> list[tuple[UUID, int]]:
        """(video_id, position) 쌍 목록 반환 (position 오름차순)."""
        ...

    @abstractmethod
    def set_items(self, playlist_id: UUID, video_ids: list[UUID]) -> None:
        """전체 순서를 원자적으로 교체 (DELETE + INSERT). item_count도 갱신."""
        ...

    @abstractmethod
    def add_video(
        self,
        playlist_id: UUID,
        video_id: UUID,
        position: int | None = None,
    ) -> None:
        """재생목록에 영상 추가. position=None이면 맨 끝에 추가."""
        ...

    @abstractmethod
    def remove_video(self, playlist_id: UUID, video_id: UUID) -> None: ...

    @abstractmethod
    def update_folder(self, playlist_id: UUID, folder_id: UUID | None) -> None:
        """재생목록의 소속 폴더를 변경한다."""
        ...

    @abstractmethod
    def get_yt_item_id(self, playlist_id: UUID, video_id: UUID) -> str | None:
        """playlist_items.yt_item_id 조회 (YouTube API 삭제 시 사용)."""
        ...

    @abstractmethod
    def set_yt_item_id(self, playlist_id: UUID, video_id: UUID, yt_item_id: str) -> None:
        """playlist_items.yt_item_id 저장."""
        ...


class IPlaylistFolderRepository(ABC):
    @abstractmethod
    def save(self, folder: PlaylistFolder) -> None: ...

    @abstractmethod
    def get_by_id(self, folder_id: UUID) -> PlaylistFolder | None: ...

    @abstractmethod
    def list_by_source(self, source: str | None = None) -> list[PlaylistFolder]:
        """source=None이면 전체 반환."""
        ...

    @abstractmethod
    def delete(self, folder_id: UUID) -> None: ...
