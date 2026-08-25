<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-06-20 | Updated: 2026-06-20 -->

# application/library

## Purpose
라이브러리 Bounded Context의 애플리케이션 레이어. 영상 CRUD, 카테고리 관리, 태그, 재생목록, YouTube 재생목록 가져오기 등 모든 커맨드·쿼리 핸들러와 DTO를 제공한다.

## Key Files

| File | Description |
|------|-------------|
| `commands.py` | `AddVideoHandler`, `UpdateVideoHandler`, `DeleteVideoHandler`, `MarkWatchedHandler`, `AssignCategoryHandler`, `CreateCategoryHandler`, `RenameCategoryHandler`, `DeleteCategoryHandler`, `MoveCategoryHandler`, `DeleteTagHandler`, `RefreshCategoryMetadataHandler`, `RefreshVideoThumbnailHandler`, `ImportYouTubePlaylistToCategoryHandler`, `SetCategoryVideoOrderHandler` |
| `queries.py` | `GetVideosHandler`, `SearchVideosHandler`, `GetCategoriesHandler`, `GetTagsHandler`, `GetVideoDetailHandler`, `LibraryStatsHandler`, `GetCategoryVideoOrderHandler` |
| `playlist_commands.py` | `CreatePlaylistHandler`, `DeletePlaylistHandler`, `AddVideoToPlaylistHandler`, `RemoveVideoFromPlaylistHandler`, `ReorderPlaylistHandler`, `ImportYouTubePlaylistHandler`, `CopyYouTubePlaylistToLocalHandler`, `PushPlaylistToYouTubeHandler`, `MoveVideoToPlaylistHandler`, `AddUrlToPlaylistHandler`, `RenamePlaylistHandler`, 폴더 관련 핸들러 |
| `playlist_queries.py` | `GetPlaylistsHandler`, `GetPlaylistItemsHandler`, `GetPlaylistFoldersHandler`, `GetSubscriptionFeedHandler`, `GetChannelVideosHandler`, `GetSubscribedChannelInfosHandler`, `GetYouTubePlaylistsHandler` |
| `dtos.py` | `VideoDTO`, `VideoDetailDTO`, `CategoryDTO`, `TagDTO`, `LibraryStatsDTO`, `DownloadInfoDTO`, `CategoryStatDTO` |
| `favorites.py` | 즐겨찾기 관련 헬퍼 |

## For AI Agents

### Working In This Directory
- `GetSubscriptionFeedHandler`·`GetChannelVideosHandler`: yt-dlp `extract_flat` 후 YouTube Data API `videos.list`로 메타데이터(게시일·조회수·길이) 보강.
- `_yt_api` 없을 때 graceful 처리 필수 — API 미설정 시 시간 미표시, 이름순 정렬.
- `RefreshCategoryMetadataHandler`: LIMIT/OFFSET 50개 청크 순회 — 전체 메모리 로드 금지.
- `ImportYouTubePlaylistToCategoryHandler`: 워커 스레드에서 실행, 항목 단위 진행 콜백.

### Common Patterns
```python
# DTO 반환 — 엔티티 직접 노출 금지
@dataclass
class VideoDTO:
    id: str
    title: str
    url: str
    channel_name: str | None
    duration_sec: int | None
    ...

# 쿼리에 항상 limit/offset
query = GetVideosQuery(category_id=cat_id, limit=50, offset=page * 50)
```

## Dependencies

### Internal
- `domain/library/` — VideoAggregate, IVideoRepository, SearchQuery
- `domain/shared/ports.py` — IEventBus, IMediaSource

<!-- MANUAL: -->
