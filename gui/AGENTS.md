<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-06-20 | Updated: 2026-06-20 -->

# gui

## Purpose
프레젠테이션 레이어. PyQt6 기반 MVVM 패턴으로 구현된 GUI 전체.
모든 네트워크·DB 작업은 `QThread` 워커에서 실행되고, 결과는 Qt 시그널로 메인 스레드에 전달된다.

## Key Files

| File | Description |
|------|-------------|
| `__init__.py` | 패키지 마커 |
| `main_window.py` | 루트 윈도우 — 사이드바 네비게이션, 패널 스택, `closeEvent`에서 ViewModel `shutdown()` 호출 |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `panels/` | 각 기능 화면 패널 (라이브러리·다운로드·모니터링·통계·상세·피드·설정) (see `panels/AGENTS.md`) |
| `view_models/` | ViewModel — Application 핸들러 호출 + Qt 시그널로 UI 갱신 (see `view_models/AGENTS.md`) |
| `widgets/` | 재사용 위젯 (인라인 비디오 플레이어) (see `widgets/AGENTS.md`) |
| `dialogs/` | 독립 다이얼로그 (YouTube 인증·일괄 다운로드) (see `dialogs/AGENTS.md`) |
| `themes/` | 테마 시스템 — ThemeManager 싱글턴, 토큰, QSS 생성기 (see `themes/AGENTS.md`) |

## For AI Agents

### Working In This Directory
- **GUI는 메인 스레드 전용** — 네트워크·I/O를 메인 스레드에서 직접 호출하지 말 것.
- ViewModel은 `QThread` 워커를 소유하며, `shutdown()` 메서드로 종료 시 정리.
- `main_window.py`의 `closeEvent`에서 모든 ViewModel `shutdown()` 호출 확인.
- **GUI 파일 수정 후 반드시 `/verify` 스킬 실행** — 앱이 실제로 실행·표시되는지 확인.
- 썸네일: `QListView` + `QAbstractItemModel` + 델리게이트 방식, `QListWidget` 사용 금지.
- `QPixmapCache.setCacheLimit(30720)` (30 MB), LRU 썸네일 캐시 최대 100개.

### Testing Requirements
- `tests/gui/` — pytest-qt 스모크 테스트 (패널이 크래시 없이 뜨는지 확인).

### Common Patterns
```python
# ViewModel → 워커 QThread → Qt 시그널 패턴
class SomeViewModel(QObject):
    data_loaded = pyqtSignal(list)
    error_occurred = pyqtSignal(str)

    def load(self):
        worker = SomeWorker(self._handler)
        worker.finished.connect(self.data_loaded)
        worker.error.connect(self.error_occurred)
        worker.start()

    def shutdown(self):
        if self._worker and self._worker.isRunning():
            self._worker.terminate()
            self._worker.wait()
```

## Dependencies

### Internal
- `application/` — Command·Query 핸들러 (ViewModel이 직접 호출)
- `config/settings.py` — 테마, 경로 설정

### External
- `PyQt6` — QObject, QThread, QMediaPlayer, QListView, QAbstractItemModel
- `gui/themes/` — ThemeManager, build_qss

<!-- MANUAL: -->
