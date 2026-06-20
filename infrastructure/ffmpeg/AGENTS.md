<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-06-20 | Updated: 2026-06-20 -->

# infrastructure/ffmpeg

## Purpose
ffmpeg 클립 추출 및 썸네일 생성 어댑터. `IClipExtractor` 포트를 구조적으로 만족한다.
번들 ffmpeg(`bin/ffmpeg.exe`)을 우선 사용하고 없으면 시스템 PATH에서 탐색한다.

## Key Files

| File | Description |
|------|-------------|
| `__init__.py` | 패키지 마커 |
| `ffmpeg_adapter.py` | `FfmpegAdapter` — `IClipExtractor` 구현 |

## For AI Agents

### Working In This Directory
- ffmpeg 경로는 `utils.resources.get_ffmpeg_path()` 사용 — 하드코딩 금지.
- 비디오 플레이어의 하이브리드 스트리밍에서도 이 어댑터를 사용 (DASH 영상+오디오 병합).
- 출력 파일 경로는 항상 `utils.resources` 또는 `config.settings`에서 가져온 디렉터리 사용.

### Key Methods (IClipExtractor)
| Method | Purpose |
|--------|---------|
| `extract_clip(source_path, time_range, output_path)` | 시간 범위 클립 추출 |
| `extract_thumbnail(source_path, timestamp_sec, output_path, width, height)` | 특정 시각 썸네일 추출 |

## Dependencies

### External
- `ffmpeg-python` — ffmpeg 프로세스 래퍼

<!-- MANUAL: -->
