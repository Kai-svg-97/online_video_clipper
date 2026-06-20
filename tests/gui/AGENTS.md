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
