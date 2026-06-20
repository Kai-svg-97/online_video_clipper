<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-06-20 | Updated: 2026-06-20 -->

# infrastructure/downloader

## Purpose
yt-dlp 래퍼 어댑터. `IMediaSource` 포트를 구조적으로 만족하며, 영상 메타데이터 조회, 파일 다운로드, 썸네일 다운로드, 재생목록·구독 피드·채널 영상 조회를 담당한다.

## Key Files

| File | Description |
|------|-------------|
| `__init__.py` | 패키지 마커 |
| `ytdlp_adapter.py` | `YtDlpAdapter` — `IMediaSource` 구현, 진행률 콜백 지원 |

## For AI Agents

### Working In This Directory
- `YtDlpAdapter`는 `on_progress` 콜백을 받는 생성자를 통해 작업별 인스턴스 생성 — `main.py`의 `make_downloader = lambda cb: YtDlpAdapter(on_progress=cb)` 패턴.
- `fetch_subscription_feed()`, `fetch_channel_videos()`는 `extract_flat=True` 옵션으로 빠른 목록 조회 — 게시일·조회수는 YouTube Data API로 보강 필요.
- 쿠키 옵션(`cookie_opts`)으로 인증된 요청 지원 (브라우저 쿠키 또는 Netscape 쿠키 파일).
- ffmpeg 경로는 `utils.resources.get_ffmpeg_path()` 사용.

### Key Methods (IMediaSource)
| Method | Purpose |
|--------|---------|
| `fetch_metadata(url)` | 단일 영상 메타데이터 딕셔너리 반환 |
| `download_thumbnail(...)` | 썸네일 URL → `THUMBNAIL_DIR`에 저장, 상대 경로 반환 |
| `download(url, settings, output_dir)` | 파일 다운로드 → 파일 경로 반환 |
| `fetch_user_playlists(cookie_opts)` | YouTube 사용자 재생목록 목록 |
| `fetch_subscription_feed(limit, cookie_opts)` | 구독 피드 영상 목록 (flat) |
| `fetch_channel_videos(channel_url, limit, cookie_opts)` | 채널 영상 목록 |

## Dependencies

### External
- `yt-dlp` — 1000+ 사이트 지원

<!-- MANUAL: -->
