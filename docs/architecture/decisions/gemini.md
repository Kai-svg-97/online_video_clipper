# Gemini 요약

> YouTube 'AI 요약'을 받아 오는 방식과 언어별 저장.
> 색인: [`../design-decisions.md`](../design-decisions.md).

## 항목별 기록

- **Gemini AI 요약 자동 메모 저장** — `DownloadSettings.capture_gemini=True`이면 다운로드 완료 후 `GeminiExtractor`(Playwright sync API)가 YouTube 페이지에서 요약 텍스트를 추출하고, `AddVideoHandler`를 통해 라이브러리 영상 `notes` 필드에 저장한다(`initial_notes` — 기존 메모가 비어있을 때만 덮어씀). 추출 실패는 완전히 격리돼 다운로드 결과에 영향을 주지 않는다. `infrastructure/browser/gemini_extractor.py`는 반드시 QThread에서만 호출한다. **패키징(PyInstaller) 빌드에는 Playwright의 Chromium 바이너리가 번들되지 않는다**(spec이 playwright 브라우저를 수집하지 않음 → `BrowserType.launch: Executable doesn't exist …chrome-headless-shell.exe`). 따라서 `_launch_browser()`는 시스템 설치 브라우저를 `channel="chrome"`→`"msedge"` 순으로 우선 실행하고, 둘 다 없을 때만 번들 Chromium으로 폴백한다(대상 사용자 대부분이 Chrome/Edge 보유 → 150MB 브라우저 번들 회피). 쿠키 소스(인증)와 실행 브라우저는 별개다. **"질문하기" 버튼 클릭은 채팅 패널을 여는 것일 뿐 자동 요약이 아니다** — 실제 요약을 얻으려면 패널 안의 "동영상을 요약해 줘" 추천 칩을 다시 클릭해야 한다(`_click_and_extract`). 응답은 스트리밍으로 채워지므로 고정 지연 대신 칩을 감싸는 컨테이너(칩에서 6단계 조상으로 추정)의 `innerText`가 `_STABLE_REQUIRED_COUNT`회 연속 동일할 때까지 폴링해 완료를 판단한다(`_wait_for_stable_text`). 실패 시 `LOG_DIR/gemini_debug.png`·`gemini_debug.html`에 진단 스냅샷을 남긴다. **Gemini가 자동화 브라우저를 감지해 "문제가 발생했습니다" 오류로 요청을 거부하는 사례를 확인**했다 — 헤드리스 Chromium에 `--disable-blink-features=AutomationControlled` 인자와 `navigator.webdriver` 오버라이드 init script로 완화하고, 오류 문구(`_ERROR_PHRASE`) 감지 시 칩을 최대 `_MAX_ERROR_RETRIES`회 재클릭한다. **`get_by_text`로 잡은 요소가 텍스트 span/div일 뿐 실제 클릭 핸들러가 걸린 button이 아니어서 클릭이 씹히는 사례를 확인** — 클릭 전 `xpath=ancestor-or-self::button[1]`로 진짜 버튼 조상을 우선 사용하고, 클릭 전/후 패널 텍스트가 동일하면(=클릭 미반영) 재시도 후에도 그대로면 실패로 처리한다(정적 인사말을 성공으로 오인하지 않도록). **인증은 쿠키 파일(Netscape 포맷)로만 이루어진다.** 확보 우선순위: 1) 설정 화면 "구독 피드 — 브라우저 쿠키" 섹션의 "또는 쿠키 파일"(`YT_AUTH_COOKIEFILE`), 2) `data/auth/youtube_cookies.txt` — `gui/dialogs/youtube_auth_dialog.py`의 `YouTubeAuthDialog`(Playwright로 **자체 브라우저 창**을 띄워 로그인시키고 `context.cookies()`로 직접 캡처해 `write_netscape_cookies`로 저장)가 이 파일을 만든다. **설정 화면 "구독 피드 — 브라우저 쿠키" 섹션 맨 위 "브라우저 열어서 로그인 (권장)" 버튼**(`SettingsPanel._on_open_auth_dialog`)으로 연결되어 있다 — 예전엔 이 다이얼로그가 구현은 돼 있었지만 앱 어디에서도 열리지 않는 미연결 코드였다("쿠키를 왜 찾아야 하냐, 브라우저를 띄워서 로그인시키면 안 되냐"는 사용자 질문으로 연결). **기존 브라우저의 쿠키 DB를 전혀 건드리지 않아**(자체 격리된 Playwright 컨텍스트에서 로그인) Chrome 잠금·App-Bound Encryption 문제와 완전히 무관하게 동작하는 것이 핵심 장점이다 — 아래 "브라우저/프로필" 자동 감지가 실패하는 환경에서도 이 방법은 별도의 문제다. `_find_system_chromium_exe()`가 시스템 설치된 Chrome/Edge/Brave 실행 파일을 직접 찾아 `executable_path`로 넘겨 실행하므로(playwright `channel=`이 아님) 패키징 빌드에도 번들 Chromium 없이 동작하며, 못 찾으면 `_open_system_browser()`가 기본 브라우저로 로그인 페이지만 열고(쿠키 자동 캡처는 안 됨) "브라우저 계정" 탭에서 프로필을 고르라고 안내한다. **Google이 자동화된 브라우저의 로그인을 차단하는 사례를 실제로 확인**했다("로그인할 수 없음 — 브라우저 또는 앱이 안전하지 않을 수 있습니다") — Playwright가 CDP로 제어하는 브라우저는 Google 로그인 시점에 자동화로 탐지되기 쉬우며, `gemini_extractor.py`와 동일하게 `--disable-blink-features=AutomationControlled` + `navigator.webdriver` 오버라이드를 추가했지만 **Google의 로그인 자동화 탐지는 페이지 열람 탐지보다 훨씬 엄격해 이 완화만으로 항상 우회되지는 않는다**(구조적 한계 — CDP 제어 자체가 탐지 신호가 될 수 있음). 따라서 **설정 화면에서 이 버튼은 더 이상 "권장"으로 표기하지 않고**, "쿠키 파일 등록 방법 보기"(사용자가 평소 쓰는 정상 브라우저에서 확장으로 직접 내보내는 방식 — 자동화 탐지 대상이 아님)를 실질적인 권장 경로로 안내한다. 3) 같은 설정 섹션의 "브라우저"/"프로필" 드롭다운(`YT_AUTH_BROWSER`/`YT_AUTH_PROFILE`)을 `GeminiExtractor._export_browser_cookies()`가 yt-dlp `cookiesfrombrowser`로 임시 내보내기(Firefox 등 대부분 브라우저에서 동작; 임시 파일은 Netscape 헤더로 미리 초기화해야 yt-dlp의 cookiejar 최초 로드가 실패하지 않음). **Chrome v127+ 예외**: Chrome은 쿠키를 App-Bound Encryption으로 암호화해 프로필 직접 실행·프로필 파일 복사·yt-dlp `cookiesfrombrowser` 세 가지 방식 모두 외부 프로세스가 복호화할 수 없음을 확인했다(DPAPI 오류) — Chrome 사용자는 방법 1(쿠키 파일 직접 등록)만 유효하다. **브라우저/프로필 쿠키 내보내기는 자동 감지로 폴백한다** — 사용자가 "매번 설정에서 브라우저/프로필을 다시 골라야 해서 불편하다"고 신고한 뒤 추가됨. `GeminiExtractor._export_browser_cookies()`는 이제 설정된 브라우저(있으면)를 먼저 시도하고, 실패하거나(브라우저 실행 중 DB 잠금·Chrome 암호화 실패 등) 아무것도 설정하지 않았으면 `_auto_detected_candidates()`가 `infrastructure/auth/youtube_auth.py:YouTubeAuthService.detect_profiles()`로 설치된 모든 브라우저의 로그인 프로필을 `_AUTO_DETECT_BROWSER_ORDER`(firefox→edge→chromium→chrome) 순으로 순회해 자동으로 시도한다. 자동 감지로 성공한 조합은 `save_setting`으로 즉시 저장돼 다음 시도부터 먼저 쓰인다(반복되는 실패-재탐색 축소). 이미 시도한 (브라우저, 프로필) 조합은 자동 감지 단계에서 중복 시도하지 않는다. **설정된 브라우저·자동 감지가 모두 실패해 쿠키를 전혀 못 찾으면 반드시 `out["reason"] = SUMMARY_REASON_NOT_SIGNED_IN`을 채운다** — 예전엔 이 경로가 사유를 채우지 않아 `extract_with_reason`이 기본값(`SUMMARY_REASON_ERROR`, "잠시 후 다시 시도하세요")으로 떨어졌다. 실제로는 로그인된 브라우저를 못 찾은 것인데 원인을 알 수 없는 오류로만 보여, 브라우저 프로필을 이미 선택했는데도 왜 계속 실패하는지 알 수 없게 만들었다(사용자 실제 신고로 발견). **쿠키 파일 후보 자동 스캔**: "쿠키 파일" 기능을 한 번도 써본 적이 없어 어디 두는지조차 모른다는 신고에 따라, `infrastructure/auth/youtube_auth.py:find_cookie_file_candidates()`가 `~/Downloads`·`~/Desktop`을 스캔해 Netscape 헤더 + `youtube.com` 도메인 항목을 포함한 `.txt` 파일(브라우저 확장이 내보낸 쿠키 파일 — 파일명이 제각각이라 **내용**으로 판별)을 최신 수정 순으로 찾는다. 설정 화면 "구독 피드 — 브라우저 쿠키" 섹션의 "감지된 쿠키 파일" 콤보(`SettingsPanel._reload_cookie_candidates`)가 이 목록을 보여주고, 선택하면 "또는 쿠키 파일" 경로란에 채워진다("다시 검색" 버튼으로 재스캔, 방금 확장으로 내보낸 경우 대응). 후보가 없으면 안내 문구만 표시되고 기존 "찾기…" 수동 선택은 그대로 남는다. **일반 사용자를 위한 폴더 바로가기·안내 다이얼로그**: "이건 컴퓨터 전문가용 앱이 아니다"(브라우저/프로필 자동 감지가 전혀 동작하지 않는 환경에서 경로를 직접 찾아야 하는 데 대한 불만)는 신고에 따라, `gui/panels/settings_panel.py:open_folder(path)`(`QDesktopServices.openUrl(QUrl.fromLocalFile(...))`)로 경로를 직접 입력할 필요 없이 버튼 클릭만으로 탐색기를 연다. "저장 경로" 섹션의 데이터베이스·다운로드·썸네일·로그 4개 행 각각에 "열기" 버튼을 추가했고, 쿠키 섹션에는 "쿠키 파일 등록 방법 보기"(`COOKIE_HELP_TEXT` — 확장 설치→로그인 확인→내보내기→"다시 검색" 4단계 평문 안내 + "다운로드 폴더 열기" 버튼이 있는 `QDialog`)와 "로그 폴더 열기" 버튼을 추가했다. 후자는 사용자가 `AppData` 경로를 몰라도 로그 폴더를 열어 `app.log`를 지원 요청 시 첨부할 수 있게 한다. **자동 감지가 왜 후보를 못 찾았는지도 로그에 남긴다**: 실제 사용자가 보내온 로그에서 "설정된 브라우저·자동 감지 모두 실패"만 보이고 firefox·edge·chromium·chrome 각각이 몇 개의 프로필을 찾았는지 전혀 알 수 없어 원인을 좁힐 수 없었던 사례가 있었다. `_auto_detected_candidates()`가 이제 브라우저별 프로필 개수를 `"자동 감지 브라우저별 프로필 개수: firefox=0, edge=1, ..."` 형식으로 INFO 로그에 남기고, `detect_profiles()` 호출 자체가 예상 밖의 예외를 던지는 경우도 호출부에서 한 번 더 잡아 로그로 남긴다(라이브러리 내부 예외 처리에만 의존하지 않음).
- **Gemini 요약 — Playwright 대기 함정과 영상별 기능 제공 여부** — `Locator.is_visible(timeout=...)`의 `timeout`은 **Playwright가 무시한다**(문서: "Deprecated: This option is ignored. `locator.is_visible()` does not wait for the element to become visible and returns immediately."). 과거 `_click_and_extract`가 이걸로 "질문하기" 버튼을 찾아 **0초 대기**했고, 액션 행이 아직 스켈레톤인 영상에서 0.2초 만에 미발견으로 포기했다. 지금은 `_find_ask_button`이 `wait_for(state="visible")`로 총 `_ASK_BUTTON_TIMEOUT_MS`(20초)를 한 번만 소비한다. **셀렉터마다 `>> visible=true`를 반드시 붙인다** — 실측 결과 지원 영상에서 `button[aria-label*='질문하기']`가 5개 매칭 중 첫 번째가 **숨은 요소**여서, 필터 없이 `or_`로 합치면 `.first`가 그 숨은 요소를 가리켜 정상 영상까지 실패하는 회귀가 난다(한 번 실제로 냈다). 로그인 판정 `_detect_login_state`도 같은 이유로 `wait_for`를 쓴다 — 예전엔 로그인이 됐는데도 "판별 불가"로 기록돼 실패 원인을 잘못 짚게 했다. **YouTube는 이 기능을 영상별로 선별 제공한다**: 조회수가 적거나 업로드가 최근인 영상은 DOM에 `질문하기`가 **아예 없어**(1920px에서도 0개, 오버플로 메뉴에도 없음) 어떤 대기·수정으로도 요약을 얻을 수 없다. 따라서 실패 로그는 '미로그인'과 '영상 미지원'을 구분해 남기고, UI 메시지도 쿠키 문제로 단정하지 않는다. **실패 사유는 영속된다**: `GeminiExtractor.extract_with_reason(url) -> (요약, 사유)`가 `SUMMARY_REASON_NO_BUTTON`·`NOT_SIGNED_IN`·`ERROR`를 돌려주고, `video_summary_status` 테이블(video_id, status, updated_at — `video_descriptions`처럼 분리해 `videos` 행을 늘리지 않는다)에 저장된다. `VideoDetailDTO.summary_status`로 실려 요약 탭 placeholder가 사유별로 달라진다(`video_detail_panel.summary_placeholder`, `no_button`이면 "질문하기 버튼이 없어 가져오는데 실패했습니다"). 요약을 성공적으로 가져오면 행을 삭제해 문구가 사라진다. 기록 경로는 등록 시 자동 보강(`EnrichVideoHandler`)과 상세 ⟳(`_GeminiSummaryWorker.done`이 사유를 실어 `summary_status_saved` → `UpdateVideoCommand.summary_status`) 두 곳이다. 기존 `extract()`는 `ISummarySource` 포트 계약이라 그대로 두었다(다운로드 완료 캡처가 쓴다). **상세 화면 상단의 한 줄 상태 라벨(`_summary_status_lbl`)도 사유별로 다른 문구를 쓴다**(`video_detail_panel.summary_failure_status_label`) — 과거엔 사유와 무관하게 항상 "설정에서 브라우저/프로필을 선택하거나 쿠키 파일을 등록하세요"를 보여줘, `no_button`(YouTube가 그 영상에 요약 기능을 제공하지 않는 것)처럼 설정을 고쳐도 소용없는 경우까지 설정 탓으로 안내해 사용자가 반복적으로 헛수고를 하게 만들었다.

