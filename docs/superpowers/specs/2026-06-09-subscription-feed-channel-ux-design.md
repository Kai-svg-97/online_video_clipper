# 구독 피드 채널 UX 개선 설계

작성일: 2026-06-09

## 배경

라이브러리 좌측 트리의 구독 섹션(`yt_tree`)에서 4가지 사용성 문제를 개선한다.

1. **전체 구독 피드에 채널명이 안 보임.** yt-dlp 플랫 추출(`fetch_subscription_feed`)이 항목별 `uploader`/`channel`을 채우지 않아 카드 채널명이 빈다. 반면 개별 채널 피드는 채널 레벨 fallback이 있어 항상 채워진다 → 비대칭.
2. **"구독 채널" 노드에 펼침 세모가 없음.** 구독 섹션은 `yt_tree`에 있는데 `yt_tree`에만 branch 화살표 스타일을 빼놨다(`library_panel.py:3572`).
3. **개별 채널 영상목록에 채널명이 중복 노출.** 이미 어느 채널인지 아는데 카드마다 채널명을 보여줄 필요가 없다.
4. **"구독 채널" 노드 클릭 시 아무 동작 없음.** 등록된 채널 목록을 아바타·구독자수·영상수와 함께 카드 그리드로 보고 싶다.

## 설계

### ① 전체 피드 채널명 보강 (videos.list 역조회)
- **검증 결과(2026-06-10):** yt-dlp 플랫 추출(`/feed/subscriptions`)은 항목에 채널 정보를 **전혀 주지 않는다**(키: `id, title, url, duration, timestamp, thumbnails`). `channel_id`조차 없어 저장소 backfill만으로는 매칭 불가.
- **실제 수정:** 각 항목의 **영상 ID**로 YouTube Data API `videos.list(part=snippet)`를 50개씩 배치 역조회해 `channelTitle`/`channelId`를 채운다 — `YouTubeApiAdapter.get_videos_channels(video_ids)`.
- `GetSubscriptionFeedHandler`에 `yt_api` 주입(우선) + `IChannelRepository`(미인증 시 channel_id→이름 fallback).
- 파일: `infrastructure/youtube/youtube_api_adapter.py`, `application/library/playlist_queries.py`, `main.py`(와이어링).
- 라이브 검증: 실 production 경로에서 12/12 항목 채널명 복구 확인.

### ② 펼침 세모
- `library_panel.py:3572` — `yt_tree.setStyleSheet(style)` → `branch_style` 적용(로컬 트리와 동일, ▶/▼ 픽스맵 재사용).

### ③ 개별 채널 피드 채널명 숨김
- `_FeedCard.__init__(dto, show_channel=True)` / `_FeedGrid.set_feed(items, show_channel=True)` 파라미터 추가.
- `show_channel=False`면 썸네일 채널 배지(`set_channel`)와 제목 아래 채널명 라벨 둘 다 생략.
- `library_panel`: `self._feed_show_channel` 상태 — `_on_feed_all_selected`=True, `_on_channel_selected`=False, `_on_feed_changed`에서 `set_feed(items, show_channel=...)`.

### ④ 채널 카드 그리드
- **infra** `infrastructure/youtube/youtube_api_adapter.py`: `list_channels(channel_ids) -> list[dict]` — `channels.list(part=snippet,statistics, id=≤50)` 배치. 반환 `{id, title, thumbnail, subscriber_count, video_count}`.
- **dto** `application/library/dtos.py`: `ChannelInfoDTO(channel_id, channel_name, channel_url, thumbnail_url, thumbnail_path, subscriber_count, video_count)`.
- **app** `application/library/playlist_queries.py`: `GetSubscribedChannelInfosHandler` + `Query(channels: list[tuple[id,name,url]])`. API로 보강, 미인증/실패 시 이름만 반환(graceful). 전체 입력 채널을 항상 반환.
- **vm** `gui/view_models/feed_vm.py`: `_start(fetch, on_ok)` 일반화, `channel_infos` 저장 + `channel_infos_changed` 시그널 + `load_channel_infos(channels)`.
- **gui** `gui/panels/feed_panel.py`: `_ChannelCard`(아바타 + 채널명 + 구독자수·영상수, 클릭→channel_url 방출), `_ChannelGrid`(_FeedGrid와 동일 reflow + minimumSizeHint). 아바타 캐시 `channel_<id>.jpg`. 숫자 포맷 `_fmt_views` 재사용.
- **gui** `gui/panels/library_panel.py`: `_VIEW_CHANNELS=5` 추가, `_channel_grid` 빌드. "구독 채널"(`_ITYPE_ROOT`+youtube) 노드 선택 가능화 + 클릭 시 `load_channel_infos(subs)`. 채널 카드 클릭 → 기존 `_on_channel_selected`.
- **wiring** `main.py`: yt_api를 새 핸들러에 주입, 핸들러를 `FeedViewModel`에 주입.

## 검증
- `ruff check`, `pytest tests/gui/`, 그리고 실제 앱 `/verify`(전체 피드 채널명 표시·세모·개별 채널 채널명 숨김·채널 그리드 아바타/카운트).
