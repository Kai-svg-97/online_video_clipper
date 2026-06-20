<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-06-20 | Updated: 2026-06-20 -->

# assets

## Purpose
앱 번들에 포함되는 정적 자산. 아이콘 파일이 현재 포함되어 있으며, PyInstaller 빌드 시 번들에 포함된다.

## Key Files

| File | Description |
|------|-------------|
| `icon.ico` | Windows 태스크바·윈도우 아이콘 (PyInstaller `.spec`에서 참조) |
| `icon.png` | 소스 아이콘 이미지 |

## For AI Agents

### Working In This Directory
- 자산 파일 접근은 항상 `utils.resources.get_resource_path("assets/...")` 경유 — PyInstaller 번들 환경 호환.
- 새 아이콘·이미지 추가 시 `packaging/online_video_clipper.spec`의 `datas` 목록에도 추가.

<!-- MANUAL: -->
