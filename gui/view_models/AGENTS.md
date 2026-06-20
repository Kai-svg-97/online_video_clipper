<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-06-20 | Updated: 2026-06-20 -->

# gui/view_models

## Purpose
MVVM의 ViewModel 레이어. Application 핸들러를 호출하고 결과를 Qt 시그널로 View에 전달한다.
각 Bounded Context별 ViewModel이 있으며, `QThread` 워커를 소유하고 `shutdown()`으로 종료 시 정리한다.

## Key Files

| File | Description |
|------|-------------|
| `library_vm.py` | `LibraryViewModel` — 영상 목록·카테고리·검색·태그·재생목록 아이템 로딩 |
| `download_vm.py` | `DownloadViewModel` — 다운로드 큐/이력 + 진행률 시그널 |
| `feed_vm.py` | `FeedViewModel` — 구독 피드 refresh, 채널별 영상, 구독 채널 카드 정보, `shutdown()` |
| `monitoring_vm.py` | `MonitoringViewModel` — 채널 구독 목록 |
| `clip_vm.py` | `ClipViewModel` — 클립 목록 + 추출 작업 |
| `playlist_vm.py` | `PlaylistViewModel` — 재생목록 관리·YouTube 연동 |

## For AI Agents

### Working In This Directory
- **모든 ViewModel은 `shutdown()` 메서드 제공** — `MainWindow.closeEvent`에서 호출됨.
- 네트워크/DB 작업은 `QThread` 워커에서 실행 — 메인 스레드 블로킹 금지.
- 에러는 `error_occurred = pyqtSignal(str)`로 View에 전달.
- `FeedViewModel`은 멀티워커(기본 4개) 사용 — `config.settings.MAX_CONCURRENT_FEED_WORKERS`.

### Common Patterns
```python
class SomeViewModel(QObject):
    data_loaded = pyqtSignal(list)
    error_occurred = pyqtSignal(str)

    def load(self):
        self._worker = SomeWorker(self._handler)
        self._worker.result.connect(self.data_loaded)
        self._worker.error.connect(self.error_occurred)
        self._worker.start()

    def shutdown(self):
        if self._worker and self._worker.isRunning():
            self._worker.terminate()
            self._worker.wait()
```

## Dependencies

### Internal
- `application/` — Command·Query 핸들러 (생성자 주입)
- `PyQt6.QtCore` — QObject, QThread, pyqtSignal

<!-- MANUAL: -->
