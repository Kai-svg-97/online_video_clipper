# 메모리 프로파일링 실측 결과

> `CLAUDE.md`에서 분리됐다. 지켜야 할 **규칙**은 CLAUDE.md에 남아 있고,
> 여기에는 그 규칙이 실제로 지켜지고 있는지 확인한 **측정값**을 담는다.

### Memory Profiling Results (v1.22.0 이후 검증)

- **썸네일 LRU 캐시 상한**: 100개/렌더 크기 종류(아이콘·리스트·상세) = 300개 QPixmap 최악 시 66MB (`QPixmapCache.setCacheLimit(30720)` 별도).
  - 아이콘 그리드(160×90) + 리스트(80×45) + 상세 뷰(배경용 큰 이미지)의 3 경로.
  - `library_panel.py`의 `_thumb_cache`에 대한 상한은 `library/thumbnails.py`의 `_ThumbnailCache` 데코레이터로 관리.
- **페이지네이션 구현 완료**: 모든 리포지토리 쿼리에 `LIMIT/OFFSET` 적용(기본 50), `.fetchall()` 사용 지점 0개, 커서 반복만 사용.
  - 검증: `tests/integration/test_downloaded_formats_bulk.py`(배치 조회), `tests/integration/test_search_fields.py`(검색 페이징).
- **Lazy Load 확인**:
  - `description`, `notes` 필드: `GetVideoDetailHandler` 상세 조회 시에만, 목록 쿼리에서 제외.
  - `song_info` 전체: 노래 탭 진입 시에만 `SongViewModel.load()` 호출.
  - 자막/영상 메타: 재생 시작 시점에만 `_on_playback_state`에서 조회.
- **기타 확인**:
  - `__slots__` 적용: `VideoUrl`, `Duration`, `Timestamp`, `ChannelInfo`, `DownloadProgress` 등 value objects (통계: ~30개 클래스).
  - Generator expressions: `_run_list`, `search_videos`, `get_related_videos` 경로 확인됨.
  - 백그라운드 QThread: 플레이리스트 임포트 50개 청크 단위, 다운로드 진행률 콜백 구현됨.

---

