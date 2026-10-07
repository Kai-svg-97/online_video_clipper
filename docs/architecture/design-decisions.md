# 설계 결정 기록

> **왜 이렇게 만들었는지**와 **어떤 함정을 실제로 밟았는지**를 담는다 — 같은 함정을 다시
> 밟지 않기 위한 기록이므로, 실측으로 확인한 사실은 반드시 남긴다.
>
> 한 파일이 1,700줄을 넘겨 주제별로 나눴다(2026-09-30). **이 파일은 목차다** — 새 기록은
> 아래 주제 파일 중 맞는 곳에 추가하고, 새 절을 만들었으면 여기 목차에도 한 줄 더한다.
> 맞는 주제가 없으면 새 주제 파일을 만들고 이 표에 올린다.

| 주제 | 파일 |
| --- | --- |
| 기반 — 레이어·스레드 원칙, 시작 성능, 데이터 안전, CI | [`decisions/foundations.md`](decisions/foundations.md) |
| Qt 수명 — 프로세스가 조용히 죽는 경로 | [`decisions/qt-lifetime.md`](decisions/qt-lifetime.md) |
| 라이브러리·검색·가져오기·구독 | [`decisions/library.md`](decisions/library.md) |
| 재생·스트리밍·자막·음성 인식 | [`decisions/playback.md`](decisions/playback.md) |
| 노래·가사·앨범 | [`decisions/song.md`](decisions/song.md) |
| Gemini 요약 | [`decisions/gemini.md`](decisions/gemini.md) |
| 다운로드·자동 업데이트 | [`decisions/download-update.md`](decisions/download-update.md) |
| 클라우드 동기화 | [`decisions/sync.md`](decisions/sync.md) |
| 다국어화 | [`decisions/i18n.md`](decisions/i18n.md) |
| 설명서·갈무리 | [`decisions/manual.md`](decisions/manual.md) |
| 코드 구조 — 큰 파일을 나누는 방식 | [`decisions/code-structure.md`](decisions/code-structure.md) |
| 테스트 — 느림과 흔들림의 원인 | [`decisions/testing.md`](decisions/testing.md) |

## [기반 — 레이어·스레드 원칙, 시작 성능, 데이터 안전, CI](decisions/foundations.md)

- 스플래시는 창이 뜬 뒤에 닫는다 — 시작 체감 (2026-10)
- DB 백업은 파일을 복사하는 일이 아니다 (v1.28)
- 화면은 인프라를 임포트하지 않는다 — 포트 + 조립 루트 주입
- CI 첫 실행이 드러낸 것 — 개발 PC가 가리던 결함 셋
- 항목별 기록: 번들 YouTube OAuth 로그인 · GUI on main thread · yt-dlp progress hooks · Aggregates own state changes · Repositories are interfaces in `domain/` · Domain Events over direct calls · ffmpeg resolved via `get_ffmpeg_path()` · Ports over concrete infra in application · 단일 인스턴스 가드 · GUI→infra 예외 경계 · Phase 2 성능 최적화 (YouTube OAuth 및 Database 지연 로딩) · 버그 수정 기록

## [Qt 수명 — 프로세스가 조용히 죽는 경로](decisions/qt-lifetime.md)

- 실행 중 애니메이션을 위젯의 자식으로 두면 프로세스가 죽는다 (2026-09)
- 해결: ThemeManager 싱글턴 람다 연결 (2026-09)
- 델리게이트 paint() 안의 예외는 앱을 통째로 끈다 (v1.27.1)

## [라이브러리·검색·가져오기·구독](decisions/library.md)

- 트리 고정 헤더 — 지금 어느 폴더 안인지 잃지 않게 (2026-10)
- 라이브러리 무한 스크롤 — 쪽을 넘긴 뒤의 재조회 (v1.27.1)
- "지난번 이후"를 날짜로 재지 않는다 (v1.28)
- 북마크는 우리가 거르지 않는다 (v1.28)
- 저장된 검색은 값이 아니라 **프리셋 키**를 담는다 (v1.29)
- 저장된 검색은 사용자를 막아 세우지 않는다 (v1.29)
- 깨진 항목 하나가 목록 전체를 막지 않는다 (v1.29)
- 워치 폴더 — 반쯤 담는 것이 못 담는 것보다 나쁘다 (v1.29)
- 항목별 기록: 추천 영상 스트립 (목록 아래 접이식) · 라이브러리 밖 영상의 카테고리 지정 (요약·가사 잠금 해제) · 브라우저 URL → 카테고리 트리 드롭 · 추천 영상 미리 받기(무한 스크롤) · 라이브러리 정리(중복·사라진 파일) · 피드/채널 메타데이터 보강 · 라이브러리 가져오기/내보내기(카테고리 단위 zip 패키지) · 영상 검색 (부분 일치) · 검색 입력 응답성 (키 입력이 밀리던 문제) · 목록·검색 로딩 스켈레톤 (v1.22.0 체감 성능 개선 Phase 1 Step 3) · 등록 시 요약·가사 자동 보강
- `QFont("", N)`가 느린 비트맵 글꼴로 풀린다 — 앱 글꼴 헬퍼 (2026-10)

