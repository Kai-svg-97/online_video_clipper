# 밝은 테마 전환 · 불필요 아이콘 제거 · 카테고리 트리 재설계 설계

작성일: 2026-07-28

## 배경

화면 전체가 너무 어둡고 레이어(창 배경 / 패널 / 카드)가 서로 구분되지 않는다.

실제 앱을 각 팔레트로 렌더링해 픽셀을 측정한 결과, 원인이 확인됐다.

| 지점 | slate (현재 기본값) |
| --- | --- |
| 좌측 내비바 · 트리 패널 | `#0a0a0a` (`bg_base`) |
| 콘텐츠 카드 · 검색바 | `#141414` (`bg_elevated`) |

`bg_base #0a0a0a` → `bg_surface #0d0d0d` → `bg_elevated #141414`로 **계층 간 차이가 3~7단위**뿐이다.
배경 계층 자체는 테마 토큰을 정상적으로 따르므로, 문제는 구조가 아니라 **팔레트의 계층 대비 부족**이다.

다만 태그·카테고리 칩은 `paintEvent`에서 QPainter로 직접 그려 네 테마에서 모두 `#2a3a4a`로 고정됐다.
밝은 테마로 바꾸면 이 칩들만 어두운 얼룩으로 남는다.

## 결정 사항 (확정)

| 항목 | 결정 |
| --- | --- |
| 팔레트 | **`mist`** (밝은 중간 톤) 신규 추가 후 기본값으로 지정 |
| 기존 테마 | 6종(slate/zinc/warm/cloud/rose/sand) 모두 유지 — 설정에서 선택 가능 |
| 아이콘 제거 | 사이드바 상단 `▶` 로고 + 좌측 계정(인증) 버튼 |
| 트리 | **모양만 전면 재설계.** 동작 코드는 한 줄도 수정하지 않는다 |

## 1. 팔레트 — `mist`

```python
MIST = ThemeTokens(
    name="mist", display_name="Mist",
    bg_base="#d9dee6",      # 창 전체
    bg_surface="#e7ebf1",   # 패널·사이드바
    bg_elevated="#f8fafc",  # 카드·입력
    bg_overlay="#c9d2dd",   # 호버·활성
    border="#aab6c5", border_muted="#c4cdd9",
    text_primary="#121a25", text_secondary="#4d5c70", text_muted="#8290a2",
    accent="#2563eb", accent_hover="#1d4ed8",
    selected_border="#2563eb", progress_fg="#2563eb",
    badge_bg="rgba(0, 0, 0, 0.55)", star_color="#b45309",
    text_on_accent="#ffffff",
)
```

계층 간 차이를 12~18단위로 벌려 경계가 눈에 보이게 한다. 순백(`#ffffff`)이 아닌 `#f8fafc`를
카드에 쓰고 배경을 `#d9dee6`으로 살짝 눌러, 완전한 화이트 테마보다 장시간 사용에 눈 부담이 적다.

`DEFAULT_PRESET`을 `"mist"`로 변경한다. `config.yaml`에 이미 `theme`가 저장된 기존 사용자는
그 값이 유지되므로 영향받지 않는다 — 신규 설치와 미설정 사용자만 `mist`로 시작한다.

### 하드코딩 칩 토큰화

QSS를 거치지 않고 `QPainter`로 직접 칠하는 두 지점을 토큰 기반으로 바꾼다.

| 위치 | 현재 | 변경 |
| --- | --- | --- |
| `library_panel.py:1012` `_TagChip.paintEvent` | 미선택 `#2a3a4a` | `bg_elevated` 채움 + `border_muted` 1px 테두리 |
| `library_panel.py:1208` `_TagChipDelegate.paint` | 선택 `#1a4f82` / 미선택 `#2a3a4a` | 선택 `accent` / 미선택 위와 동일 |

두 위젯은 `ThemeManager.instance().current()`로 토큰을 읽고 `theme_changed`를 구독해 재도색한다.

카테고리·태그 구분용 색상 팔레트 약 40종(`#8b2252`, `#6b3d9a` 등)은 **항목을 식별하는 데이터
색상이므로 유지**한다. 어두운 톤이지만 밝은 배경 위의 점·칩 채움으로는 오히려 대비가 좋다.

## 2. 아이콘 제거

`gui/main_window.py`에서 세 부분을 삭제한다.

1. **상단 `▶` 로고** (`_SideBar._build_ui`, 211~215행) — `QLabel("▶")` 생성과 `addWidget` 호출.
   상단 여백은 레이아웃 `contentsMargins`가 그대로 유지한다.
2. **계정 버튼** (233~236행) — `_account_btn`. 클릭 동작이 `_navigate(_PAGE_SETTINGS)`로
   바로 아래 기어 버튼과 **완전히 동일**해 기능 손실이 없다.
3. **`update_account_status()`** (247~250행) — `_account_btn`만 참조하는 메서드이며
   프로젝트 전체에서 **호출하는 곳이 없다**(grep으로 확인). 버튼과 함께 삭제한다.

`_SVG_ACCOUNT` 상수도 다른 사용처가 없으면 함께 제거한다.

## 3. 카테고리 트리 재설계

### 유지되는 것

`_PlaylistTree`(`library_panel.py:1408~2779`, 약 1,370줄)의 시그널 28개, 드래그&드롭,
컨텍스트 메뉴, 구독 노드, 로딩 스피너, 스냅샷 선택 복원은 **수정하지 않는다.**
변경은 그리기 계층에만 한정한다.

### (a) 데이터 롤 도입

현재 항목의 시각 정보가 한 문자열에 뭉쳐 있다.

```python
label = f"🏷  {name}  ({video_count})" if video_count > 0 else f"🏷  {name}"
```

