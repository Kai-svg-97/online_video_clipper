# 노래·가사·앨범

> 노래 정보, 가사 검색·싱크, 앨범 보기.
> 색인: [`../design-decisions.md`](../design-decisions.md).

## 항목별 기록

- **노래 정보(song 컨텍스트)** — Video와 1:1인 `SongInfo`(가수·앨범·제목·발매년도·가사·is_song). **노래 판별**은 yt-dlp `categories`에 "Music" 포함 또는 `track`/`artist`/`album` 존재로 자동 감지하며, 상세 탭의 "노래로 표시" 토글로 수동 지정도 가능하다. **가사 조회는 관리형 출처 레지스트리(`lyrics_sources` 테이블)를 priority 순으로 순회하는 체인**(`FetchSongInfoHandler._run_chain`) — 기본 LRCLIB(무키·안정)→지니→벅스→Genius→멜론 순으로 부족한 항목(가사·가수·앨범·제목)을 이어서 채운다(**국내곡은 지니·벅스가 원가사를 안정적으로 반환**해 앞에 둔다 — Genius가 기여자/번역 헤더 쓰레기로 '조회 성공' 처리돼 국내 사이트가 시도조차 안 되던 문제 완화. Genius 파서는 `N ContributorsTranslations…Lyrics` 머리말·`…Embed` 꼬리말을 제거함. 멜론은 가사가 AJAX 지연 로드라 정적 스크래핑 불가 → 최하위·graceful None. 기존 설치본은 `_migrate_song_sources_reorder`로 1회 재정렬). **다중 아티스트 폴백**: yt-dlp `artist`는 협업/피처링을 콤마 등으로 이어 붙이는데(예: "NIKI, Phil Collins"), 제공자는 정확한 아티스트명으로 매칭하므로 이 전체 문자열로는 조회가 실패한다. `_run_chain`은 각 제공자에 **전체 아티스트 → 주(첫) 아티스트(`_primary_artist` — 콤마/`;`/`/`/`&`/`feat`/`ft`/`with`/`x`로 분리) 순으로 재시도**해 유명곡 가사를 놓치지 않는다(표시용 아티스트 값은 원본 전체를 보존). **가사 검색 기준값은 현재 노래 정보에 입력된 값(가수·제목·앨범 — 수동 편집 포함)을 최우선**으로 쓴다. **사용자가 항목을 한 번이라도 수정했으면(`manual_fields` 존재) 입력된 값만으로 검색하고, 빈 항목은 채우지 않는다**(영상 제목을 song_title 기본값으로 억지로 넣어 검색이 실패하던 문제 해결 — 예: 가수를 비우면 제목만으로 검색). **수정한 적이 없을 때만(자동 첫 조회) 영상 제목을 파싱**해 부족분을 보완한다. 따라서 제목·가수를 고친 뒤 ⟳를 누르면 그 값으로 다시 검색한다. 새 출처를 추가하면 자동으로 체인에 편입돼 정보를 보강한다(설정 화면에서 관리). **비한국어 가사는 `deep-translator`로 한글을 병행 표기**(원문+번역 `LyricsLine`); 한국어 가사(한글 비율≥0.3 감지)나 번역기 미설치 시 원문만. **등록·"노래로 표시" 토글·상세 최초 진입 시엔 영상 제목 기준으로 메타데이터(가수·앨범·제목·발매년도)만 채운다**(가사 네트워크 조회 생략 — `FetchSongInfoCommand.fetch_lyrics=False`; `SongViewModel.toggle_song`/`load(dto 없을 때)`). **가사는 '가사' 레이블 옆 가사 검색 버튼을 눌러야만 조회**한다(자동 조회 안 함). 검색 버튼은 아래 "가사 검색 후보 목록" 항목대로 **전 출처를 훑어 후보를 나열**하고 사용자가 고른 것만 반영한다. 옆의 **번역 버튼**은 현재 등록된 가사를 한글로 (재)번역해 저장한다(`TranslateSongLyricsCommand`/`TranslateSongLyricsHandler` — 조회와 분리된 독립 동작, `SongInfoAggregate.set_lyrics_translations`로 출처 유지·수동표시 안 함, 한국어면 no-op). **사용자가 더블클릭 편집한 필드는 `manual_fields`에 기록돼 갱신 시 덮어쓰지 않는다**(`SongInfoAggregate.apply_fetched`가 manual 필드를 건너뜀). 가사 제공자·번역기는 `domain/song/ports.py`의 Protocol(`ILyricsProvider`·`ITranslator`)에 의존하고 composition root가 구체 구현을 주입한다. Genius·국내 사이트 스크래퍼는 사이트 구조 변경에 취약하므로(그래서 켜고/끄기·순서 조정 가능) 실패는 격리돼 다음 출처로 이어지고 등록/재생에 영향을 주지 않는다. **같은 가수/앨범 필터**: 노래 탭 가수·앨범 값의 `»` 아이콘 → `ISongRepository.find_video_ids_by(artist=/album=)`(is_song=1 매칭)로 video_id를 구해 기존 `GetVideos(video_ids=)`로 조회, 상세화면 우측 목록을 그 결과로 교체(헤더 "가수/앨범: XXX"). **상세 우측 목록은 재생목록**으로 동작 — 현재 영상 포함·강조, `InlinePlayer.playback_finished`(EndOfMedia)에 다음 항목 자동재생(끝이면 정지). 진입 시 재생 전에는 목록과 동일한 썸네일을 포스터로 보여준다. **가수/앨범 필터 재생목록에서 마우스 뒤로가기**는 `LibraryPanel._playlist_ctx`(items·header·prev_related·history)를 두고 `_playlist_back`으로 재생 이력(history 스택)을 되짚어 이전 재생 항목을 열고(재생 중이면 이어재생), 이력이 소진되면 진입 직전 "연관 영상" 목록으로 복귀한다(재생목록 내 이동은 `push_nav=False`라 화면 히스토리를 오염시키지 않음).
- **가사 검색 후보 목록 (|출처|가수|제목|가사 첫째 줄|싱크|)** — 가사 검색 버튼(⟳)은
  이제 **활성 출처를 전부 훑어 후보를 나열**하고, 사용자가 고른 것만 반영한다.
  예전에는 체인(`FetchSongInfoHandler._run_chain`)이 첫 성공 출처를 곧바로 채택하고
  마음에 안 들면 '다음 출처'로 순환시켰는데, **어떤 가사인지는 적용된 뒤에야 볼 수 있었고**
  원하는 출처에 닿으려면 여러 번 눌러야 했다. 후보 검색은 별도 유스케이스
  (`SearchLyricsCandidatesHandler`)이며 **DB에 쓰지 않는다** — 채택은
  `ApplyLyricsCandidateHandler`가 맡아 "조회"와 "반영"을 분리한다(체인 검색은 등록 시
  자동 보강·싱크 가사 찾기 경로에서 그대로 쓰이므로 **삭제하지 않았다**).
  **출처당 후보는 여러 건이다.** 같은 제목의 다른 가수 곡이 흔해 1건만 받으면 엉뚱한
  곡이 걸리므로, 제공자에 `search()`(다건)를 추가하고 출처마다 최대
  `per_source_limit`건(기본 `DEFAULT_LYRICS_SEARCH_LIMIT`=10, **0이면 무제한**)을 모은다.
  무제한을 기본으로 두지 않는 이유는 스크래핑 출처(Genius·멜론·벅스·지니)가 곡마다
  상세 페이지를 한 번씩 긁어 요청 수 = 후보 수이기 때문이다. `search`가 없는 제공자는
  `fetch` 1건으로 폴백한다(`_search_one`이 `hasattr`로 판정 — 그래서 포트를
  `ILyricsSearchProvider`로 분리했다. `ILyricsProvider`에 넣으면 전 구현이 강제된다).
  **정렬은 출처가 주는 신호에 따라 다르다** — 조회수(Genius `stats.pageviews`)가 있으면
  내림차순, 없고 곡 길이만 있으면(LRCLIB) 영상 길이에 가까운 순, 둘 다 없으면
  **출처가 준 순서를 그대로 둔다**(국내 3사는 검색 결과 순서 자체가 그 사이트의 랭킹이라
  재정렬이 오히려 정보를 버린다). 핸들러의 `_rank_results`는 지표가 하나라도 있을 때만
  개입하는 **안정 정렬**이라, 제공자가 이미 정렬해 온 결과를 흐트러뜨리지 않는다.
  정렬 근거(조회수·길이)는 열을 늘리지 않고 행 툴팁(`_candidate_tooltip`)에 담는다.
  **결과는 전 출처가 끝나기를 기다리지 않고 도착하는 대로 표시한다** — 느린 출처 하나
  때문에 이미 확보한 후보를 못 보는 일이 없어야 하므로, 핸들러가 `on_start(출처)` →
  `on_result(출처, DTO)`(**출처당 여러 번**) → `on_source_done(출처, 건수)`를 부르고 GUI는
  '조회중…' 행을 먼저 깔아 둔 뒤 그 자리를 후보 N행으로 펼친다. **종료 통지가 따로 필요한
  이유**는 후보 0건인 출처는 `on_result`가 한 번도 안 불려 '조회중'과 구분이 안 되기
  때문이다. 표는 행 인덱스를 직접 만지지 않고 상태(`_order`/`_results`/`_pending`)에서
  **매번 다시 그린다**(`_rebuild`) — 출처마다 행 수가 달라 삽입 위치를 계산하면 어긋난다.
  대신 선택은 DTO 동일성으로 되찾아 유지한다(다른 출처 결과가 도착할 때마다 선택이
  풀리면 고르는 도중에 놓친다). `list_source_names()`가 반환하는 목록과 `handle()`이 실제로
  순회하는 목록은 **같은 조건**(활성 + 제공자 구현 존재)으로 추려야 한다 — 어긋나면 영영
  안 채워지는 '조회중…' 행이 남는다. 조회가 취소·중단돼도 `finish()`가 남은 행을
  '결과 없음'으로 정리한다.
  후보 DTO는 `lines`/`timings`를 **그대로 동봉**한다(고른 뒤 같은 출처를 다시 조회하지
  않기 위해 — 네트워크 절약 + 그새 다른 결과가 오는 사고 방지). 적용은 사용자가 명시적으로
  고른 것이므로 `force_lyrics=True`로 수동편집 가드를 넘어 교체하되, 가수·앨범 등
  메타데이터는 `apply_fetched` 규칙대로 수동 편집분을 보존한다. 검색 기준값 계산
  (`resolve_search_basis`)·다중 아티스트 폴백(`artist_search_candidates`)·번역 포함 줄 생성
  (`build_lyrics_lines`)은 체인 검색과 **같은 함수를 공유**한다(두 경로가 다른 결과를 내면
  "목록엔 있는데 자동 보강은 못 찾는" 혼란이 생긴다). UI는 가사 영역 스택의 index 2
  (`_LyricsCandidateList`)라 레이아웃이 흔들리지 않으며, 검색 중 다른 저장이
  `song_info_changed`를 쏘아도 목록을 닫지 않는다(`_SongTab.set_info`의 `_STACK_CANDIDATES`
  가드 — 닫히면 고르던 후보를 잃는다). 늦게 도착한 결과가 다른 영상의 목록에 섞이지 않도록
  VM은 새 검색 시 이전 워커를 `cancel()`+신호 disconnect하고, `VideoDetailWidget`은
  `video_id`가 현재 상세와 다르면 결과를 버린다. 회귀 테스트:
  `tests/unit/application/test_lyrics_candidates.py`(전 출처 순회·다건·상한·실패 격리·취소·적용 규칙),
  `tests/unit/infrastructure/test_lyrics_provider_search.py`(LRCLIB 제목만 재검색·중복 제거·Genius 상한·id 전수 추출),
  `tests/gui/test_lyrics_candidates_ui.py`(조회중 행·출처당 다행·선택 유지·VM→위젯 전 구간).