## Gemini 요약을 언어별로 (v1.33 준비)

영어 화면이 생긴 뒤에도 요약은 `videos.gemini_summary` 한 칸짜리 한국어였다. 영어로 다시
받으면 한국어 요약을 덮는다. 요약을 **언어마다 한 행**으로 나누고, 요약은 앱 언어로 받는다.

### Video 엔티티에 dict 로 싣지 않은 이유

처음 떠오르는 모양은 `Video.summaries: dict[str, str]` 이다. 그런데 목록 쿼리는 요약을
읽지 않는다(읽어서도 안 된다 — 메모리 규칙). 그러면 목록에서 읽은 Video를 `save()` 할 때
빈 dict 가 요약을 **조용히 지운다**. `description` 이 지연 로드인 것과 같은 함정이다.
그래서 실패 사유 표(`video_summary_status`)가 이미 쓰던 방식대로 **리포지토리 전용
메서드**로 다룬다 — `get_summaries` / `save_summary(video_id, lang, text)`(빈 값=삭제).
덤으로, 목록 쿼리(`SELECT videos.*`)가 요약 전문을 끌어오던 낭비도 사라졌다.

`videos.gemini_summary` 컬럼은 지우지 않았다. SQLite 컬럼 삭제는 테이블 재작성인데
그 위험에 비해 얻는 게 없다. 마이그레이션이 값을 `'ko'` 행으로 옮기고(지금까지는 전부
`locale="ko-KR"` 로 받았다), 이후로는 읽지도 쓰지도 않는다.

