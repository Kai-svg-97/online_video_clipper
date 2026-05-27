# DESIGN.md — UI 디자인 가이드

이 문서는 프로젝트의 디자인 언어를 정의한다.
모든 UI 코드는 이 가이드를 준수해야 하며, 색상·간격·컴포넌트 규칙은 반드시 이 문서를 참고한다.

> **코드 참조**: 실제 색상 토큰은 [`gui/themes/tokens.py`](gui/themes/tokens.py) 에 정의된다.
> 하드코딩 금지 — 반드시 `ThemeManager.instance().current()` 를 통해 읽는다.

---

## 1. 색상 시스템

### 1.1 테마 프리셋

| 토큰 | Slate (기본) | Zinc + Indigo | Warm + Gold |
|------|-------------|---------------|-------------|
| `bg_base` | `#0a0a0a` | `#0e1014` | `#0f0e0d` |
| `bg_surface` | `#0d0d0d` | `#111318` | `#131211` |
| `bg_elevated` | `#141414` | `#1c1f26` | `#1e1c1b` |
| `bg_overlay` | `#1e1e1e` | `#252832` | `#2a2624` |
| `border` | `#1a1a1a` | `#1e2230` | `#252220` |
| `border_muted` | `#252525` | `#2d3142` | `#302c28` |
| `text_primary` | `#e0e0e0` | `#e2e8f0` | `#e8e4e0` |
| `text_secondary` | `#888888` | `#94a3b8` | `#9a9290` |
| `text_muted` | `#444444` | `#475569` | `#4a4440` |
| `accent` | `#e0e0e0` | `#6366f1` | `#d4a84b` |
| `accent_hover` | `#ffffff` | `#818cf8` | `#e8be65` |
| `selected_border` | `#e0e0e0` | `#6366f1` | `#d4a84b` |
| `progress_fg` | `#e0e0e0` | `#6366f1` | `#d4a84b` |
| `star_color` | `#d4a84b` | `#f59e0b` | `#d4a84b` |

### 1.2 색상 계층 원칙

```
bg_base (최하단)
  └── bg_surface (패널, 사이드바)
        └── bg_elevated (카드, 입력 필드)
              └── bg_overlay (호버, 활성 상태)
```

- 배경이 깊을수록 더 어두운 레이어
- `accent`는 버튼·선택 테두리·진행바 등 **최소한의 강조 요소**에만 사용
- 텍스트 색상 3단계: `primary` → `secondary` → `muted`

### 1.3 태그 팔레트

태그는 별도의 32색 팔레트(`_TAG_PALETTE`)를 사용한다 (`library_panel.py`).
태그 색상은 `hash(tag_name) % 32` 로 결정론적으로 할당되며, 테마와 무관하게 유지된다.

---

## 2. 타이포그래피

| 용도 | 크기 | 굵기 | 색상 토큰 |
|------|------|------|----------|
| 창 제목 | 13px | 600 | `text_primary` |
| 섹션 레이블 | 9px | 600 | `text_muted` (대문자) |
| 본문 / 카드 제목 | 12px | 500 | `text_primary` |
| 메타데이터 | 11px | 400 | `text_secondary` |
| 뱃지 / 시간 | 9–10px | 400 | `text_secondary` |
| 태그 칩 | 10px | 400 | (팔레트 색상) |

- 폰트 패밀리: `"Segoe UI", system-ui, sans-serif`
- 줄 간격: 1.4 (본문), 1.2 (카드 제목)

---

## 3. 간격 시스템

4px 그리드 기반.

| 이름 | 값 | 사용처 |
|------|----|--------|
| `xs` | 4px | 아이콘 내부 패딩, 뱃지 |
| `sm` | 8px | 버튼 패딩, 입력 필드 패딩 |
| `md` | 12px | 카드 내부 패딩, 섹션 간격 |
| `lg` | 16px | 패널 패딩 |
| `xl` | 24px | 섹션 제목 여백 |

---

## 4. 컴포넌트 규칙

