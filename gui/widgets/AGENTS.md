<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-06-20 | Updated: 2026-06-20 -->

# gui/widgets

## Purpose
재사용 가능한 커스텀 위젯. 현재 인라인 비디오 플레이어(`video_player.py`) 하나가 포함된다.

## Key Files

| File | Description |
|------|-------------|
| `__init__.py` | 패키지 마커 |
| `video_player.py` | `InlinePlayer` — QMediaPlayer 기반 하이브리드 스트리밍 플레이어. 화질별 muxed 즉시 스트리밍 vs ffmpeg 병합 후 로컬 재생 모드 선택 |

## For AI Agents

### Working In This Directory
- **하이브리드 스트리밍 화질 모드**:
  - "자동·360p·240p": muxed URL 즉시 스트리밍 (`merge=False`)
  - "1080p·720p·480p": `bestvideo[avc1]+bestaudio[mp4a]` → ffmpeg 병합 → 임시 mp4 → 로컬 재생 (`merge=True`)
- 임시 파일(`ovc_stream_*`)은 `stop()`·`load()`·화질 변경 시 정리 필수.
- 화질 변경 시 현재 위치 저장 → `mediaStatusChanged(LoadedMedia/BufferedMedia)` 후 이어보기 seek.
- WMF 호환을 위해 avc1(H.264) + m4a 코덱 우선.
- `_StreamWorker`가 두 모드를 운용 — QThread에서 실행.

### Testing Requirements
- GUI 스모크 테스트: 위젯 초기화 확인.
- 실제 스트리밍 테스트는 `/verify` 스킬로 수동 확인.

## Dependencies

### External
- `PyQt6.QtMultimedia` — QMediaPlayer, QAudioOutput
- `infrastructure/ffmpeg/` — 병합 모드 ffmpeg 실행

<!-- MANUAL: -->