### 영어 요약 — 실측이 계획을 두 번 바꿨다

계획은 "YouTube를 영어로 열고 영어 칩(Summarize the video)을 누른다"였다.

1. **URL `hl=en` 과 브라우저 `locale="en-US"` 는 로그인 상태에서 무시된다.** 페이지가
   `lang="ko-KR"` 로, 버튼이 "질문하기"로 떴다 — **계정 언어**가 이긴다. `PREF` 쿠키의
   `hl` 을 덮어써야 바뀐다(`_force_page_language`). 한국어 요약에도 `hl=ko` 를 강제한다 —
   계정 언어가 영어인 사용자의 요약이 영어로 받아져 한국어 칸에 들어가는 것을 막는다.
   `gl`(지역)은 건드리지 않는다(영상 제공 여부가 바뀔 수 있다).
2. **영어 화면에서 영어 칩을 눌러도 한국어 영상에는 한국어로 답했다.** 영어 영상에는
   영어로 답했으니, 답의 언어가 화면이 아니라 영상을 따라가는 경우가 있다. 그래서 영어는
   칩을 누르지 않고 **입력칸에 "Summarize the video in English." 를 쓴다** — 한국어
   영상에도 영어로 답했다. 입력한 문장이 대화에 그대로 되풀이되므로 본문을 자를 기준점도
   된다(칩 목록의 "Summarize the video" 와 겹치지 않는 문장이라 마지막 출현이 곧 에코다).