## [재생·스트리밍·자막·음성 인식](decisions/playback.md)

- 전사 모델을 "받아 뒀는지" 묻는 두 가지 방법 (v1.27.1)
- 음성 인식 중단 — 단계를 구분해야 버튼이 거짓말을 하지 않는다 (v1.27.1)
- 자막 번역은 묶어 보내되, 정렬이 깨지면 되돌린다 (v1.29)
- 앱 내 재생이 항상 360p였던 진짜 이유 (v1.32)
- 먼 seek 뒤 '소리만 나오고 영상이 안 나오는' 반쪽 스트림 — 입력 하나만 포기하면 복구가 안 돈다
- 먼 seek이 막히던 진짜 원인 — yt-dlp가 JS 챌린지를 못 풀었다(낡은 yt-dlp + node 미사용)
- 항목별 기록: 지금 재생 중 미니바 · 영상 자막 (언어 선택 · 자동 번역 · 두 줄 동시 표시) · 읽는 글(요약·가사) 글자 크기 · 재생 컨트롤 아이콘 크기 · 이어보기(재생 위치) · 스트리밍 재생 실패 → 브라우저 튕김 (해결)

## [노래·가사·앨범](decisions/song.md)

- 항목별 기록: 노래 정보(song 컨텍스트) · 가사 검색 후보 목록 (|출처|가수|제목|가사 첫째 줄|싱크|) · 가사 자막 표시 · 싱크 조정 · 앨범 보기 (음악 카테고리 전용, 파생 그룹)

## [Gemini 요약](decisions/gemini.md)

- Gemini 요약을 언어별로 (v1.33 준비)
- 항목별 기록: Gemini AI 요약 자동 메모 저장 · Gemini 요약 — Playwright 대기 함정과 영상별 기능 제공 여부

## [다운로드·자동 업데이트](decisions/download-update.md)

- 게이트에 걸린 다운로드는 '대기 중'이라고 말한다 (v1.27.1)
- 자동 업데이트 UI — 배지·진행률·무중단에 가까운 설치 (v1.30.0)
- 항목별 기록: 자동 업데이트(백그라운드 다운로드 + 종료 시 설치) · 다운로드 403 Forbidden + 조각난 `.part` 파일 (해결)

## [클라우드 동기화](decisions/sync.md)

- 항목별 기록: 클라우드 동기화 캡처 (레코드 단위 oplog CRDT, 구현 중) · 미디어/썸네일 파일 동기화 (oplog와 별개 서브시스템, 구현 중) · 클라우드 provider 어댑터 (로컬 폴더 / Google Drive / OneDrive) · 컴팩션 + 스냅샷 부트스트랩 (구현 중) · 미디어 경로 이식성 (머신 간 동기화 대비)

## [다국어화](decisions/i18n.md)

- 다국어화 1단계 — 번역보다 먼저 한 일 (v1.33 준비)
- 다국어화 2단계 — 영어 화면 (v1.33 준비)
- 감싸지 않은 표시 문자열 정리 (v1.34 준비)
- 영어 설명서 (v1.34 준비)
- 애플리케이션·인프라의 표시 문구 (v1.35 준비)

## [설명서·갈무리](decisions/manual.md)

- 설명서는 원본을 하나만 둔다 (v1.32)
- 갈무리가 사용자의 즐겨찾기를 담아 배포됐다 (v1.32.1)

## [코드 구조 — 큰 파일을 나누는 방식](decisions/code-structure.md)

- 큰 파일 넷을 조립부 + mixin으로 (2026-09-30)

## [테스트 — 느림과 흔들림의 원인](decisions/testing.md)

- 전체 시험 742초 → 443초 (2026-09-30)