델리게이트가 이 문자열을 파싱하는 방식은 두 가지 이유로 깨진다.

- 스피너가 `item.setText(0, f"{orig}  {frame}")`로 텍스트 뒤에 `⠋`를 덧붙인다.
- 카테고리 이름 자체에 괄호가 들어갈 수 있다.

따라서 `_make_*` 팩토리에서 별도 롤을 함께 심고 델리게이트는 롤만 읽는다.

```python
_NAME_ROLE  = Qt.ItemDataRole.UserRole + 300   # 아이콘·개수 없는 순수 이름
_COUNT_ROLE = Qt.ItemDataRole.UserRole + 301   # int | None — 영상 개수
_GLYPH_ROLE = Qt.ItemDataRole.UserRole + 302   # "category" | "folder" | "playlist" | "channel" | ...
_COLOR_ROLE = Qt.ItemDataRole.UserRole + 303   # 카테고리 색상 점 (str | None)
```

팩토리가 유일한 작성자라 변경 범위가 좁다. **기존 `setText(0, ...)` 라벨은 그대로 유지**한다 —
툴팁·스피너·`find_item_by_*` 탐색이 계속 동작해야 하고, 롤이 비어 있을 때 델리게이트가
텍스트로 폴백할 수 있어야 한다.

### (b) `_TreeRowDelegate`

`QStyledItemDelegate`를 상속해 행을 새로 그린다.

- **둥근 pill 행** (radius 6), 좌우 3px 여백
- **호버** `bg_overlay`, **선택** accent 14% 알파 틴트 + accent 텍스트
  (현재의 거친 2px 좌측 보더를 없앤다)
- **행 높이 30px** (`sizeHint`, 현재 약 22px)
- **개수는 우측 정렬 pill 뱃지** — 인라인 `(3)` 대신 `bg_overlay` 채움 + `text_secondary` 9pt
- **카테고리는 8px 색상 점** — `🏷` 이모지 대신 `_COLOR_ROLE` 값을 쓴다
- **즐겨찾기 ★** — 이름 오른쪽에 `star_color` 작은 별 (현재는 글자색만 바뀜)
- **`_ITYPE_ROOT` 행은 굵은 그룹 행**으로 — 이름을 `text_primary` bold로 하고 pill 배경은 생략하되
  **셰브론과 선택 동작은 그대로 유지**한다

> **루트 노드에 대한 확인 결과.** `_PlaylistTree`는 `section="local"`과 `section="youtube"`
> 두 인스턴스로만 생성되므로(`library_panel.py:2843`, `:2888`), `_make_root("로컬"/"YouTube")`를
> 호출하는 `_load_both_sections`는 **현재 UI에서 실행되지 않는 죽은 경로**다.
> 트리에 실제로 나타나는 `_ITYPE_ROOT` 행은 YouTube 트리의 `📡 구독 채널`(`:1645`) 하나뿐이며,
> 이 노드는 **자식을 가지고 클릭도 되는**(채널 그리드 열기) 항목이다. 따라서 셰브론을 없앤
> "섹션 라벨"로 만들면 펼침이 불가능해져 기능이 깨진다 — 굵은 그룹 행으로 처리한다.
>
> 화면의 "로컬" / "YouTube" 헤더는 트리 행이 아니라 `_PlaylistPanel`의 `QPushButton`
> (`local_hdr` `:2829`, `_yt_bar`)이다. 이 두 버튼은 QSS로 스타일링되므로 팔레트를 따라가지만,
> 새 트리 모양과 톤을 맞추기 위해 자간·색을 함께 조정한다.

### (c) 셰브론·들여쓰기 가이드는 `drawBranches()`로

이 부분이 핵심 기술 판단이다. 셰브론을 델리게이트가 **아이템 영역**에 그리면
**클릭해도 펼쳐지지 않는다** — `QTreeView`는 branch 영역의 클릭만 확장/축소로 처리한다.

따라서 `QTreeWidget.drawBranches(painter, rect, index)`를 오버라이드해 branch 영역에 직접 그린다.
네이티브 클릭 히트테스트가 그대로 유지되므로 펼침 동작에 손을 댈 필요가 없다.

- 셰브론 `▸`/`▾`을 `text_muted`로, 자식이 있는 항목에만
- 깊이별 1px 세로 가이드선을 `border_muted`로 — 계층을 화살표에 의존하지 않고 읽히게 한다
- 네이티브 인디케이터는 QSS `QTreeWidget::branch { image: none; }`로 숨긴다

## 검증

- **회귀 확인 대상**(그리기 변경이 동작을 깨지 않았는지): 노드 펼침/접힘, 카테고리 선택,
  드래그&드롭(재생목록↔폴더, 영상→카테고리), 컨텍스트 메뉴, 즐겨찾기 표시, 로딩 스피너,
  뒤로가기 스냅샷 복원
- **시각 확인**: 실앱을 띄워 before/after 스크린샷을 찍어 비교한다
  (`scratchpad/theme_preview.py`가 `app.exec`를 가로채 `MainWindow`를 PNG로 캡처한다)
- `pytest tests/` 전체 — 기존 `tests/gui/test_smoke.py` 3건은 main에도 있는 기존 실패이며
  이번 작업과 무관하다(작업 전 main에서 재현 확인함)
- GUI 변경이므로 `/verify`로 실앱 기동을 확인한다

## 문서 갱신 (CLAUDE.md 필수 규칙)

- `CLAUDE.md` — `gui/themes/tokens.py` 설명에 `mist` 기본값 명시,
  `library_panel.py` 설명에 `_TreeRowDelegate`·`drawBranches`·신규 롤 추가,
  `main_window.py` 설명에서 계정 버튼 제거 반영
- `planning/youtube_content_manager_prd.md` — UI/UX 개선 항목 추가