한국어는 검증된 칩 방식을 그대로 둔다(영어 영상도 한국어로 요약해 왔다 — 기존 DB 가
증거다). 영어 칸에 한국어가 들어가는 것을 막으려고 **영어 답은 한글 비율 30% 이하**만
받는다(넘으면 "다른 언어로 답함"으로 재시도). 처음엔 10%였는데, 한국어 영상의 영어
요약에는 한글 고유명사가 섞일 수 있어 멀쩡한 요약을 거부할 수 있다(리뷰 지적). 실제로
한국어로 답하면 글자 대부분이 한글이라 30%로도 충분히 갈린다. 한국어 쪽은 검사하지 않는다 — 한국어
요약에 영어 용어가 섞이는 것은 정상이다.

영어 오류 문구("Something went wrong")만은 실측하지 못했다 — 오류가 나야 볼 수 있다.
틀려도 재시도를 한 번 덜 할 뿐이다.

### 생성 언어는 조립 때 한 번

앱 언어는 다시 시작해야 바뀐다. 그래서 `EnrichVideoHandler`·`StartDownloadHandler` 는
`summary_lang` 을 **생성자로** 받는다(`bootstrap.services.summary_language()`). application
은 `gui.text` 를 모르므로 이 방법이 의존 방향을 지킨다. 상세 화면의 ⟳ 는
`summary_generation_lang()` 으로 같은 규칙을 쓴다 — 둘이 어긋나면 자동으로 받은 요약과
⟳ 로 받은 요약이 다른 칸에 들어간다.

