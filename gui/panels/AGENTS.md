<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-06-20 | Updated: 2026-06-20 -->

# gui/panels

## Purpose
앱의 각 기능 화면을 구현하는 패널 모음. `MainWindow`의 스택 위젯에 교체되며 표시된다.
가장 복잡한 `library_panel.py`(~5000줄)가 핵심이며, 분할 리팩터링 검토 대상이다.

## Key Files

| File | Description |
|------|-------------|
| `library_panel.py` | 메인 패널 — 썸네일 그리드, 카테고리/재생목록 트리, 상세화면, YouTube 구독 피드/채널 뷰. 단일 클릭→상세, 뒤로/앞으로 히스토리, 연관영상 체인 포함 |
| `video_detail_panel.py` | YouTube 시청 페이지형 상세화면 — 플레이어+제목/메타/태그/챕터/설명+하단 탭(다운로드·메모·클립) + 우측 연관영상(`_RelatedList`) |
| `feed_panel.py` | 피드 카드(`_FeedGrid`·`_FeedCard`)·채널 카드(`_ChannelGrid`·`_ChannelCard`)·`_RoundedThumbLabel`·`_ThumbLoader` 부품 정의 |
| `download_panel.py` | 다운로드 큐 + 완료 이력 탭 |
| `monitoring_panel.py` | 채널 구독 & 모니터링 규칙 관리 |
| `stats_panel.py` | 라이브러리 통계 대시보드 |
| `settings_panel.py` | 전체 설정 패널 (다운로드 경로, 테마 등) |
| `settings_dialog.py` | 간략 설정 다이얼로그 (레거시, 42줄) |

## For AI Agents

### Working In This Directory
- **모든 GUI 파일 수정 후 `/verify` 스킬 실행 필수**.
- `library_panel.py` 수정 시 히스토리 내비게이션(`_push_nav_state`, `_go_back`, `_go_forward`, `_restore_screen`) 로직 주의 — `_capture_screen` 스냅샷이 kind+payload를 저장.
- `feed_panel.py`의 `_ThumbLoader`·`_RoundedThumbLabel`는 `library_panel`과 `video_detail_panel`에서도 재사용.
- `QSplitter`로 가시성 토글 시 레이아웃 thrash → 프리징 발생 — 일반 세로 레이아웃 사용.
- 태그 섹션(`_tag_section`)은 카테고리 선택 시에만 표시 (`_set_popular_tags_visible`).
- 트리 노드 클릭 시 상세 화면이면 먼저 목록으로 복귀 (`_leave_detail_if_open`).

### Navigation State Machine
```
_nav_history (뒤로) ←─ _push_nav_state ─→ _nav_future (앞으로)
                           ↓ _capture_screen
                     {kind, payload, scroll_pos, selected_ids}

kind values: "category" | "playlist" | "folder" | "feed_all" | "channel" | "channels_root"
```

### Testing Requirements
- `tests/gui/test_smoke.py` — pytest-qt로 패널 초기화 확인.

## Dependencies

### Internal
- `gui/view_models/` — LibraryViewModel, PlaylistViewModel, FeedViewModel 등
- `gui/widgets/video_player.py` — InlinePlayer
- `gui/panels/feed_panel.py` — _ThumbLoader, _RoundedThumbLabel (재사용)

<!-- MANUAL: -->
