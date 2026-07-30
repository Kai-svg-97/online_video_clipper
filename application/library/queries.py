from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from uuid import UUID

_QUALITY_LABELS = frozenset({"UHD (4K)", "QHD (2K)", "FHD", "HD", "SD", "LD"})
_BRACKET_RE = re.compile(r'\[([^\]]+)\]')


def _actual_quality(file_path: str | None, fallback: str) -> str:
    """파일명에 삽입된 실제 품질 레이블을 반환한다.

    ytdlp_adapter가 다운로드 완료 후 '{stem} [FHD].mp4' 형태로 파일명을 수정한다.
    해당 레이블이 없으면 fallback(요청 품질 값)을 그대로 반환.
    """
    if file_path:
        matches = _BRACKET_RE.findall(Path(file_path).stem)
        label = next((m for m in reversed(matches) if m in _QUALITY_LABELS), None)
        if label:
            return label
    return fallback

from application.library.dtos import (
    CategoryDTO,
    CategoryStatDTO,
    ChannelCategoryStatDTO,
    ChannelStatDTO,
    DownloadInfoDTO,
    FailedDownloadInfoDTO,
    LibraryStatsDTO,
    TagDTO,
    VideoDTO,
    VideoDetailDTO,
)
from domain.download.repositories import IDownloadRepository
from domain.library.aggregates import VideoAggregate
from domain.library.repositories import IVideoRepository, SearchQuery

logger = logging.getLogger(__name__)


@dataclass
class GetVideosQuery:
    category_id: UUID | None = None
    category_ids: list[UUID] = field(default_factory=list)
    tag_ids: list[UUID] = field(default_factory=list)
    video_ids: list[UUID] = field(default_factory=list)
    categorized_only: bool = False
    favorite_only: bool = False
    watched: bool | None = None
    limit: int = 50
    offset: int = 0
    sort_by: str = "created_at"
    sort_asc: bool = False
    min_duration_sec: int | None = None
    max_duration_sec: int | None = None


@dataclass
class SearchVideosQuery:
    text: str
    category_id: UUID | None = None
    category_ids: list[UUID] = field(default_factory=list)
    tag_ids: list[UUID] = field(default_factory=list)
    video_ids: list[UUID] = field(default_factory=list)
    categorized_only: bool = False
    favorite_only: bool = False
    limit: int = 50
    offset: int = 0
    sort_by: str = "created_at"
    sort_asc: bool = False
    min_duration_sec: int | None = None
    max_duration_sec: int | None = None


@dataclass
class GetVideoByIdQuery:
    video_id: UUID


def _to_dto(
    agg: VideoAggregate,
    cats: dict | None = None,
    tag_id_to_name: dict[UUID, str] | None = None,
) -> VideoDTO:
    v = agg.video
    cat_name = ""
    if cats and agg.category_id:
        cat_name = cats.get(agg.category_id, "")
    published = v.published_at.strftime("%Y-%m-%d") if v.published_at else None
    tag_names: tuple[str, ...] = ()
    if tag_id_to_name and agg.tag_ids:
        tag_names = tuple(tag_id_to_name[tid] for tid in agg.tag_ids if tid in tag_id_to_name)
    created = v.created_at.strftime("%Y-%m-%d %H:%M") if getattr(v, "created_at", None) else None
    return VideoDTO(
        id=agg.id,
        url=v.url.value,
        title=v.title,
        channel_name=v.channel.name if v.channel else "",
        thumbnail_path=v.thumbnail_path,
        duration_sec=v.duration.seconds if v.duration else None,
        favorite=v.favorite,
        watched=v.watched,
        category_id=agg.category_id,
        category_name=cat_name,
        published_at=published,
        view_count=v.view_count,
        tag_names=tag_names,
        created_at=created,
    )


def _cats_dict(repo: IVideoRepository) -> dict:
    return {c.id: c.name for c in repo.list_categories()}


def _tags_dict(repo: IVideoRepository) -> dict[UUID, str]:
    return {t.id: t.name for t in repo.list_tags()}


class GetVideosHandler:
    def __init__(self, repo: IVideoRepository) -> None:
        self._repo = repo

    def handle(self, query: GetVideosQuery) -> list[VideoDTO]:
        cats = _cats_dict(self._repo)
        tag_id_to_name = _tags_dict(self._repo)
        return [
            _to_dto(agg, cats, tag_id_to_name)
            for agg in self._repo.search(
                SearchQuery(
                    category_id=query.category_id,
                    category_ids=query.category_ids,
                    tag_ids=query.tag_ids,
                    video_ids=query.video_ids,
                    categorized_only=query.categorized_only,
                    favorite_only=query.favorite_only,
                    watched=query.watched,
                    limit=query.limit,
                    offset=query.offset,
                    sort_by=query.sort_by,
                    sort_asc=query.sort_asc,
                    min_duration_sec=query.min_duration_sec,
                    max_duration_sec=query.max_duration_sec,
                )
            )
        ]


