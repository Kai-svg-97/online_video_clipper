<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-06-20 | Updated: 2026-06-20 -->

# infrastructure/youtube

## Purpose
YouTube Data API v3 연동. OAuth 2.0 토큰 발급·갱신(`oauth_adapter.py`)과 API 래퍼(`youtube_api_adapter.py`)로 구성된다.
메타데이터 보강(게시일·조회수·길이), 재생목록 관리, 채널 정보 조회에 사용된다.

## Key Files

| File | Description |
|------|-------------|
| `__init__.py` | 패키지 마커 |
| `oauth_adapter.py` | `YouTubeOAuthAdapter` — OAuth 2.0 토큰 발급·갱신·저장 (SQLite) |
| `youtube_api_adapter.py` | `YouTubeApiAdapter` — YouTube Data API v3 래퍼 (videos.list, playlists.insert 등) |

## For AI Agents

### Working In This Directory
- `_yt_api`가 `None`일 때(OAuth 미설정) graceful 처리 필수 — 모든 호출자가 None 체크.
- `videos.list` 배치 조회: `get_videos_channels(video_ids, part=...)` — 채널별 영상 메타데이터 보강에 사용.
- `get_latest_upload_dates(channel_ids)`: 채널당 1쿼터, 스레드풀 병렬 처리.
- API 할당량(quota) 초과 시 graceful fallback 필수.

### Key Methods
| Method | Purpose |
|--------|---------|
| `get_videos_channels(video_ids, part)` | videos.list 배치로 게시일·조회수·길이 조회 |
| `get_latest_upload_dates(channel_ids)` | 채널별 최근 업로드 날짜 |
| `list_playlists()` | 사용자 재생목록 목록 |
| `create_playlist(title)` | 재생목록 생성 |

## Dependencies

### External
- `google-api-python-client` — YouTube Data API v3
- `google-auth-oauthlib`, `google-auth-httplib2` — OAuth 2.0

<!-- MANUAL: -->