### 4.1 버튼

- **아이콘 전용 버튼**: 32×32px (사이드바), 28×28px (패널 내)
- **텍스트 버튼**: 불가피한 경우에만 사용, 레이블은 간결하게
- `accent="true"` 프로퍼티 설정 시 액센트 색상 버튼으로 렌더링
- hover 시 `bg_overlay` 배경

### 4.2 카드 (영상 썸네일 그리드)

- 배경: `bg_elevated`
- 테두리: 1px `border_muted`, `border-radius: 6px`
- 선택 시: 1px → 2px `selected_border`
- 시청완료: `text_secondary` 텍스트, `opacity: 0.6`
- 즐겨찾기 별: `star_color`

### 4.3 태그 칩

- `border-radius: 12px` (pill 형태)
- 폰트: 10px
- 배경: 팔레트 색상 (반투명)
- hover: 삭제 표시

### 4.4 사이드바 (`_SideBar`)

- 너비: 48px 고정
- 배경: `bg_surface`
- 우측 테두리: 1px `border`
- `_NavButton`: 32×32px, 활성 시 `bg_overlay` 배경 + 좌측 2px `accent` 선

### 4.5 URL 입력 바 (`_UrlBar`)

- 높이: 36px
- 배경: `bg_surface`
- 하단 테두리: 1px `border`
- 입력 필드 최대 너비: 480px

### 4.6 다운로드 상태바 (`_DownloadBar`)

- 높이: 28px (활성 다운로드 없을 시 숨김)
- 배경: `bg_surface`
- 상단 테두리: 1px `border`
- 진행바: 3px, `progress_fg`

---

## 5. 아이콘 규칙

- SVG 아이콘 인라인 사용 (외부 파일 없음, Qt SVG 렌더링)
- 색상: `QIcon`이 아닌 QPainter/QSvgRenderer로 직접 렌더링 시 `text_secondary` 사용
- 아이콘 크기: 16×16px (버튼 내부), 20×20px (강조 아이콘)
- 스트로크 너비: 1.5–2px

---

## 6. 인터랙션 패턴

| 동작 | 트리거 |
|------|--------|
| 영상 상세보기 열기 | 더블클릭 또는 Enter |
| 상세보기 닫기 | Esc 키 또는 좌상단 `‹` 버튼 |
| 카테고리 추가 | 카테고리 트리 우클릭 메뉴 |
| 브라우저에서 열기 | 우클릭 메뉴 또는 프리뷰 아이콘 버튼 |
| 즐겨찾기 토글 | 우클릭 메뉴 또는 카드 별 아이콘 클릭 |
| 카테고리 이동 | 우클릭 메뉴 또는 드래그앤드롭 |
| 시청완료 표시 | 우클릭 메뉴 |
| 태그 추가 | 프리뷰 패널 태그 입력 필드 |
| 삭제 | 우클릭 메뉴 |
| URL 추가 | URL 바에 붙여넣기 + Enter (클립보드 자동감지) |

---

## 7. 테마 전환

- 설정 패널(`SettingsPanel`) 내 **테마 섹션**에서 프리셋 카드 클릭
- `ThemeManager.instance().apply(name)` 호출 → `QApplication.setStyleSheet()` 즉시 적용
- 커스텀 위젯은 `ThemeManager.instance().theme_changed` 시그널에 연결해 `update()` 또는 `setStyleSheet()` 재호출
- 선택한 테마는 `data/config.yaml`에 저장 → 재시작 후에도 유지

---

## 8. 금지 사항

- ❌ 색상 하드코딩 (`#ffffff`, `#182430` 등) — 반드시 토큰 사용
- ❌ `QListWidget` 사용 (썸네일 그리드) — `QListView + QAbstractItemModel` 필수
- ❌ 텍스트 레이블이 있는 버튼 남발 — 아이콘만 사용하거나 우클릭 메뉴로 이동
- ❌ 설명 없는 아이콘 — 반드시 `setToolTip()` 설정
