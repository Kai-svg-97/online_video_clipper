"""라이브러리 화면 공용 상수 — 뷰 인덱스·MIME·아이템 롤·크기·색.

여러 부품이 함께 쓰는 값이라 한곳에 모은다. 여기에는 **로직이 없다** — 상수만 둔다
(부품끼리 서로를 임포트하지 않고 이 모듈만 바라보게 해서 순환 참조를 막는다).
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import (
    Qt,
)

from config.settings import THUMBNAIL_HEIGHT, THUMBNAIL_WIDTH

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Thumbnail size constants (per view type)
# ------------------------------------------------------------------
_TW_ICON = THUMBNAIL_WIDTH     # 320


_TH_ICON = THUMBNAIL_HEIGHT    # 180


_TW_LIST = 213                 # 16:9 at list row size


_TH_LIST = 120


_TW_PREV = 300


_TH_PREV = 169


# Icon-grid card metrics
_ICON_TEXT_H = 90  # px below thumbnail: title(2) + channel + views/time


_ICON_PAD    = 8   # horizontal padding inside card


_MIME_VIDEO_ID        = "application/x-video-id"


_MIME_CAT_ID          = "application/x-category-id"


_MIME_PLAYLIST_ID     = "application/x-playlist-id"


_MIME_PLAYLIST_SECTION = "application/x-playlist-section"


_MIME_YT_PLAYLIST_ID  = "application/x-yt-playlist-id"


_CAT_PARENT_ROLE = Qt.ItemDataRole.UserRole + 100  # parent_id on category tree items


_VIEW_ICON   = 0


_VIEW_LIST   = 1


_VIEW_DETAIL = 2


_VIEW_FOLDER = 3   # 폴더 내 재생목록 카드 그리드


_VIEW_FEED   = 4   # 구독 채널/전체 피드 카드 그리드


_VIEW_CHANNELS = 5 # 구독 채널 목록(아바타 카드) 그리드


_VIEW_ALBUMS = 6   # 앨범 자켓 그리드 (정렬 '앨범' 선택 시 — 음악 카테고리 전용)


# _nav_stack 페이지 — 0=목록 컨테이너, 1=영상 상세, 2=앨범 상세
_NAV_ALBUM_DETAIL = 2


# 검색어 입력 디바운스(ms) — 입력이 멎은 뒤 한 번만 조회한다.
_SEARCH_DEBOUNCE_MS = 300


# 추천 영상 자동 갱신 디바운스(ms) — 검색보다 훨씬 무거운 네트워크 조회라 길게 둔다.
_RECOMMEND_DEBOUNCE_MS = 900


# 추천 씨앗으로 쓸 영상 수 상한 — 현재 페이지 앞쪽만 봐도 목록 성격은 충분히 드러난다.
_RECOMMEND_SEED_LIMIT = 20


# 추천 후보 개수 (가로 스트립이라 너무 많으면 스크롤만 길어진다)
_RECOMMEND_COUNT = 18


# 추천 스트립이 아래에서 올라오는 연출 시간(ms) — 첫 노출에만 재생한다.
_RECOMMEND_REVEAL_MS = 280


# QWIDGETSIZE_MAX — 애니메이션이 끝나면 maximumHeight를 원래대로 되돌린다.
_QWIDGET_MAX_H = 16_777_215


# 상세화면 우측 아래에 붙일 추천 영상 수 (세로 목록이라 스트립보다 적게)
_DETAIL_RECOMMEND_COUNT = 12


_TAG_COUNT_W = 28   # width reserved for the count badge in tag chips (also the delete hit area)


# 32 visually distinct, dark-background-friendly colors for active tag chips.
# Assigned deterministically by hash(tag_name) % 32 so each tag always gets the same color.
_TAG_PALETTE: tuple[str, ...] = (
    "#1a6b8a", "#8b2252", "#2a7a3b", "#6b3d9a",
    "#b5451b", "#1a5276", "#0d7377", "#7a4430",
    "#5d3a9b", "#1e7a44", "#7d2e68", "#2e6b8a",
    "#6b2d2d", "#2a6b4a", "#3a4d8a", "#7a4e2d",
    "#1a7860", "#6b4a8a", "#4a6b2a", "#8a3a5d",
    "#2a5c8a", "#5c3a8a", "#8a5c1a", "#1a6b55",
    "#6b1a3a", "#3a6b1a", "#8a4a1a", "#1a4a6b",
    "#6b6b1a", "#448444", "#8a1a6b", "#148484",
)


# 검색 일치 속성 배지 라벨 — 도메인은 영어 키를 쓰고 표시 문자열은 GUI가 갖는다.
MATCH_FIELD_LABELS: dict[str, str] = {
    "title": "제목",
    "tags": "태그",
    "description": "설명",
    "notes": "메모",
    "summary": "요약",
    "song": "노래",
    "lyrics": "가사",
}


# 검색 일치 속성 배지 한 줄 높이(항상 확보해 타이핑 중 리플로우 방지)
_MATCH_ROW_H = 18


# "영상 없음"(count == 0) 경고 뱃지 색 — 상태를 뜻하는 의미 색이라 테마와 무관하게 고정한다.
_BADGE_EMPTY_BG = "#b03030"


# YouTube 섹션 강조색 — 브랜드 색이라 테마와 무관하게 유지한다. 밝은 배경에서도 읽히도록
# 기존 #ff7070(밝은 회색 배경 위 대비 부족)보다 진한 톤을 쓴다.
_YT_BRAND_RED = "#d32f2f"


_YT_BRAND_RED_HOVER = "#f04438"


# 캐시 키에 렌더 크기(아이콘 그리드 / 리스트 / 상세뷰 3종)가 포함되므로,
# "썸네일 LRU 최대 100개" 규칙은 *렌더 크기당* 100개를 의미한다.
# 따라서 전체 상한은 LRU_THUMBNAIL_MAX × 렌더 크기 종류 수.
_THUMB_RENDER_SIZE_KINDS = 3


_FAV_BADGE_W = 32   # count badge width in _FavoritesBar


_PLAYLIST_ID_ROLE = Qt.ItemDataRole.UserRole + 200


_FOLDER_ID_ROLE   = Qt.ItemDataRole.UserRole + 201


_ITEM_TYPE_ROLE   = Qt.ItemDataRole.UserRole + 202  # "root" | "folder" | "playlist" | "category" | "channel" | "feed_all"


_SECTION_ROLE     = Qt.ItemDataRole.UserRole + 203  # "local" | "youtube"


_CAT_ID_ROLE      = Qt.ItemDataRole.UserRole + 204  # category UUID


_CHANNEL_URL_ROLE = Qt.ItemDataRole.UserRole + 205  # 구독 채널 URL


_ORIG_TEXT_ROLE   = Qt.ItemDataRole.UserRole + 299  # 스피너 중 원본 텍스트 보존


# 그리기 전용 롤 — _TreeRowDelegate가 읽는다. 항목 텍스트를 파싱하지 않기 위해
# 팩토리가 이름·개수·글리프·색을 따로 심는다(스피너가 setText로 텍스트를 변형하므로).
_NAME_ROLE  = Qt.ItemDataRole.UserRole + 300   # 아이콘·개수 없는 순수 이름


_COUNT_ROLE = Qt.ItemDataRole.UserRole + 301   # int | None


_GLYPH_ROLE = Qt.ItemDataRole.UserRole + 302   # "category" | "folder" | "playlist" | "channel" | "feed" | "group"


_COLOR_ROLE = Qt.ItemDataRole.UserRole + 303   # 카테고리 색상 점 (#rrggbb | None)


_STAR_ROLE  = Qt.ItemDataRole.UserRole + 304   # bool — 즐겨찾기


_ITYPE_ROOT     = "root"


_ITYPE_FOLDER   = "folder"


_ITYPE_PLAYLIST = "playlist"


_ITYPE_CATEGORY = "category"


_ITYPE_CHANNEL  = "channel"    # 구독 채널 노드 (클릭 시 채널 영상 피드)


_ITYPE_FEED_ALL = "feed_all"   # 전체 구독 피드 노드


# URL 드롭 대상 판정용 sentinel — cat_id는 None("미분류로 등록")이 유효한 값이라
# 실패를 None으로 표현할 수 없다.
_NO_URL_TARGET = object()
