# 라이브러리·검색·가져오기·구독

> 추천·검색·로딩 표시·무한 스크롤·가져오기/내보내기·북마크·저장된 검색·워치 폴더·구독 감시.
> 색인: [`../design-decisions.md`](../design-decisions.md).

## 항목별 기록

- **추천 영상 스트립 (목록 아래 접이식)** — 지금 보고 있는 목록과 관련 있을 만한 영상을
  목록 아래 가로 띠로 나열하고, 좌측 카테고리 트리로 **드래그해 바로 담게** 한다.
  **관련 영상을 API로 받을 수 없다**: YouTube Data API v3의
  `search.list(relatedToVideoId=)`는 2023-08-07에 제거됐고 yt-dlp도 관련 영상을 주지 않는다.
  그래서 `domain/library/recommendation.py:derive_seed_queries`가 현재 목록의
  **제목 대표 키워드(문서빈도 기준)→최다 태그→최다 채널** 순으로 검색어를 최대 3개 만들고,
  `GetRecommendationsHandler`가 `IMediaSource.fetch_search_videos`(yt-dlp `ytsearchN:`)로
  후보를 모은다. **검색은 쿠키·API 키가 없어도 동작**하므로 미인증 사용자도 추천을 받는다
  (조회수·게시일은 YouTube API가 있으면 `get_videos_channels`로 보강). 검색어 파생을 도메인
  순수 함수로 뺀 이유는 추천 품질이 조용히 나빠지는 회귀를 테스트로 못박기 위함이다
  (`tests/unit/domain/test_recommendation.py`). **이미 라이브러리에 있는 영상은 결과에서
  제외**한다(목적이 '아직 없는 영상 담기'). 검색어별 실패는 격리해 나머지 검색어로 계속한다.
  반환형은 피드와 같은 `FeedVideoDTO`라 카드 렌더링(`_FeedCard`)을 공유한다.
  **검색창에 낱말이 입력돼 있으면 짐작을 그만두고 그 낱말의 YouTube 검색 결과로 스트립을
  채운다** — 사용자가 이미 무엇을 찾는지 말했으므로 목록에서 검색어를 뽑을 이유가 없고,
  뽑은 검색어를 섞으면 그 키워드와 무관한 후보가 함께 올라온다. 분기는 **검색어를 정하는
  한 곳**(`derive_seed_queries(search_text=…)`)에만 두고, `GetRecommendationsQuery.search_text`
  → `RecommendViewModel.load(search_text=…)`로 흘린다(두 경로가 갈라지면 "목록엔 검색어대로인데
  스트립은 딴 것"이 된다). GUI(`_refresh_recommendations`)는 검색 모드에서 **씨앗을 넘기지
  않는다** — 넘기면 목록이 바뀔 때마다(스트립에서 한 건 담기만 해도) 캐시 키가 달라져 같은
  검색을 다시 돌린다. 또 이때는 **로컬 결과가 0건이어도 조회한다**(검색 결과가 없을 때가
  오히려 'YouTube에는 뭐가 있나'를 가장 보고 싶은 순간이다 — 목록 기반 추천의
  "목록이 비어 있어 추천할 기준이 없습니다" 가드를 검색 모드에는 걸지 않는다).
  헤더 제목(`RecommendStrip.set_title`)이 `"<검색어>" YouTube 검색 결과`로 바뀌어 지금 뜬
  카드가 무엇인지 알려 주고, 검색어를 지우면 기본 제목·목록 기반 추천으로 돌아온다.
  회귀 테스트: `tests/gui/test_recommend_panel_wiring.py`(`TestSearchKeywordStrip`·
  `TestCollapsedStripSearchOverride`·`TestViewModelSearchText`),
  `tests/integration/test_recommendations.py`,
  `tests/unit/domain/test_recommendation.py`.
  **드롭 경로는 새로 만들지 않았다**: 카드 드래그가 `text/uri-list`+`text/plain`으로
  브라우저 URL 드래그와 동일한 MIME을 만들고, `_PlaylistTree`에 URL 드롭 처리를 추가해
  (`_url_drop_target` → `url_dropped(url, cat_id)` → `LibraryPanel._on_url_dropped` →
  `_vm.add_video(url, cat_id)`) 기존 등록 경로를 그대로 탄다. 대상 판정에 sentinel
  `_NO_URL_TARGET`을 쓰는 이유는 `cat_id=None`이 '미분류로 등록'이라는 **유효한 값**이라
  거부와 구분해야 하기 때문이다. 카테고리 노드와 **로컬 루트**만 대상으로 인정한다
  (YouTube 루트·채널·재생목록 노드는 거부). 부수 효과로 구독 피드 카드도 드래그 가능해졌다
  (`_FeedGrid`가 `draggable=True`로 카드를 만든다). 자동 갱신은 900ms 디바운스이고
  **접혀 있으면 조회하지 않는다** — 기본값은 펼침(`RECOMMEND_STRIP_EXPANDED`)이지만
  접어 두면 네트워크 조회가 완전히 멈춘다. **예외는 검색 결과가 0건일 때 하나뿐이다**
  (`_search_needs_recommendations`): 검색어는 있는데 로컬 결과가 없으면 화면에 아무것도
  남지 않아 헤더 바만 있는 접힌 스트립이 '결과 없음'과 구분되지 않는다 — 사용자가 이미
  무엇을 찾는지 말했으므로 `_apply_search_expand`가 스트립을 **임시로 펼쳐**(설정값은
  건드리지 않는다 — `set_expanded(notify=False)` + `_sync_recommend_sizes(save=False)`)
  그 낱말의 YouTube 결과를 채운다. 검색어를 지우거나 결과가 생기면 원래 접힘으로
  되돌리며 **그때 카드·헤더 제목도 함께 비운다** — 남겨 두면 나중에 사용자가 직접 펼쳤을
  때 `count() > 0`이라 재조회가 걸리지 않아, 지운 검색어의 결과가 '추천 영상'이라는 제목으로
  그대로 남는다. 사용자가 직접 토글하면(`_on_recommend_expanded`) 임시 펼침에서 손을 뗀다
  (직접 조작이 우선이다). 검색 0건 안내판(`_refresh_list_overlay`)도 "아래 '추천 영상' 띠에
  이 낱말의 YouTube 검색 결과를 채웁니다"로 스트립을 가리켜, 목록만 보고 있던 사용자가
  결과를 놓치지 않게 한다.
  **목록이 다 준비되기 전에는 스트립을 감춘다**(`LibraryPanel._recommend_ready`) — 조회 중인
  빈 띠가 미리 자리를 차지하지 않도록, 최종 결과(`items_changed`)가 와야 노출한다.
  **부분 결과(`partial_ready`)는 채워만 두고 노출하지 않는다.** 노출은 `_animate_recommend_in`이
  높이를 0→목표로 키워 아래에서 밀려 올라오듯 보이게 하는데, **`setSizes`만으로는 0에서 시작할
  수 없어**(스플리터가 자식의 `minimumSizeHint`를 최소로 삼는다) `maximumHeight`를 애니메이션한다
  — `qSmartMinSize`가 최소 크기를 `maximumSize`로 잘라 주기 때문에 최소 높이까지 함께 눌린다.
  끝나면 `_QWIDGET_MAX_H`로 되돌려 핸들 조절을 막지 않는다.
  **새 조회가 시작되면(카테고리 전환·검색·⟳) `_hide_recommend_strip`이 다시 아래로 접어
  감춘다** — 씨앗이 통째로 달라져 걸려 있던 카드는 새 목록과 무관한데, 그대로 두면 '이미
  준비된 추천'처럼 보인다. 접기 직전의 높이를 `_recommend_height`에 담아 두었다가 다시
  올라올 때 복원하고, 접히는 중에 결과가 도착하면 `_animate_recommend_in`이 **그 높이에서
  이어 올라간다**(0으로 튀지 않게). **결과가 없거나 실패해도, 추천 뷰모델이 없어도
  헤더 높이만큼은 띄운다** — 완전히 숨기면 ⟳(다시 받기)·접기 토글·안내 문구에 닿을 방법이
  사라진다. 같은 이유로 **접힌 상태로 시작하면 처음부터 헤더 바를 보여준다**(접혀 있으면 조회를
  안 하므로 노출 조건이 영영 오지 않는다).
  **상세화면 우측 '연관 영상' 목록 아래에도 같은 결과를 나열한다**(`_recommend_related_items()`
  → `VideoDetailWidget.set_recommendations`) — 상세를 열 때마다 따로 조회하지 않고 스트립의
  결과를 재사용한다(추천 뷰모델이 하나뿐이라 별도 조회는 스트립 목록까지 뒤엎는다). 추천은
  **재생목록(`_playlist`)에 넣지 않는다** — 자동 다음곡이 라이브러리 밖 영상으로 새면 안 된다.
  회귀 테스트: `tests/gui/test_recommend_strip.py`
  (접기·드래그 MIME·트리 드롭 대상·실제 드롭 이벤트), `tests/gui/test_recommend_panel_wiring.py`
  (디바운스·접힘 시 미조회·뷰별 숨김·**지연 노출·재조회 시 재감춤·등장/퇴장 애니메이션
  높이**·드롭 배선),
  `tests/gui/test_detail_recommendations.py`(상세 우측 두 구역 분리·재생목록 경계),
  `tests/integration/test_recommendations.py`.
- **라이브러리 밖 영상의 카테고리 지정 (요약·가사 잠금 해제)** — 상세화면 제목 행의 `📁`
  버튼(`VideoDetailWidget.category_assign_requested`)으로 **어떤 영상이든 카테고리에 담는다**.
  payload는 로컬이면 `video_id`(UUID), 스트리밍(추천·피드)이면 `FeedVideoDTO`이고,
  `LibraryPanel._on_detail_category_requested`가 전자는 `assign_category`(이동), 후자는
  `add_video(url, cat_id)`(등록)로 갈라 처리한다. 등록은 비동기라 **URL을
  `_pending_category_url`에 적어 두고** `video_add_finished`를 기다렸다가
  `_switch_to_local_detail`이 같은 영상의 로컬 상세로 갈아탄다(재생 위치·재생 여부 유지,
  `push_nav=False`라 화면 히스토리를 늘리지 않는다). 이미 라이브러리에 있는 URL을
  스트리밍으로 보고 있었다면 등록 없이 이동만 하고 전환한다.
  **요약·노래 탭은 더 이상 비활성화하지 않는다** — 두 기능은 영상별로 DB에 저장돼
  안정적인 로컬 `video_id`가 필요하지만, 탭을 비활성화하면 클릭조차 되지 않아 *왜* 못 쓰는지
  알릴 방법이 없었다. 이제 탭은 열리고 그 안에 `_LockedNotice`("카테고리에 담으면 …")와
  담기 버튼이 뜬다. 안내판은 `set_info(None)` 같은 갱신에도 유지된다(가사 후보 목록과
  같은 이유 — 되돌리면 설명이 사라진다). 카테고리 선택은 `LibraryPanel._pick_category()`가
  `_CategoryPickDialog`를 띄워 `(확인여부, cat_id)`를 돌려주며 추천 카드 우클릭 경로와 공유한다
  (`selected_id`는 **메서드**다 — 괄호를 빠뜨리면 바운드 메서드가 카테고리 id로 넘어가
  등록이 실패한다. 실제로 그 버그가 있었다). 회귀 테스트:
  `tests/gui/test_detail_category_assign.py`.
- **브라우저 URL → 카테고리 트리 드롭** — 드롭 판정은 **매 이벤트에서 MIME으로 다시 계산**한다
  (`_PlaylistTree._is_url_drag`). 예전엔 `dragEnterEvent`가 세운 `_ext_url_drag` 플래그에만
  의존해, 진입 이벤트를 놓치거나 중간에 `dragLeave`가 끼면 드롭이 **아무 반응 없이** 무시됐다.
  MIME 후보도 넓혔다: `text/uri-list`·`text/x-moz-url`에 더해 **`text/plain`과 Windows 네이티브
  포맷**(`application/x-qt-windows-mime;value="UniformResourceLocator(W)"`)까지 본다 —
  브라우저·사이트에 따라 dragEnter 시점에 uri-list가 없고 텍스트만 실려 오며, `…LocatorW`는
  **UTF-16LE**라 utf-8로 읽으면 첫 글자만 남는다. 트리는 접힌 채 로드되므로
  (`collapseAll`) 하위 카테고리에 떨구려면 드래그 중 펼침이 필요해
  `setAutoExpandDelay(600)`을 켰다(Qt 기본값은 -1=비활성). 거부된 드롭은 URL·대상·MIME 목록을
  `logger.debug`로 남긴다 — 화면에는 아무 일도 일어나지 않아 사후 진단이 불가능했다.
  회귀 테스트: `tests/gui/test_tree_url_drop.py`.
- **추천 영상 미리 받기(무한 스크롤)** — 스트립이 오른쪽 끝에 **닿기 전**(카드 두 장쯤 앞)
  다음 묶음을 백그라운드로 받아 이어 붙인다. 끝까지 밀고 나서 받으면 빈 공백을 보며
  기다리게 된다. **씨앗을 새로 뽑지 않는다** — `derive_seed_queries`는 목록당 최대 3개
  (제목 키워드·최다 태그·최다 채널)뿐이라 더 뽑을 검색어가 없다. 대신 같은 검색어를
  **더 깊이**(`per_query`를 페이지마다 늘려) 파고 이미 보여 준 URL을 `exclude_urls`로
  걸러 새것만 남긴다. 결과가 하나도 없으면 그 씨앗은 바닥난 것으로 보고 더 요청하지
  않는다(스크롤할 때마다 같은 검색을 반복하면 조용히 네트워크만 축낸다). 추가분 워커는
  **본 조회와 분리**돼 있어 세대(`_gen`)를 올리지 않는다 — 올리면 진행 중인 첫 조회 결과가
  버려진다. 결과가 도착하면 `_more_worker` 자리를 **즉시** 비운다: 스레드가 끝나기를
  기다리면 그 사이 들어온 다음 요청이 '조회 중'으로 오인돼 조용히 버려진다(실제로 이
  경합이 테스트를 간헐 실패시켰다).
- **라이브러리 정리(중복·사라진 파일)** — 중복 판정은 순수 규칙(`domain/library/duplicates.py`):
  **영상 ID로 먼저** 묶고(URL 정규화가 `youtu.be`·`watch?v=`만 합치고 **`/shorts/`는 그대로 두어**
  같은 영상이 두 행으로 들어온다), ID를 모르는 것만 제목+채널로 '비슷함'으로 묶는다.
  같은 것을 두 번 세지 않도록 ID로 묶인 것은 제목 묶기에서 제외한다. application 핸들러는
  **DTO로 바꾼 뒤 판정한다** — 아그리게이트는 값이 `.video.url`처럼 한 겹 안쪽이라 그대로
  넘기면 조용히 빈 결과가 된다(실제로 겪었다). 삭제는 자동으로 하지 않는다.
  회귀 테스트: `tests/integration/test_library_maintenance.py`, `tests/gui/test_library_cleanup_dialog.py`.
- **피드/채널 메타데이터 보강** — yt-dlp `extract_flat`은 구독 피드·채널 영상의 게시일·조회수를 주지 않으므로(영상 ID·길이만), `GetSubscriptionFeedHandler`·`GetChannelVideosHandler`가 YouTube Data API `videos.list`(`get_videos_channels`, part=snippet,statistics,contentDetails)로 `published_at`(ISO)·조회수·길이를 보강한다. 채널 카드의 "최근 영상" 시점은 채널 업로드 재생목록 첫 항목(`get_latest_upload_dates`, 채널당 1쿼터·스레드풀 병렬)으로 구한다. **`_yt_api`(OAuth) 미설정 시 graceful**: 시간 미표시 + 채널은 이름순 정렬.
- **라이브러리 가져오기/내보내기(카테고리 단위 zip 패키지)** — 모은 카테고리·영상·노래 가사/싱크 정보를 다른 사람에게 전달하거나 백업하는 용도. **내보내기**(`ExportLibraryHandler`)는 선택한 카테고리 id를 `list_categories()` 기준으로 하위까지 자동 확장(`_expand_with_descendants`)한 뒤, 그 집합에 속한 영상만 담는다 — **조상이 선택되지 않았으면 패키지 안에서 그 카테고리는 parent_id가 없는 루트로 취급**(가져오는 쪽이 상위 트리를 몰라도 되게). 패키지는 `manifest.json`+`data.json`(categories/videos, 영상마다 `song`(가사 포함) 중첩) + `thumbnails/`로 구성되고 실제 zip 입출력은 `infrastructure/transfer/portable_package.py`(`ILibraryPackageWriter`/`Reader` 포트 구현)가 전담해 application 레이어는 THUMBNAIL_DIR 절대경로를 모른다. **가져오기는 3단계**: `PreviewImportHandler`(패키지의 카테고리 목록+영상 수만 훑어 선택 UI 자료를 만든다, DB에 손대지 않음) → `DetectImportConflictsHandler`(선택된 카테고리의 영상 중 URL이 로컬에 이미 있는 것만 값이 다른 필드를 찾아 보고 — **값이 완전히 같으면 충돌로 보고하지 않는다**) → `ImportLibraryHandler`(실제 반영). **병합 키**: 영상=URL(`get_by_url`), 카테고리=(이름, 로컬로 매핑된 부모) — 패키지 카테고리 id는 그 패키지 안에서만 의미 있는 **문자열**(UUID로 강제 변환하지 않음)이라 부모가 선택 안 된 경우도 자연스럽게 표현된다. **충돌 필드의 기본 선택값**은 한쪽이 비어있고 다른 쪽이 채워져 있으면 채워진 쪽(빈 칸 채우기는 안전하다는 가정), 둘 다 채워져 있으면 기존값 유지(조용한 덮어쓰기 방지) — `ImportFieldDiffDTO.existing_filled`/`incoming_filled`로 GUI가 "(비어있음)" 표시까지 그대로 보여준다. **가사 시각(start_ms) 보존은 `apply_fetched`를 쓰고 `edit_lyrics`를 쓰지 않는다** — `edit_lyrics`는 수동 재입력용이라 줄 수가 바뀌면 시각을 버리는 게 의도된 동작이라(오탈자 수정 보호), 새 아그리게이트(줄 수 0→N)에 쓰면 항상 시각이 날아간다. **태그는 항상 합집합으로 자동 병합**(사용자에게 묻지 않음 — "둘 다 유지"가 항상 안전하므로). 카테고리가 비어있던(미분류) 영상은 가져온 카테고리로 자동 채워지고, 이미 분류돼 있으면 명시적으로 "가져오기"를 고르지 않는 한 유지된다. 설정 패널의 `_ImportExportSection`(`transfer_vm` 주입 시에만 노출)이 다이얼로그 순서(카테고리 선택 → 파일 선택 → 충돌 해결)만 조율하고, 실제 I/O·병합은 전부 `LibraryTransferViewModel`의 QThread 워커가 수행한다. **네 핸들러 모두 완료 시 `logger.info`로 카운트를 남긴다**(내보내기: 카테고리/영상 수+경로, 충돌감지: 새 영상/충돌/완전동일 수, 가져오기: 새 영상/병합/카테고리 수+경로) — 같은 라이브러리로 내보낸 뒤 그대로 다시 가져오면 전 영상이 완전히 동일해 충돌 화면 없이 조용히 병합되는데, 이게 정상 동작인지 오류인지 화면의 작은 상태 문구만으론 구분하기 어려워 실제 문의가 있었다. 로그가 없으면 사후 진단이 불가능하므로 필수로 남긴다.
- **영상 검색 (부분 일치)** — `SqliteVideoRepository._build_search_sql`이 **제목·태그·설명·메모·요약·노래(가수/앨범/제목/발매년도)·가사**를 부분 일치(`LIKE ... ESCAPE ''`)로 덮는다. 과거에는 `videos_fts`(FTS5)가 **제목·메모 두 열만** 덮었다. FTS5 대신 부분 일치를 쓰는 이유: ① 한글은 어미가 붙어 단어 단위 매칭이 자주 빗나간다 ② 어느 속성이 일치했는지 판정이 정확하다 ③ 규모가 작다(영상 수백 건). **가사는 절대 SQL `LIKE`로 다루지 않는다** — `lyrics_json`이 `[{"o":원문,"t":번역}]` 형태라 검색어 `o`·`t`가 JSON 키에 걸려 모든 노래를 오탐한다(회귀 테스트 `tests/integration/test_search_fields.py::TestLyricsJsonFalsePositive`로 고정). 일치 속성은 `match_fields_for(video_ids, text)`가 **현재 페이지 50건에만** 실행해 `MATCH_FIELD_KEYS` 순서로 반환하고, `VideoDTO.match_fields`로 실려 `VideoListModel.MatchFieldsRole`을 거쳐 그리드·리스트 델리게이트가 배지로 그린다(`_paint_match_badges`, 높이 `_MATCH_ROW_H`는 리플로우 방지를 위해 항상 확보). 한글 라벨(`MATCH_FIELD_LABELS`)은 GUI만 갖는다. `LIKE '%...%'`는 인덱스를 타지 않으므로 라이브러리가 수만 건이 되면 통합 FTS 테이블로 되돌리는 것이 맞다. `videos_fts`와 트리거는 `test_merge_applier.py`가 동기화 병합 후 발화를 검증하는 데 쓰므로 **제거하지 않았다**. **가사는 최상위 카테고리가 음악인 영상만 검색한다** — 루트 조상 카테고리 이름이
  `music`·`song`·`음악`·`노래`·`뮤직`(`MUSIC_ROOT_CATEGORY_NAMES`, trim+소문자 비교)일 때만 대상이며
  미분류는 제외한다. 게이트는 `_lyrics_match_ids`(검색 결과)와 `match_fields_for`(배지)
  **양쪽에 똑같이** 걸어야 한다 — 한쪽만 걸면 "가사로 검색됐는데 배지는 없는" 불일치가 난다.
  루트 해석은 재귀 CTE이고 `depth < 32` 가드가 필수다(`categories`에 순환을 막는 제약이
  `UNIQUE(name, parent_id)`뿐이라 데이터가 순환하면 앱이 멈춘다). 부수 효과로 매 검색마다
  전체 가사를 JSON 파싱하던 부담이 줄어든다.
- **검색 입력 응답성 (키 입력이 밀리던 문제)** — 검색창은 **키 입력마다 조회하지 않는다**. `LibraryPanel._on_search_text_changed`가 `_search_timer`(`_SEARCH_DEBOUNCE_MS`=300ms, 단발)만 재시작하고, 멎으면 `_apply_search_text`가 한 번 조회한다. Enter는 즉시, 지우기(빈 문자열)도 즉시 적용한다. 뷰모델 `set_search_text`는 **strip 결과가 같으면 재조회하지 않는다**(IME 조합·뒤 공백). 조회 자체는 예전부터 워커 스레드였지만, 그 뒤에 이어지는 **메인 스레드 작업**이 병목이었다: ① 표(상세) 뷰 `_refresh_table`이 결과가 바뀔 때마다 **행마다 `get_video_detail`**(영상당 여러 쿼리 + 다운로드 파일 `stat`)을 돌렸다 → `GetDownloadedFormatsHandler`(URL 묶음 단일 쿼리, `IDownloadRepository.find_completed_formats_by_urls`)로 대체하고, **표가 실제로 보일 때만** 채운다(숨겨져 있으면 `_table_dirty`로 표시했다가 `_switch_view`에서 지연 갱신). ② 결과가 바뀔 때마다 `_ThumbBgLoader`가 새로 떠 이전 목록의 썸네일 50장을 계속 디코딩했다 → 새 로더를 시작하기 전에 이전 로더를 `cancel()`한다. ③ 가사 후보 조회(`_lyrics_match_ids`)가 **매 검색마다 전체 가사를 JSON 파싱**했다 → `_lyrics_prefilter_safe(text)`일 때 `lyrics_json LIKE`로 후보를 먼저 좁히고(값이 그대로 저장돼 있어 안전 — `ensure_ascii=False`), `"`·`\`·제어문자·대소문자 있는 비ASCII가 섞이면 프리필터를 포기하고 전체 스캔으로 되돌아간다(이 폴백은 `tests/integration/test_search_fields.py::TestLyricsPrefilter`가 고정). `_lyrics_text`는 `lru_cache`로 재파싱을 피한다. 회귀 테스트: `tests/gui/test_search_debounce.py`, `tests/integration/test_downloaded_formats_bulk.py`.
- **목록·검색 로딩 스켈레톤 (v1.22.0 체감 성능 개선 Phase 1 Step 3)** — 카테고리 클릭은
  `loading_key_changed`(노드 키 기준)로 트리 스피너와 "불러오는 중" 안내가 떴지만,
  **검색 조회(`set_search_text`)는 노드 키가 없어 어떤 로딩 신호도 내지 않았다** —
  디바운스 300ms + 쿼리 시간 동안 화면이 낡은 목록을 든 채 아무 말도 하지 않는,
  체감 지연이 가장 큰 경로가 비어 있었다. `LibraryViewModel.loading_changed`
  (bool 시그널)를 추가해 `_run_list`/`_drain_list`가 **노드 키 유무와 무관하게**
  발행하고, 화면 표시는 텍스트 안내 대신 `gui/panels/library/skeleton_list.py`의
  `ListSkeleton`(카드/행 자리를 셰이머 블록으로 먼저 보여줌)으로 교체했다(텍스트와
  스켈레톤이 동시에 뜨면 안 되므로 `overlay.py`는 더 이상 '조회 중'을 그리지 않는다 —
  결과 0건 안내 3종만 남았다). **깊이 카운터(`_list_inflight`)로 겹치는 조회를 관리**한다
  — `_max_workers`(기본 4)로 여러 조회가 동시에 진행될 수 있어, 단순 bool 토글이면
  먼저 끝난 조회가 아직 진행 중인 다른 조회의 스켈레톤을 꺼버린다. 0→1에서만
  `loading_changed(True)`, 1→0에서만 `loading_changed(False)`를 낸다. 캐시 히트
  (`_video_cache` 적중)는 `_run_list`를 거치지 않고 즉시 반환하므로 스켈레톤이 뜨지
  않는다(깜빡임 방지). **트리 노드별 스피너(`loading_key_changed`)는 이 스켈레톤을
  더 이상 직접 켜고 끄지 않는다** — `sidebar.py`의 `_on_local_loading_key_changed`가
  예전엔 `_on_list_loading`을 함께 호출했는데, 겹치는 조회에서 먼저 끝난 노드가
  스켈레톤을 꺼버리는 사고(깊이 카운터를 우회)가 났다. 지금은 트리 스피너 전용으로만
  남았고, 스켈레톤은 오직 `_on_list_loading_any`(`vm.loading_changed` 슬롯)를 통해서만
  켜고 끈다. `ListSkeleton`은 폴더·피드·채널 카드 그리드에서는 뜨지 않는다(아이콘·
  리스트·표 뷰에서만 — 그 화면들은 영상 목록이 아니라 다른 스켈레톤이 필요하면 별도
  담당). 회귀 테스트: `tests/gui/test_library_vm_loading_signal.py`(신호 자체 —
  단일/검색/캐시 적중/겹치는 조회 깊이 안전), `tests/gui/test_list_skeleton.py`
  (`ListSkeleton` 위젯 — 표시/숨김·뷰별 배치·뷰포트 크기별 개수), `tests/gui/test_list_overlay.py`
  (패널 배선 — 스켈레톤과 텍스트 안내가 겹치지 않음, 노드 키 신호가 스켈레톤을 직접 못 끔).
- **등록 시 요약·가사 자동 보강** — **단건 등록**(`LibraryViewModel.add_video`)이 끝나면 `EnrichVideoHandler`(application/library/commands.py)가 `song_info.is_song`을 읽어 한쪽만 채운다: 노래 영상이면 `FetchSongInfoCommand(fetch_lyrics=True)`로 **가사만**(가수·앨범·제목·발매년도는 등록 시 이미 채워졌고 체인은 빈 값만 채우므로 실질적으로 가사만 추가된다), 아니면 `ISummarySource.extract`(=`GeminiExtractor`)로 **요약**(`gemini_summary`)을 채운다. **가사를 못 찾아도 요약으로 폴백하지 않는다.** 이미 값이 있거나 추출기가 미주입이면 `kind="skipped"`로 건너뛴다. 설정 `AUTO_ENRICH_ON_ADD`(기본 ON)로 끌 수 있다. **재생목록·채널 일괄 임포트는 대상이 아니다** — 그 경로들은 `AddVideoHandler`를 직접 호출하고 ViewModel을 지나지 않으므로 자연히 제외되며, Gemini가 영상당 브라우저를 띄워 수십 초 걸리기 때문에 의도된 제외다. 보강은 `_EnrichWorker`(QThread)에서 **동시 1건**으로 직렬화한다(`_pending_enrich` 큐 — 브라우저 병렬 실행 방지). 진행·실패는 `MainWindow` 상태바에 표시하고(`enrich_started`/`enrich_finished`), 완료 시 그 영상 상세가 열려 있으면 `_reload_detail_in_place`로 재로드한다(상세 DTO+노래 정보를 함께 다시 읽어 요약 탭·노래 탭 모두 반영). `ISummarySource`는 `domain/shared/ports.py`의 Protocol이라 application 레이어가 infrastructure를 직접 import하지 않으며, 반환형은 실제 구현에 맞춰 `str | None`(실패 시 falsy)이다. 모든 실패는 `EnrichVideoResult(ok=False)`로 변환돼 등록 결과에 영향을 주지 않는다.

## 라이브러리 무한 스크롤 — 쪽을 넘긴 뒤의 재조회 (v1.27.1)

`LibraryViewModel.load_next_page()`는 처음부터 있었는데 **아무도 부르지 않았다.**
목록 조회가 한 쪽 50개(메모리 규칙)라, 51번째 영상부터는 화면에서 사라져 있었다
(영상 60개로 재현: 첫 화면 50개, 끝까지 내려도 50개).

스크롤 배선 자체는 간단하지만, 붙이고 나서 **없던 함정이 둘 생긴다**.

1. **바닥 근처에서 신호가 연달아 온다.** 호출부가 막아 주기를 기대하면 같은 쪽을
   여러 번 읽어 목록에 중복이 쌓인다 → `load_next_page()`가 스스로 막는다
   (`_has_more`·`_list_inflight`). 화면은 그냥 부르면 된다.
2. **재조회가 쪽 번호를 되돌리지 않는다.** 삭제·태그 변경 등은 `_refresh_videos()`를
   그대로 부르는데, 3쪽까지 내린 상태에서 그러면 `offset=150`으로 조회해 목록이
   151번째부터로 튄다. 무한 스크롤을 붙이기 전에는 `_current_page`가 늘 0이라
   드러나지 않던 결함이다.

2번은 "쪽 번호를 0으로 되돌린다"로 막을 수도 있었지만, 그러면 3쪽까지 내려 둔
사용자가 영상 하나를 지울 때마다 맨 위로 되돌아간다. 대신 **읽어 둔 만큼 통째로 다시
읽는다**(`offset=0, limit=50*(page+1)`). 메모리는 사용자가 스스로 내린 만큼만 는다.

곁가지로 캐시를 손봤다. `_video_cache`는 '첫 쪽'만 담는 구조라, 여러 쪽 분량을 같은
키로 넣으면 크기가 뒤섞인다 → **1쪽을 넘긴 뒤에는 캐시를 쓰지 않는다.**

회귀 테스트: `tests/gui/test_library_pagination.py`.

---

## "지난번 이후"를 날짜로 재지 않는다 (v1.28)

구독 채널 새 영상 감시에서 "지난번 조회 이후에 올라온 것"을 판정해야 한다. 날짜
비교가 자연스러워 보이지만 쓰지 않았다 — `published_at` 표기가 **경로마다 다르기**
때문이다. yt-dlp 플랫 추출은 `YYYYMMDD`, YouTube API는 ISO 8601, 어떤 경로는 상대
표기("3일 전")를 준다. 형식을 잘못 짚으면 예외가 나지 않고 **조용히 틀린다**:
알림이 영영 안 오거나, 매 회차마다 피드 전체가 새 영상이 된다.

대신 **지난번에 본 주소 목록**과 비교한다(`domain/monitoring/watch.py`). 형식에
의존하지 않고, 피드에서 순서가 바뀌거나 잠깐 사라졌다 돌아와도 흔들리지 않는다.

여기서 나오는 두 가지 함정을 규칙으로 고정했다:

* **기억이 비면 새 영상이 하나도 없다고 본다.** 설치 직후 피드 전체를 알리면 알림이
  수십 개 뜨고, 사용자는 그 길로 OS에서 앱 알림을 꺼 버린다. 첫 회차는 기준선만 잡는다.
* **이번 피드로 기억을 갈아 끼우지 않고 이어 붙인다.** 채널 하나가 응답하지 않아
  피드가 짧아지는 순간이 있는데, 그때 갈아 끼우면 다음 조회에서 이미 본 영상이 전부
  새 영상이 된다. 상한(300)까지 이전 기억을 남긴다.

배경 조회는 **화면이 쓰는 캐시 키와 다른 키**(`__watch__`)로 돈다. 같은 키를 쓰면
사용자가 보던 채널 목록을 배경 결과가 덮어써 보던 것이 사라진다.

---

## 북마크는 우리가 거르지 않는다 (v1.28)

북마크 파일에는 영상이 아닌 링크가 섞여 있다. 그렇다고 "영상 사이트 목록"으로 걸러
버리면, yt-dlp가 받을 수 있는 1000여 개 사이트 중 우리가 아는 것만 남긴다 — **기능을
우리가 좁히는 셈**이다. 반대로 전부 담으면 쇼핑몰·문서가 라이브러리에 들어온다.

그래서 판단을 화면으로 넘겼다. `LIKELY_VIDEO_HOSTS`는 **거르는 기준이 아니라 미리
체크해 둘 기준**이고, 사용자가 목록을 보며 더하거나 뺀다. 호스트 판정은 `endswith`가
아니라 정확히 같거나 `"." + host`로 끝나는지를 본다 — `youtube.com.evil.example`을
영상으로 보면 안 된다.

파싱은 정규식으로 한다. 이 형식(Netscape Bookmark File Format)은 **닫는 태그가 없어**
(`<DT>`·`<p>`가 열린 채로 끝난다) 엄격한 HTML 파서가 구조를 잘못 잡거나 통째로
실패한다. 필요한 것은 `<A HREF>`와 `<H3>` 둘뿐이라, 위치 순으로 섞어 훑어 각 링크가
어느 폴더 아래였는지까지 얻는다.

---

## 저장된 검색은 값이 아니라 **프리셋 키**를 담는다 (v1.29)

"최근 1주"로 좁힌 목록을 저장할 때, 화면이 엔진에 넘기는 값
(`published_from="2026-09-12"`)을 그대로 담으면 다음 달에 그 검색을 열었을 때 **그 주의
영상만** 나온다. 사용자가 기대한 것은 "지금으로부터 최근 1주"다. 예외도 오류도 없이
조용히 엉뚱한 결과가 나오는 부류라 더 위험하다.

그래서 화면이 두 가지를 구분해 내놓는다:

| 메서드 | 무엇 | 쓰는 곳 |
| --- | --- | --- |
| `FilterBar.filters()` | 푼 값(`published_from="2026-09-12"`) | 목록 조회 |
| `FilterBar.condition_keys()` | 프리셋 키(`date_key="7d"`) | 저장 |

되부를 때는 `domain/library/filters.py`가 **오늘 기준으로 다시 푼다**. 길이·다운로드·
시청도 같은 이유로 키로 담는다 — 프리셋 경계가 나중에 바뀌면 저장된 검색도 함께
따라오는 편이 맞다.

---

## 저장된 검색은 사용자를 막아 세우지 않는다 (v1.29)

저장은 **곁가지 행동**이다. 사용자가 하려던 일은 영상 찾기이고, 저장은 그 조건을 또
쓰고 싶어서 하는 것이다. 그래서 거기서 되묻거나 거절하면 흐름이 끊긴다.

* **이름이 겹치면 번호를 붙인다**(거절하고 다시 묻지 않는다).
* **상한(50)을 넘기면 가장 오래된 것을 밀어낸다**(저장을 거절하지 않는다) — 거절하면
  사용자는 뭘 지워야 할지 모른 채 막힌다.
* 다만 **조건이 하나도 없는 검색은 저장하지 않는다** — 되불러도 아무 일이 없고 목록만
  지저분해진다.

이 정책은 화면이 아니라 **응용 계층**(`SaveSearchHandler`)에 있다. 나중에 다른
진입점(단축키·명령 팔레트)이 생겨도 같은 규칙을 타게 하기 위해서다. 같은 이유로
뷰모델은 리포지토리를 직접 잡지 않는다(`gui → application → domain`).

---

## 깨진 항목 하나가 목록 전체를 막지 않는다 (v1.29)

저장된 검색은 앱 버전을 오르내리며 필드가 늘거나 줄고, 사용자가 DB를 손볼 수도 있는
값이다. 그때 한 줄 때문에 목록이 통째로 안 뜨면 기능이 죽는다.

`SavedSearch.from_json`은 **모르는 키를 버리고 빠진 키를 기본값으로 채운다**. JSON이
아예 깨져 있으면 조건 없는 항목으로 떨어뜨리되 **이름은 살린다** — 사용자가 그것을
알아보고 지울 수 있어야 하기 때문이다. `id`가 UUID가 아닌 행만 건너뛴다(되부를 방법이
없다). 되부르기에서도 모르는 프리셋 키는 '전체'로 떨어진다.

---

## 워치 폴더 — 반쯤 담는 것이 못 담는 것보다 나쁘다 (v1.29)

폴더에 떨군 파일에서 주소를 거둬들인다. 여기서 실패 방식은 둘인데 무게가 다르다.

* **못 담는다**: 사용자가 알아차리고 다시 넣는다. 회복 가능하다.
* **반쯤 담는다**: 큰 파일이 복사되는 중간에 읽으면 주소가 잘린 채 들어온다. 사용자는
  전부 담긴 줄 알고, 원본 파일은 '처리됨'으로 옮겨져 있다. **되돌리기 어렵다.**

그래서 **수정된 지 3초가 안 된 파일은 건너뛴다**. 늦게 담는 것은 괜찮다.

처리한 파일은 기록을 남기는 대신 **옮긴다**. 기록을 따로 두면 그 기록과 실제 폴더가
어긋난다(사용자가 파일을 지우거나 되돌려 놓는다). 옮기면 폴더를 보는 것만으로 상태를
알 수 있고, 다시 담고 싶으면 도로 꺼내면 된다. 같은 이름이 있으면 번호를 붙인다 —
덮어쓰면 사용자가 되돌릴 수 없고, 같은 파일을 여러 번 떨구는 일이 흔하다.

**주소가 없는 파일은 옮기지 않는다.** 실수로 넣었거나 아직 채우는 중일 수 있는데,
말없이 옮기면 사용자에게는 파일이 사라진 것으로 보인다.

`.url`(윈도우가 링크를 폴더로 끌 때 만드는 INI 파일)은 `URL=` 줄을 **먼저** 본다.
그 형식에는 아이콘 경로(`IconFile=C:\...`)가 함께 들어 있어, 통째로 정규식을 돌리면
엉뚱한 것까지 주소로 잡힌다.
