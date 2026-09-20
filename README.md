# YouTube Content Manager

YouTube를 비롯한 1,000개 이상의 동영상 플랫폼을 다루는 **개인용 콘텐츠 관리 데스크톱 앱**입니다.
받아서 쌓아 두는 도구가 아니라, 모으고·분류하고·찾고·보는 일을 한 화면에서 끝내는 것이 목표입니다.

> 📘 **화면별 사용법과 갈무리는 [상세 설명서](docs/manual.md)에 있습니다.**
> 앱에서는 아무 화면에서나 **F1**, 또는 **설정 → 도움말 → 상세 설명서 열기**.

---

## 무엇을 할 수 있나

| | |
| --- | --- |
| **라이브러리** | 카테고리(계층 트리)·태그로 분류, FTS5 전문 검색, 복합 필터, 저장된 검색 |
| **앱 내 재생** | 내려받지 않고 **1080p 스트리밍 재생**, 자막 2줄 동시 표시, 구간 건너뛰기, 이어보기 |
| **다운로드** | 단일·재생목록·채널 전체, 화질/형식 선택, 병렬 큐, 자동 재시도 |
| **클립 추출** | 구간을 지정해 ffmpeg로 잘라 저장 |
| **채널 모니터링** | 신규 영상 자동 감지, 조건부 자동 다운로드, 트레이 알림 |
| **통계** | 카테고리·채널별 분포와 추이 |
| **그 밖에** | 11가지 테마, OneDrive·Google Drive 동기화, 음성 인식 자막, 가사 연동 |

---

## 설치와 실행

**요구 사항** — Python 3.10 이상, ffmpeg(시스템 PATH 또는 `bin/` 폴더)

```bash
pip install -r requirements.txt
python main.py
```

배포용 설치 파일에는 Python·ffmpeg·yt-dlp가 모두 들어 있어 따로 설치할 것이 없습니다.

| 플랫폼 | 빌드 명령 | 결과물 |
| --- | --- | --- |
| Windows | `.\scripts\build_windows.ps1` | `dist/YouTubeContentManager-setup.exe` |
| Linux | `bash scripts/build_linux.sh` | `dist/YouTubeContentManager-x86_64.AppImage` |

애플리케이션 데이터(DB·다운로드·로그)는 OS 표준 경로에 저장됩니다 — Windows는
`%APPDATA%\YouTubeContentManager\`, Linux는 `~/.local/share/YouTubeContentManager/`.

---

## 개발

```bash
pytest                  # 전체 테스트
pytest tests/unit/      # 단위
pytest tests/gui/ -v    # GUI 스모크
ruff check .            # 린트
```

설명서를 고쳤다면 브라우저용 HTML도 다시 만듭니다.

```bash
python scripts/capture_screenshots.py   # 화면 갈무리 갱신(선택)
python scripts/build_manual.py          # docs/manual.md → docs/manual/index.html
```

### 아키텍처

Domain-Driven Design 레이어드 구조이고, 의존 방향은 한 줄로 요약됩니다 —
**`gui → application → domain ← infrastructure`**.

```
main.py          진입점(순서만)          bootstrap/    조립 루트
domain/          순수 도메인             application/  유스케이스
infrastructure/  SQLite·yt-dlp·ffmpeg    gui/          PyQt6 (MVVM)
```

| 찾는 것 | 문서 |
| --- | --- |
| 파일별 책임·레이어 구조 | [`docs/architecture/file-map.md`](docs/architecture/file-map.md) |
| 설계 근거와 실제로 밟은 함정 | [`docs/architecture/design-decisions.md`](docs/architecture/design-decisions.md) |
| 기여 규칙·코딩 제약 | [`CLAUDE.md`](CLAUDE.md) |
| 요구사항 / DDD 설계 | `planning/youtube_content_manager_prd.md` · `planning/ddd_design.md` |
| 빌드·패키징 | [`docs/packaging-windows.md`](docs/packaging-windows.md) · [`-linux.md`](docs/packaging-linux.md) · [`-macos.md`](docs/packaging-macos.md) |