class SearchVideosHandler:
    def __init__(self, repo: IVideoRepository) -> None:
        self._repo = repo

    def handle(self, query: SearchVideosQuery) -> list[VideoDTO]:
        cats = _cats_dict(self._repo)
        tag_id_to_name = _tags_dict(self._repo)
        aggs = self._repo.search(
            SearchQuery(
                text=query.text,
                category_id=query.category_id,
                category_ids=query.category_ids,
                tag_ids=query.tag_ids,
                video_ids=query.video_ids,
                categorized_only=query.categorized_only,
                favorite_only=query.favorite_only,
                limit=query.limit,
                offset=query.offset,
                sort_by=query.sort_by,
                sort_asc=query.sort_asc,
                min_duration_sec=query.min_duration_sec,
                max_duration_sec=query.max_duration_sec,
            )
        )
        dtos = [_to_dto(agg, cats, tag_id_to_name) for agg in aggs]
        if not query.text:
            return dtos
        # 일치 속성은 현재 페이지에만 판정한다(전체 스캔 방지).
        matches = self._repo.match_fields_for([d.id for d in dtos], query.text)
        return [replace(d, match_fields=matches.get(d.id, ())) for d in dtos]


class GetVideoByIdHandler:
    def __init__(self, repo: IVideoRepository) -> None:
        self._repo = repo

    def handle(self, query: GetVideoByIdQuery) -> VideoDTO | None:
        agg = self._repo.get_by_id(query.video_id)
        if agg is None:
            return None
        cats = _cats_dict(self._repo)
        return _to_dto(agg, cats)


class GetVideoDetailHandler:
    """Returns rich VideoDetailDTO including description, tags, and download history."""

    def __init__(self, video_repo: IVideoRepository, dl_repo: IDownloadRepository) -> None:
        self._video_repo = video_repo
        self._dl_repo = dl_repo

    def handle(self, video_id: UUID) -> VideoDetailDTO | None:
        agg = self._video_repo.get_by_id(video_id)
        if agg is None:
            return None
        v = agg.video

        # Resolve tag names
        all_tags = {t.id: t for t in self._video_repo.list_tags()}
        tag_names = [all_tags[tid].name for tid in agg.tag_ids if tid in all_tags]

        # Download history for this URL
        completed = self._dl_repo.find_completed_by_url(v.url.value)
        downloads = []
        for j in completed:
            fp = Path(j.file_path) if j.file_path else None
            size = fp.stat().st_size if fp and fp.exists() else None
            downloads.append(DownloadInfoDTO(
                quality=_actual_quality(j.file_path, j.settings.quality.value),
                fmt=j.settings.format.value,
                file_path=j.file_path,
                file_size_bytes=size,
            ))

        published = v.published_at.strftime("%Y-%m-%d") if v.published_at else None

        failed_jobs = self._dl_repo.find_failed_by_url(v.url.value)
        failed_downloads = [
            FailedDownloadInfoDTO(
                error_msg=j.error_msg or "알 수 없는 오류",
                created_at=j.created_at,
            )
            for j in failed_jobs
        ]

        return VideoDetailDTO(
            id=agg.id,
            url=v.url.value,
            title=v.title,
            channel_name=v.channel.name if v.channel else "",
            channel_url=v.channel.url if v.channel else "",
            thumbnail_path=v.thumbnail_path,
            duration_sec=v.duration.seconds if v.duration else None,
            published_at=published,
            view_count=v.view_count,
            favorite=v.favorite,
            watched=v.watched,
            category_id=agg.category_id,
            notes=v.notes,
            description=v.description,
            tags=tag_names,
            downloads=downloads,
            failed_downloads=failed_downloads,
            gemini_summary=v.gemini_summary,
            summary_status=self._video_repo.get_summary_status(agg.id),
        )


class GetVideoIdByUrlHandler:
    """URL로 라이브러리 영상 ID 조회 — 다운로드 패널 카드 클릭 시 상세화면 연결에 사용."""

    def __init__(self, repo: IVideoRepository) -> None:
        self._repo = repo

    def handle(self, url: str) -> UUID | None:
        agg = self._repo.get_by_url(url)
        return agg.id if agg else None


class GetCategoriesHandler:
    def __init__(self, repo: IVideoRepository) -> None:
        self._repo = repo

    def handle(self) -> list[CategoryDTO]:
        try:
            counts = self._repo.list_category_video_counts()
        except Exception:
            logger.exception("카테고리별 영상 수 조회 실패")
            counts = {}
        return [
            CategoryDTO(id=c.id, name=c.name, parent_id=c.parent_id, video_count=counts.get(c.id, 0))
            for c in self._repo.list_categories()
        ]


@dataclass
class GetTagsQuery:
    """태그 목록 조회. 스코프 미지정 시 라이브러리 전체.

    category_ids: 해당 카테고리(하위 포함) 영상들의 태그만 집계.
    video_ids: 해당 영상들의 태그만 집계(재생목록 스코프).
    """
    category_ids: list[UUID] = field(default_factory=list)
    video_ids: list[UUID] = field(default_factory=list)