- **가사 자막 표시 · 싱크 조정** — 노래 영상 재생 중 가사를 영상 위 자막으로 표시한다.
  **타이밍의 유일한 출처는 LRCLIB의 `syncedLyrics`(LRC)** — 지니·벅스·Genius·멜론은
  시간 정보를 주지 않는다. 예전에는 syncedLyrics의 타임스탬프를 버리고 텍스트만 썼으나,
  이제 `infrastructure/song/lrc.py:parse_lrc`로 파싱해 `LyricsLine.start_ms`에 싣고
  `lyrics_json`에 `"s"` 키로 저장한다(값이 있을 때만 넣어 하위호환·프리필터 영향 최소화).
  **자막·싱크 UI는 `SongInfo.is_synced`(시각이 있는 줄이 1개 이상)일 때만 활성**하며,
  없으면 컨트롤바 `💬`가 비활성되고 노래 탭에 `⏱`(싱크 가사 찾기 —
  `FetchSongInfoCommand.synced_only`)가 뜬다. `synced_only` 조회는 타이밍 없는 출처를
  건너뛰고, **전 출처가 실패해도 기존 가사를 지우지 않는다.**
  보정은 **시작 오프셋 하나**(`SongInfo.lyrics_offset_ms`, ±30초 clamp)뿐이다 — 배속·구간
  늘림은 지원하지 않는다. `💬` 좌클릭 토글 / 우클릭 메뉴(±0.25초·"현재 위치를 이 줄에
  맞춤"·초기화), 단축키 `C`·`[`·`]`·`\`로 조작하고 500ms 디바운스로 DB에 저장한다
  (영상별 값이라 sync 캡처에 자동 편입 — 같은 영상은 다른 기기에서도 같은 어긋남을 갖는다).
  **`,`(빠르게)·`.`(늦게)는 `[`·`]`의 별칭**이다(`InlinePlayer.keyPressEvent`) — 자막 조정에
  익숙한 편집 프로그램 키 배치를 추가로 지원할 뿐 별개 동작은 아니다. **노래 탭에도
  같은 값을 직접 편집하는 입력 필드(`_SongTab._offset_spin`, ±30초·0.25초 단위)가
  있다** — ⏱(싱크 가사 찾기)와 상호 배타적으로 노출되며(시간 정보가 있어야 조정할
  대상이 있으므로), `InlinePlayer.set_subtitle_offset_ms()`(공개 setter, 내부적으로
  단축키가 쓰는 `_set_subtitle_offset`에 위임)를 호출해 **기존 저장 경로를 그대로
  재사용**한다 — 탭이 직접 DB에 쓰지 않고 플레이어의 `subtitle_offset_changed` 신호가
  다시 `VideoDetailWidget._on_subtitle_offset_changed`(디바운스 저장)로 흘러들어가는
  구조라, 플레이어 단축키·메뉴로 바뀐 값도 `_SongTab.set_offset_ms()`로 탭 표시에
  되돌아온다(양방향 동기화, `blockSignals`로 무한 루프 방지).
  **디바운스는 조정 시점의 video_id를 함께 캡처한다**(`_pending_offset: tuple[UUID, int]`)
  — 500ms 안에 다른 영상으로 전환해도 flush 시점 `self._detail`이 바뀐 값이 아니라
  원래 영상에 저장되도록 한다.
  렌더는 **`LyricsTrack`(순수 로직)과 `LyricsOverlay`(그리기)로 분리**해 경계값·오프셋
  로직을 QApplication 없이 테스트한다. 오버레이는 인라인·전체화면·PiP **3창 모두**에
  얹히며 기존 컨트롤바 팬아웃 패턴을 그대로 따른다 — **`bar`처럼 `subtitle`도 외부
  (InlinePlayer)가 내용을 채워야 한다.** 현재 줄 인덱스가 바뀔 때만 다시 그려 매 position
  틱 repaint를 피한다. 노래 탭은 재생에 맞춰 현재 줄을 accent 틴트로 강조하고 자동
  스크롤하되 **사용자가 직접 스크롤하면 3초간 멈춘다**(`valueChanged`가 아니라
  `sliderPressed`/`actionTriggered`를 듣는다 — `valueChanged`는 자동 스크롤 자신의 변화까지
  잡아 영구 억제된다). 가사를 손으로 편집하면 **줄 수가 같을 때만 기존 타이밍을 유지**한다
  (오탈자 수정으로 싱크가 날아가지 않게, 줄 구성이 바뀌면 신뢰할 수 없어 폐기).
  **자막 크기·위치는 사용자가 조절한다** — `Ctrl`+휠/방향키↑↓로 글자 크기(배율 0.5~3.0,
  스텝 0.1), `Ctrl+Shift`+휠/방향키↑↓로 세로 위치(`bottom_ratio` 0.0~0.6, 스텝 0.02).
  "위로 굴리면 값이 커진다"로 방향을 통일했고 `bottom_ratio`는 아래에서 띄우는 양이라
  값이 커지면 자막이 위로 올라간다. 두 값은 **영상별이 아니라 전역**이며(보기 설정이므로)
  `config.yaml`에 500ms 디바운스로 저장한다. **오버레이는 비디오 영역 전체를 덮는다** —
  예전엔 컨트롤바 위 28% 높이 띠라 글자를 키우면 잘렸고, 크기 비율(5.5%)이 그 띠에 적용돼
  실질 1.5%라 자막이 지나치게 작았다(지금은 영역 높이의 4.5%). 지오메트리는 인라인·PiP·
  전체화면(`_position_bar`/`resizeEvent`) **4곳**에 있으니 함께 고쳐야 한다.
  `keyPressEvent`는 원래 수정키를 보지 않았으므로 새 분기를 맨 앞에 두고 `Ctrl+Shift`를
  `Ctrl`보다 먼저 판정한다(맨 ↑↓ 볼륨과 충돌 방지). `_VideoView`(QGraphicsView)는 휠을
  삼키므로 `wheelEvent`에서 `ignore()`해야 하고, 이 도달성은
  `tests/gui/test_subtitle_player.py::TestSubtitleWheel`이 실제 휠 이벤트로 고정한다.
  다만 `ignore()`만으로는 부족하다 — `QAbstractScrollArea`는 viewport 이벤트를
  `viewportEvent()`로 dispatch해 부모 전파 경로를 타지 않으므로, `InlinePlayer.eventFilter`
  의 Wheel 분기가 **세 창의 viewport를 모두**(인라인 `_video_view`, 전체화면·PiP `_vw`)
  명시적으로 가로채 `wheelEvent`로 넘긴다. 한 곳이라도 빠지면 그 창에서만 조용히 죽는다.
  **저장된 값은 `_setup()` 끝에서 `_apply_subtitle_prefs()`로 오버레이에 밀어 넣는다** —
  생성자가 필드에 담기만 하면 화면은 기본 크기로 뜨고 첫 조작에서 값이 튄다.
  **조절 피드백은 `LyricsOverlay.set_notice()`로 3창 오버레이 모두에 그린다** — 인라인
  상태 라벨(`_status_lbl`)은 전체화면에서 가려지고 PiP는 아예 다른 창이라 안 보인다.
  임시 문구는 직전 안내("스트림 URL 가져오는 중…")를 보관했다가 만료 시 복원한다.
  **`💬` 우클릭 초기화 메뉴는 값이 기본값이 아니면 싱크 가사가 없어도 열린다**
  (`_ControlBar.set_subtitle_prefs_dirty` → `_refresh_cc_enabled`/`_build_subtitle_menu`).
  조절 단축키에는 가사 조건이 없어서, 없으면 비노래 영상에서 키운 전역 값을 되돌릴
  방법이 사라진다. 오프셋 관련 항목은 트랙이 있어야 의미가 있어 그때만 넣는다.
  저장값은 `round(v, 2)`로 자른다(0.1 누적이 `1.9700000000000002`로 박히던 문제).
  **테스트는 실사용 `data/config.yaml`을 절대 건드리면 안 된다** —
  `tests/gui/test_subtitle_player.py`의 autouse 픽스처가 `save_setting`을 무력화하고
  시작값을 기본값으로 고정한다(디바운스 타이머가 살아남아 실제 파일에 값을 누적하면
  다음 실행부터 다른 테스트가 깨진다).
- **앨범 보기 (음악 카테고리 전용, 파생 그룹)** — 최상위 카테고리가
  `MUSIC_ROOT_CATEGORY_NAMES`(music·song·음악·노래·뮤직)일 때만 **보기 유형 버튼에 💿**가
  나타난다(`LibraryPanel._update_view_options`, ⊞/☰/⊟ 옆). 앨범은 **정렬이 아니라 보기
  방식**이다 — 같은 목록을 자켓 단위로 묶어 보는 것이라 리포지토리 정렬 컬럼으로는 표현할 수
  없다(처음엔 정렬 항목이었는데, 정렬로 두면 SQL 정렬로 새어 나갈 위험이 있고 의미도 맞지
  않아 옮겼다). 앨범 버튼도 `_view_group`의 일원이라 **앨범에서 빠져나올 때 `checkedId()`로
  되돌리면 다시 앨범**이 된다 — `_last_list_view`(마지막 아이콘/리스트/표 뷰)로 복귀한다.
  음악이 아닌 카테고리로 옮기면 버튼을 감추고 앨범 모드도 함께 푼다(버튼이 사라졌는데 화면만
  앨범 그리드로 남으면 빠져나갈 방법이 없다).
  **트리에서 카테고리를 고르면 음악 카테고리라도 앨범 보기에서 나온다**(`_on_cat_filter_changed`).
  트리 클릭은 "이 카테고리를 보겠다"는 뜻이지 "앨범 보기를 유지한 채 대상만 바꾸겠다"는 뜻이
  아니다 — 특히 앨범 상세를 보던 중이면 화면이 앨범에 머물러 갇힌 느낌이 든다. 나가는 것과
  잃는 것은 다르므로 직전 앨범 화면은 히스토리에 남아 뒤로가기로 돌아온다(진입은 💿 버튼).
  단 **복원 중(`_is_restoring`)에는 건드리지 않는다** — 그때는 스냅샷이 앨범 여부를 결정하며
  (`_restore_album_mode`), 여기서 나가 버리면 되살리려던 앨범 화면이 사라진다.
  **앨범은 저장되지 않는다**: `domain/song/album.py`가 노래 정보(가수·앨범)에서 묶음을 만들고,
  표기 차이는 정규화로 흡수하며 문자열 `"null"` 같은 자리표시자는 앨범명으로 보지 않는다
  (실제 DB에 있던 값). 목록 조회(`GetAlbumsHandler`)는 **네트워크를 쓰지 않는다** — 카테고리를
  옮길 때마다 외부 API를 때리지 않기 위해 캐시된 자켓만 붙인다. 자켓·설명·수록곡 전체는
  **앨범을 열 때** `GetAlbumDetailHandler`가 iTunes(무키)에서 받아 `album_cache`에 저장한다.
  **iTunes `lookup`에는 `country`를 붙이면 안 된다** — 실측 결과 수록곡이 통째로 빠지고 앨범
  한 건만 돌아와, 14곡짜리 앨범이 '내 곡 1개'로 조용히 잘못 보였다(`search`에는 붙여도 된다).
  **앨범 식별은 앨범명 텍스트 검색보다 곡 기준 조회를 먼저 시도한다**
  (`GetAlbumDetailHandler._resolve_metadata`) — 표기 차이·동명 앨범(재발매·베스트 앨범 등)
  때문에 `fetch_album(가수, 앨범명)`이 엉뚱한 앨범을 고르는 사고가 있었다. 대신
  `earliest_registered`(`domain/song/album.py`)로 **그 묶음에서 가장 먼저 등록한 곡**을
  앵커로 골라(생성 시각이 없으면 목록의 첫 항목으로 폴백) `find_album_of_track(가수,
  곡제목)`으로 정확히 그 곡을 iTunes에서 찾아 앨범을 확정한다 — 사용자가 직접 처음
  등록한 곡은 손대지 않은 원본 데이터라 가장 신뢰할 수 있다. `_anchor_in_tracks`가
  찾은 앨범이 실제로 그 곡을 담고 있는지 검증하는 안전판이다(잘못된 collectionId
  방어) — 검증에 실패하거나 앵커가 없을 때만 기존 앨범명 검색으로 되돌아간다.
  외부 조회가 실패하면 **내가 가진 곡만으로** 앨범을 구성한다(화면이 통째로 비지 않게).
  외부 수록곡과 내 영상은 `match_track_to_songs`로 붙이는데, 영상 제목에 붙은 꼬리표를 걷어낸
  뒤 완전일치→부분일치 순으로 보고 **3글자 미만 곡명은 부분일치를 허용하지 않는다**("Go"가
  아무 제목에나 걸린다). 외부 목록에 없는 내 곡은 뒤에 붙여 **화면에서 사라지지 않게** 한다.
  **수록곡의 신원은 (디스크, 트랙) 쌍이다** — 트랙 번호는 디스크 안에서만 유일해서,
  2장짜리 앨범(예: iTunes의 'Mercury - Acts 1 & 2' = disc1 1~14 + disc2 1~18)에서는
  번호만으로 다루면 **서로 다른 곡이 한 곡으로 뭉개진다**. 실제로 그 증상이 나왔다:
  `album_track_links`의 키가 `(album_key, track_no)`라 disc1·disc2의 같은 번호가 서로를
  덮어썼고, `AlbumDetailPanel.apply_filled_track`도 번호만 비교해 같은 번호 행 **둘 다**를
  같은 곡으로 갈아치웠다(화면에 같은 제목이 두 줄씩 떴다). 지금은 `AlbumTrackInfo`·
  `AlbumTrackDTO`·`AlbumTrackLink` 모두 `disc_no`를 갖고, 링크 키는
  `(album_key, disc_no, track_no)`이며 행 갱신도 `AlbumTrackDTO.slot`으로 찾는다.
  정렬은 `(disc_no, track_no)`, 표시는 2장 이상일 때만 `1-3`처럼 디스크를 붙인다.
  기존 캐시는 어느 디스크의 것인지 알 수 없어(=틀린 매핑이 섞여 있어)
  `migrate_album_disc_no`가 **버리고 다시 만든다** — 파생 캐시라 다시 조회하면 복구된다.
  **수록곡 헤더의 '＋ 현재 카테고리에 등록'**(`add_all_requested` → `AddAlbumTracksHandler`)은
  자동 매핑된(스트리밍) 곡을 현재 카테고리로 한꺼번에 담는다. 등록만 하면 새 영상이 앨범 값
  없이 들어와 '앨범 미상'으로 떨어지므로 — 담았는데 그 앨범에는 안 보인다 — **노래 정보
  (가수·앨범·곡 제목)를 함께 기록**한다. `AddVideoHandler`가 upsert라 중복 클릭·부분 실패 후
  재시도도 안전하고, 한 곡이 실패해도 나머지는 계속 담는다.
  라이브러리에 없는 곡은 앨범을 열 때 `FillAlbumTracksHandler`가 `"<가수> <곡> official audio"`로
  yt-dlp 검색해 붙이고(곡당 1회, 결과는 `album_track_links`에 저장돼 재검색하지 않음), 진행 상황을
  곡 단위 콜백으로 흘려 도착하는 대로 표시한다. 수록곡 배지는 **내 등록/자동 매핑/없음** 세 가지다.
  **검색 결과를 그대로 붙이지 않고 `domain/song/album.py:pick_official_audio`로 검증한다** —
  실제 신고: "자신의 음원이 아닌 경우"(동명이곡·커버·리액션·1시간 루프)가 수록곡에 붙었다.
  순수 함수라 네트워크 없이 판정한다: ① 후보 제목에 커버·리믹스·라이브 등
  위험 키워드가 있으면 배제(**대상 곡 제목 자체에 있는 표기는 예외** — 정식 발매곡이
  "Song (Remix)"면 후보도 당연히 그 표기를 담고 있어야 하므로) ② 정규화한 제목이 실제로
  그 곡을 가리키는지 확인(완전 일치 또는 3글자 이상 부분 포함) ③ **가수를 알면 후보
  제목이나 채널명에 그 가수가 보여야 한다** ④ iTunes가 준 곡 길이와
  크게 다르면(다른 버전·컴필레이션 추정) 배제.
  **①의 키워드 검사는 ASCII만 단어 경계(``)로 한다** — 부분문자열로 찾으면 "Amrit"의
  `mr`, "Alive"의 `live`가 걸려 정답 후보가 조용히 버려진다(실측). 한글은 띄어쓰기 없이
  붙는 일이 흔해("영상리액션") 경계를 쓰면 오히려 놓치므로 부분문자열 그대로 둔다.
  **②는 제목 변형(`_title_variants`)을 함께 본다** — iTunes 수록곡 제목에는 괄호 밖
  꼬리표가 붙어("Enemy (with JID) - from the series Arcane…") 전체 문자열로만 견주면
  실제 공식 영상조차 일치하지 않아 영영 '없음'으로 남는다(실측). 정규화는 제목 속
  하이픈을 지키려고 `" - "`를 자르지 않으므로, 여기서 `" - "` 앞부분을 변형으로 추가한다.
  **③은 원래 점수 가산 요소였을 뿐이라 아무 후보도 막지 못했다** — 실측 사고: Mr.Children의
  앨범 'HOME'을 채울 때 "Wake Me Up!"에 Avicii, "Piano Man"에 Billy Joel, "Houkiboshi"에
  규현의 곡이 붙었다(셋 다 제목만 같고 가수가 다르다). 검색어가 `"<가수> <곡> official
  audio"`라 정답 후보에는 가수가 제목이나 채널에 거의 항상 드러나므로, 근거가 하나도
  없는 후보는 남의 곡으로 본다. **가수명 대조(`_name_visible`)는 ASCII면 낱말 단위**다
  ("IU"가 "studious"에 걸리면 안 된다). 다만 **띄어쓰기를 지운 표기도 함께 본다** —
  YouTube 채널 핸들은 붙여쓰기가 흔해("ImagineDragons") 낱말 경계만 보면 정작 그 가수의
  공식 채널이 남의 채널로 판정된다(실측). 짧은 이름의 오탐을 막으려 붙여쓰기 대조는
  4글자 이상일 때만 허용하고, 한글·일본어는 조사가 붙는 표기가 흔해 부분문자열로 둔다.
  살아남은 후보 중에서는 **채널명에 가수가 있는지**(공식 채널 — 제목에만 가수를 적어 둔
  팬 편집본과 갈라 준다), YouTube가 자동 생성하는 `<가수> - Topic` 채널인지(공식 음원임을
  더 강하게 시사), 곡 길이가 얼마나 가까운지로 점수를 매겨 가장 그럴듯한 것을 고른다. 검색
  풀은 검증으로 걸러질 것을 감안해 `_SEARCH_POOL`(8)로 넉넉히 받는다(한 번의
  `ytsearchN:` 호출이라 늘려도 요청 수는 그대로다). **하나도 통과하지 못하면 그
  수록곡은 계속 'missing'으로 남는다** — 틀린 음원을 붙이느니 '없음'이 낫다(외부 수록곡
  제목이 로마자인데 실제 영상은 원어인 경우 — 일본곡의 "Houkiboshi" ↔ 「箒星」 — 처럼
  정답을 못 찾는 자리도 생기지만 그 자리는 비워 두는 것이 맞다).
  **검증 규칙을 고쳐도 이미 저장된 연결은 그대로 남는다** — 사용자 화면은 아무것도
  달라지지 않으므로 `migrate_album_links_reverify`가 1회 재판정한다. 저장된 행에 스트림
  제목·채널이 있고 앨범 키 앞부분이 정규화된 가수명이라(`album_key_artist`) **네트워크
  없이** `link_artist_matches`로 그 자리에서 판정할 수 있다. **전부 비우지 않고 틀린 것만
  지운다** — 실측 라이브러리에서 잘못된 매핑은 42건 중 3건뿐이었고, 나머지를 함께 버리면
  앨범을 열 때마다 곡마다 yt-dlp 검색이 다시 돈다. 사용자가 지운(`rejected`) 행은
  손대지 않는다(캐시가 아니라 판단이라, 지우면 그 자리가 자동 채우기 대상으로 되살아난다).
  **수정 모드로 잘못 붙은 자동 매핑을 지운다**: 앨범 상세 우측 상단 "✎ 수정" 토글을
  누르면(누르기 전엔 완전히 숨겨져 있다) **자동 매핑(AUTO) 행에만** 삭제(✕) 버튼이
  뜬다(`_TrackRow.set_edit_mode` — 내 라이브러리 영상은 훨씬 무거운 동작이라 대상이
  아니고, '없음'은 지울 게 없다). 클릭하면 `RemoveAlbumTrackLinkHandler`가
  그 (disc_no, track_no) 행을 **지우지 않고 `origin=rejected`로
  표시**한다(`IAlbumRepository.reject_track_link`, 스트림 정보는 비운다). **행을 지우면
  앨범을 다시 열 때 자동 채우기가 같은 영상을 도로 붙여 지우는 기능이 무력해진다**
  (실측 — `_on_album_detail_ready`가 `missing_count > 0`이면 매번 채우기를 돌린다).
  그래서 `FillAlbumTracksHandler`는 `retry_rejected=False`(앨범 열 때 도는 자동
  채우기)면 거부된 슬롯을 건너뛰고, 사용자가 **'빠진 곡 찾기'를 직접 누른 경우에만**
  `retry_rejected=True`로 다시 시도한다. DB 한 줄 갱신뿐이라 QThread 없이 즉시
  처리되며(`AlbumViewModel.remove_track_link`), 그 슬롯만 '없음'으로 되돌린 DTO를 실어
  화면 한 자리만 갱신한다(전체 재조회 없음). **VM이 들고 있는 `detail`도 함께 갈아
  끼운다** — 앨범 재생·수록곡 클릭이 `vm.detail`을 그대로 쓰므로, 안 고치면 방금 지운
  음원이 재생목록에 남아 그대로 재생된다. 다른 앨범으로 넘어가면 수정 모드는 자동으로 꺼진다
  (`AlbumDetailPanel.set_detail`) — 켜진 채로 남으면 새로 연 앨범에서 실수로 누를 수 있다.
  앨범 값이 빈 노래는 `ResolveUnknownAlbumsHandler`가 가수·제목으로 앨범을 추정해 `apply_fetched`로
  채우고(다음 조회부터 제 앨범으로 이동), 실패한 곡은 `album_lookup_state`에 남겨 **화면을 열
  때마다 같은 조회를 반복하지 않는다**. 재생은 새 경로를 만들지 않고 기존 재생목록 컨텍스트
  (`_playlist_ctx`)를 그대로 쓴다 — 로컬 곡은 video_id, 자동 매핑 곡은 FeedVideoDTO를 payload로
  실어 자동 다음곡·뒤로가기가 그대로 동작한다. 앨범 화면은 **하위 카테고리까지 포함**한다
  (`_album_category_ids` — 음악 라이브러리는 'Music > 가수 > 곡' 구조라 루트에서 보면 전부 빠진다).
  **앨범 화면도 화면 히스토리에 편입된다** — 스냅샷(`_capture_screen`)에 `album_mode`·
  `album_key`를 함께 실어, 앨범 그리드 진입(`_enter_album_mode`)·앨범 상세 진입
  (`_on_album_clicked`)·앨범 재생(`_start_album_playlist`) 세 지점에서 직전 화면을 쌓는다.
  복원은 `_restore_album_mode`가 모드를 맞춘 뒤 상세를 다시 여는 순서다(상세는 그리드 위에
  열리므로 순서가 뒤바뀌면 안 된다). 마우스 ‹/›가 앨범 화면에서도 먹도록 이벤트 필터를
  앨범 그리드·상세에도 설치한다(영상 상세는 자체 app 레벨 필터를 쓴다).
  회귀 테스트: `tests/unit/domain/test_album_grouping.py`(그루핑·정규화·매칭 규칙),
  `tests/unit/infrastructure/test_album_provider.py`(요청 파라미터·country 금지·실패 격리),
  `tests/integration/test_albums.py`(캐시·폴백·자동 채우기·앨범 추정),
  `tests/gui/test_album_view.py`(보기 버튼 노출 조건·배지·재생 배선·2장 앨범 행 갱신).
