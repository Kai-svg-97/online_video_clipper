# YouTube Content Manager

YouTube 및 1,000개 이상의 동영상 플랫폼을 지원하는 개인용 콘텐츠 관리 데스크탑 애플리케이션입니다.  
단순 다운로드 도구를 넘어, 라이브러리 관리·클립 추출·채널 모니터링을 하나의 GUI에서 제공합니다.

---

## 주요 기능

### 라이브러리 관리
- URL 입력 또는 클립보드 자동 감지로 영상 추가
- 카테고리(계층형 트리) / 태그로 영상 분류
- 시청 여부, 즐겨찾기 표시 및 필터
- 제목·설명·메모 편집
- JSON/CSV 내보내기 및 플레이리스트·브라우저 북마크 일괄 임포트

### 다운로드
- 단일 영상, 플레이리스트, 채널 전체 다운로드
- 품질(2160p~360p / best / worst) 및 포맷(mp4, mkv, webm, mp3, m4a) 선택
- 병렬 다운로드 큐 (동시 다운로드 수 1~8 설정)
- 자막·썸네일·메타데이터 개별 다운로드
- 실패 시 자동 재시도, 다운로드 이력 영구 저장

### 클립 구간 추출
- 영상의 특정 구간 타임스탬프 북마크
- ffmpeg로 지정 구간 추출·저장
- 클립 미리보기 썸네일 자동 생성

### 채널 구독 & 모니터링
- 채널 URL 등록 → RSS/폴링으로 신규 영상 자동 감지
- 채널별 자동 다운로드 규칙 (키워드, 최소/최대 재생시간 필터)
- 시스템 트레이 알림

### 검색 & 필터
- SQLite FTS5 전문 검색 (제목·설명·메모)
- 날짜 범위, 영상 길이, 채널, 다운로드 여부, 즐겨찾기 복합 필터
- 태그 클릭으로 즉시 필터링

### 재생 연동
- 외부 플레이어(VLC, mpv, 기본 플레이어) 실행
- yt-dlp stream URL을 통한 온라인 스트리밍 재생
- 마지막 재생 위치 기억

### 통계 대시보드
- 총 다운로드 수 및 누적 용량
- 카테고리/태그별 분포 차트
- 최근 활동 로그

---

## 설치 및 실행

### 요구 사항

- Python 3.10 이상
- ffmpeg (시스템 PATH에 있거나 `bin/` 폴더에 위치)

### 의존성 설치

```bash
pip install -r requirements.txt
```

### 실행

```bash
python main.py
```

---

## 개발 명령어

```bash
# 테스트 전체 실행
pytest

# 단위 테스트만
pytest tests/unit/

# 통합 테스트만
pytest tests/integration/

# 린트
ruff check .

# 포맷
ruff format .
```

---

## 배포 빌드

| 플랫폼 | 명령 | 출력 |
|--------|------|------|
| Windows | `.\scripts\build_windows.ps1` | `dist/YouTubeContentManager-setup.exe` |
| Linux | `bash scripts/build_linux.sh` | `dist/YouTubeContentManager-x86_64.AppImage` |

빌드 패키지에는 Python, ffmpeg, yt-dlp가 모두 포함되어 사용자 별도 설치가 불필요합니다.

---

## 아키텍처

Domain-Driven Design (DDD) 레이어드 아키텍처를 적용합니다.

```
GUI (PyQt6 + MVVM)
    ↓
Application (Commands / Queries)
    ↓
Domain (Aggregates, Entities, Value Objects)
    ↑
Infrastructure (SQLite, yt-dlp, ffmpeg)
```

상세 설계는 `planning/ddd_design.md`, 요구사항 전체는 `planning/requirements.md`를 참고하세요.

---

## 사용자 데이터 경로

애플리케이션 데이터(DB, 다운로드, 로그)는 OS 표준 경로에 저장됩니다.

| OS | 경로 |
|----|------|
| Windows | `%APPDATA%\YouTubeContentManager\` |
| Linux | `~/.local/share/YouTubeContentManager/` |
