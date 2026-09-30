<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-06-20 | Updated: 2026-06-20 -->

# tests/gui

## Purpose
PyQt6 GUI 스모크 테스트. pytest-qt를 사용하여 각 패널·다이얼로그가 크래시 없이 초기화·표시되는지 확인한다.

## Key Files

| File | Description |
|------|-------------|
| `__init__.py` | 패키지 마커 |
| `conftest.py` | pytest-qt 픽스처 설정, Mock ViewModel 등 |
| `test_smoke.py` | 패널별 스모크 테스트 — 위젯 초기화 + `show()` 확인 |

## For AI Agents

### Working In This Directory
- 스모크 테스트는 **기능 정확성이 아닌 크래시 유무**만 확인.
- 실제 ViewModel 대신 Mock 사용 — 네트워크·DB 불필요.
- 디스플레이 환경 필요 (`QApplication` 인스턴스).
- GUI 스모크 실행: `pytest tests/gui/ -v`
- **부모 없이 만든 위젯은 반드시 `qtbot.addWidget(...)`에 맡긴다.** 안 맡기면 순환 참조로
  세션 끝까지 살아남고, 뒤의 테마 시험이 전역 QSS를 바꿀 때 그 위젯을 **전부** 다시 칠한다
  (실측: 누수 위젯 9,701개 → `setStyleSheet` 한 번에 11초, 테마 시험 하나가 36초).
  `conftest.py`의 autouse 픽스처가 시험마다 `DeferredDelete`를 집행하지만, 등록되지 않은
  위젯은 거기서도 지워지지 않는다.
- **키 입력 시험은 창이 활성화될 때까지 기다린다.** `waitExposed`는 노출만 기다린다 —
  활성화는 비동기로 늦게 와서, 부하 중에는 `QApplication.focusWidget()`이 None이다.
  `activateWindow()` 후 `qtbot.waitUntil(w.isActiveWindow)`, 포커스 판정은 활성 여부와 무관한
  `widget.window().focusWidget()`으로 한다. `sleep`으로 때우지 않는다.
- **창 크기를 가정하지 않는다.** 러너 화면이 작으면 창 관리자가 창을 줄인다 — 기대값은
  요청한 크기가 아니라 `window.height()` 같은 **실제** 값으로 계산한다.

### Common Patterns
```python
def test_library_panel_shows(qtbot, mock_library_vm):
    panel = LibraryPanel(mock_library_vm)
    qtbot.addWidget(panel)
    panel.show()
    assert panel.isVisible()
```

## Dependencies

### External
- `pytest-qt` — qtbot 픽스처

<!-- MANUAL: -->