class GetTagsHandler:
    def __init__(self, repo: IVideoRepository) -> None:
        self._repo = repo

    def handle(self, query: GetTagsQuery | None = None) -> list[TagDTO]:
        cat_ids = query.category_ids if query else None
        vid_ids = query.video_ids if query else None
        return [
            TagDTO(id=t.id, name=t.name, count=c)
            for t, c in self._repo.list_tags_with_counts(
                category_ids=cat_ids or None,
                video_ids=vid_ids or None,
            )
        ]


@dataclass
class GetCategoryVideoOrderQuery:
    category_id: UUID


class GetCategoryVideoOrderHandler:
    def __init__(self, repo: IVideoRepository) -> None:
        self._repo = repo

    def handle(self, query: GetCategoryVideoOrderQuery) -> list[UUID]:
        return self._repo.get_category_video_order(query.category_id)


class LibraryStatsHandler:
    """라이브러리 통계 집계 핸들러. video_repo는 get_library_stats() 지원 구체 타입이어야 함."""

    def __init__(self, video_repo, dl_repo: IDownloadRepository) -> None:
        self._video_repo = video_repo
        self._dl_repo = dl_repo

    def handle(self) -> LibraryStatsDTO:
        raw = self._video_repo.get_library_stats()
        cat_stats = [CategoryStatDTO(name=n, count=c) for n, c in raw["category_stats"]]

        # 다운로드 통계
        try:
            dl_history = self._dl_repo.get_history(limit=10000, offset=0)
            total_dl = len(dl_history)
            total_bytes = 0
            from pathlib import Path  # noqa: PLC0415

            # 같은 파일을 가리키는 이력 레코드가 여러 개(재시도·중복 다운로드)면
            # 동일 파일이 중복 합산되므로, 정규화된 경로 기준으로 1회만 집계한다.
            # 또한 영상 파일만 집계해 썸네일·메타데이터(.jpg/.part 등)를 제외한다.
            video_exts = {
                ".mp4", ".mkv", ".webm", ".avi", ".mov", ".flv", ".m4a", ".mp3", ".opus"
            }
            counted: set = set()
            for j in dl_history:
                if not j.file_path:
                    continue
                p = Path(j.file_path)
                if p.suffix.lower() not in video_exts or not p.exists():
                    continue
                key = str(p.resolve())
                if key in counted:
                    continue
                counted.add(key)
                total_bytes += p.stat().st_size
        except Exception:
            logger.exception("다운로드 통계 집계 실패")
            total_dl = 0
            total_bytes = 0

        return LibraryStatsDTO(
            total_videos=raw["total_videos"],
            total_duration_sec=raw["total_duration_sec"],
            watched_count=raw["watched_count"],
            favorite_count=raw["favorite_count"],
            category_stats=cat_stats,
            total_downloads=total_dl,
            total_download_bytes=total_bytes,
            channel_stats=self._build_channel_stats(),
        )

    def _build_channel_stats(self) -> list[ChannelStatDTO]:
        """채널별 카테고리 통계를 조립한다. 카테고리 경로는 부모 체인을 거슬러 만든다."""
        get_fn = getattr(self._video_repo, "get_channel_category_stats", None)
        if not callable(get_fn):
            return []
        try:
            raw = get_fn()
            cats = {c.id: c for c in self._video_repo.list_categories()}
        except Exception:
            logger.exception("채널별 통계 집계 실패")
            return []

        def path_of(cat_id: UUID) -> str:
            parts: list[str] = []
            seen: set[UUID] = set()
            cur: UUID | None = cat_id
            while cur is not None and cur in cats and cur not in seen:
                seen.add(cur)
                node = cats[cur]
                parts.append(node.name)
                cur = node.parent_id
            return " > ".join(reversed(parts))

        from collections import defaultdict  # noqa: PLC0415
        grouped: dict[str, list[ChannelCategoryStatDTO]] = defaultdict(list)
        channel_urls: dict[str, str] = {}
        for channel, ch_url, ch_id, cat_id_str, cnt in raw:
            try:
                cid = UUID(str(cat_id_str))
            except (ValueError, TypeError, AttributeError):
                continue
            grouped[channel].append(
                ChannelCategoryStatDTO(
                    category_id=cid,
                    category_path=path_of(cid) or "미분류",
                    count=cnt,
                )
            )
            # 채널 URL: channel_url 우선, 없으면 channel_id로 표준 URL 구성. 채널당 1회.
            if channel not in channel_urls:
                if ch_url:
                    channel_urls[channel] = ch_url
                elif ch_id:
                    channel_urls[channel] = f"https://www.youtube.com/channel/{ch_id}"
                else:
                    channel_urls[channel] = ""

        result: list[ChannelStatDTO] = []
        for channel, cat_list in grouped.items():
            cat_list.sort(key=lambda x: (-x.count, x.category_path))
            result.append(
                ChannelStatDTO(
                    channel_name=channel,
                    total=sum(x.count for x in cat_list),
                    categories=cat_list,
                    channel_url=channel_urls.get(channel, ""),
                )
            )
        result.sort(key=lambda x: (-x.total, x.channel_name.lower()))
        return result