반면 **편집·상태 저장은 명시적으로 언어를 싣는다**(`UpdateVideoCommand.summary_lang`).
영어 화면에서 한국어 요약을 보고 고칠 수 있으므로 앱 언어로 짐작하면 틀린다.

### 동기화 — 구버전 op 호환

요약은 새 엔티티 `video_summary`(nkey = `link_key(video_key, 언어)`)로 동기화한다.
`video` 엔티티 필드에서는 `gemini_summary` 를 뺐다. 그런데 **업그레이드 전 기기가 남긴
op 에는 아직 그 필드가 있다.** 버리면 다른 PC에서 고친 요약이 조용히 사라진다 —
`VideoApplyHandler` 가 그 필드를 `'ko'` 행으로 적용한다. 새 마이그레이션 id 가 스키마
게이트를 올리므로 반대 방향(새 op → 구버전 앱)은 "앱 업데이트 필요"로 막힌다.

**옮겨 온 요약의 삭제.** 마이그레이션이 옮긴 요약(그리고 동기화를 켜기 전에 쓴 요약)은
`sync_identity` 에 없다. `record_delete` 는 식별자가 없으면 아무것도 기록하지 않으므로,
그대로면 한 기기에서 지운 요약이 다른 기기에 **영영 남는다**. 지울 때 식별자가 없으면
존재를 먼저 기록한 뒤 지운다(`RecordingVideoRepository.save_summary`).

**알려진 한계 — 오래된 구버전 op.** 필드 단위 LWW 는 `video.gemini_summary` 와
`video_summary(ko).summary` 를 **서로 다른 필드로** 판정한다. 그래서 아직 업그레이드하지
않은 기기가 오프라인에서 고친 요약이 늦게 도착하면, 그 사이 새 버전 기기가 더 나중에 고친
한국어 요약을 덮을 수 있다. 막으려면 구버전 필드를 적용할 때 새 키의 시계와 비교해야 하는데,
적용기 핸들러가 op 시계를 받지 않는 구조라 손이 크다. 모든 기기를 업그레이드하면 더는 생기지
않는 과도기 문제라 기록만 남긴다.

### 화면

언어 칩은 **다른 언어의 요약이 있을 때만** 뜬다(요약이 앱 언어 하나뿐이면 소음이다).
칩에는 요약이 있는 언어와 앱 언어만 올린다. 선택된 칩은 **굵은 글씨로만** 구분한다 —
상세 화면에는 테마 변경 연결이 없어서, 색을 칠하면 테마를 바꿨을 때 옛 색이 남는다.

요약 안내 문구(`text_format.py`)는 모듈 상수에서 **함수**로 바꿨다. `tr()` 은 앱 언어가
정해진 뒤 불려야 번역되는데 모듈 상수는 임포트 순간 평가된다. 이 문구들은 2단계에서
감싸지 않아 영어 화면에 한국어로 남아 있었다.
