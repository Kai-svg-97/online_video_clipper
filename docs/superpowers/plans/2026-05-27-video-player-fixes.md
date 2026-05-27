# 영상 플레이어 버그 수정 및 기능 개선 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 영상 플레이어 컨트롤바 사라짐 버그, 미리보기 패널 자동 접힘, 상세보기 다운로드 버튼 미작동, 다운로드 파일명 품질 표기 4가지를 수정한다.

**Architecture:** 각 수정은 독립적이며 서로 영향을 주지 않는다. GUI 레이어 3곳(`video_player.py`, `library_panel.py`, `video_detail_panel.py`)과 인프라 레이어 1곳(`ytdlp_adapter.py`)을 수정한다.

**Tech Stack:** PyQt6, yt-dlp, Python 3.10+

---

## 수정 대상 파일

| 파일 | 변경 내용 |
|------|-----------|
| `gui/widgets/video_player.py` | `_VideoArea._layout_children()` 높이 계산 수정 |
| `gui/panels/library_panel.py` | `_PreviewPane` 자동 접힘 + `_on_back_from_detail` 조건부 표시 |
| `gui/panels/video_detail_panel.py` | `download_requested` 시그널 추가 및 연결 |
| `infrastructure/downloader/ytdlp_adapter.py` | 다운로드 후 파일명에 품질 레이블 삽입 |
| `tests/unit/domain/test_quality_label.py` | Fix 4 단위 테스트 |

---

## Task 1: 컨트롤바 사라짐 버그 수정

**Files:**
- Modify: `gui/widgets/video_player.py` (`_VideoArea._layout_children` 메서드)

**문제 원인:**  
`resizeEvent` 안에서 `setFixedHeight(new_h)` 를 호출한 직후 `_layout_children()` 을 실행하는데,  
이 시점에 `self.height()` 는 아직 이전(old) 높이를 반환한다.  
→ 컨트롤바 Y 좌표 = `old_height - 72` → 위젯 바깥으로 밀려 화면에서 사라짐.

- [ ] **Step 1: 수정 전 코드 확인 (읽기 전용)**

`gui/widgets/video_player.py` 의 `_VideoArea._layout_children` (약 342-346줄):
```python
def _layout_children(self) -> None:
    self._stack.setGeometry(self.rect())
    if self._bar is not None:
        self._bar.setGeometry(0, self.height() - self._BAR_H, self.width(), self._BAR_H)
        self._bar.raise_()
```

- [ ] **Step 2: `_layout_children` 수정**

`self.height()` 를 `self.heightForWidth(self.width())` 로 교체한다.  
`setGeometry` 도 `self.rect()` 대신 명시적 좌표로 변경해 일관성을 높인다.

```python
def _layout_children(self) -> None:
    h = self.heightForWidth(self.width())
    self._stack.setGeometry(0, 0, self.width(), h)
    if self._bar is not None:
        self._bar.setGeometry(0, h - self._BAR_H, self.width(), self._BAR_H)
        self._bar.raise_()
```

- [ ] **Step 3: 커밋**

```bash
git add gui/widgets/video_player.py
git commit -m "fix: 컨트롤바 Y 좌표를 heightForWidth 기준으로 계산해 리사이즈 시 사라짐 방지"
```

---

## Task 2: 미리보기 패널 자동 접힘

**Files:**
- Modify: `gui/panels/library_panel.py` (`_PreviewPane`, `LibraryPanel._on_back_from_detail`)

**동작 목표:**
- 영상을 선택하지 않았을 때 → 미리보기 패널 완전히 숨김(QSplitter 구획 접힘)
- 영상 선택 시 → 패널 표시
- 상세보기에서 목록으로 돌아올 때 → 선택된 영상이 있으면 표시, 없으면 숨김

- [ ] **Step 1: `_PreviewPane._show_empty()` 에 `self.hide()` 추가**

`_show_empty` 메서드 (약 1254-1261줄) 끝에 한 줄 추가:

```python
def _show_empty(self) -> None:
    self._current_dto = None
    self._player.load("", [], None)
    self._title_lbl.setText("영상을 선택하세요")
    self._meta_lbl.clear()
    _clear_layout(self._tags_container_layout)
    self._btn_browser.setEnabled(False)
    self._btn_detail.setEnabled(False)
    self.hide()   # ← 추가: 선택 대상 없을 때 패널 접기
```

- [ ] **Step 2: `_PreviewPane.show_video()` 에 `self.show()` 추가**

`show_video` 메서드 (약 1210줄) 첫 줄 바로 뒤에 추가:

```python
def show_video(self, dto: VideoDTO) -> None:
    self.show()   # ← 추가: 영상 선택 시 패널 펼치기
    self._current_dto = dto
    # ... 이하 기존 코드 그대로 ...
```

- [ ] **Step 3: `_PreviewPane` 에 `has_video` 프로퍼티 추가**

`stop_player` 메서드 아래에 추가:

```python
@property
def has_video(self) -> bool:
    """선택된 영상이 있으면 True."""
    return self._current_dto is not None
```

- [ ] **Step 4: `LibraryPanel._on_back_from_detail()` 조건부 show**

기존 코드:
```python
def _on_back_from_detail(self) -> None:
    self._detail_widget.stop_player()
    self._nav_stack.setCurrentIndex(0)
    self._preview.show()
```

수정 후:
```python
def _on_back_from_detail(self) -> None:
    self._detail_widget.stop_player()
    self._nav_stack.setCurrentIndex(0)
    if self._preview.has_video:   # 선택된 영상이 있을 때만 표시
        self._preview.show()
```

- [ ] **Step 5: 커밋**

```bash
git add gui/panels/library_panel.py
git commit -m "fix: 미리보기 패널, 선택 대상 없을 때 자동 접힘"
```

---

## Task 3: 상세보기 다운로드 버튼 연결

**Files:**
- Modify: `gui/panels/video_detail_panel.py` (시그널 선언 + 연결)
- Modify: `gui/panels/library_panel.py` (`_connect_signals`)

**문제 원인:**  
`_PreviewPane` 은 `self._player.download_requested.connect(self.download_requested.emit)` 로 올바르게 연결되어 있으나,  
`VideoDetailWidget` 은 `download_requested` 시그널 자체가 없고 연결도 없다.  
→ 상세보기에서 다운로드 버튼을 눌러도 아무 동작 없음.

- [ ] **Step 1: `VideoDetailWidget` 에 `download_requested` 시그널 추가**

`video_detail_panel.py` 의 `VideoDetailWidget` 클래스 시그널 선언부 (약 126-128줄):

```python
class VideoDetailWidget(QWidget):
    back_requested       = pyqtSignal()
    tag_filter_requested = pyqtSignal(object, str)   # (UUID, str)
    tags_updated         = pyqtSignal(object, object)  # (UUID, list[str])
    download_requested   = pyqtSignal(str, str, object)  # ← 추가 (url, title, DownloadSettings)
```

- [ ] **Step 2: `_setup_skeleton()` 에서 InlinePlayer 시그널 연결**

`_setup_skeleton` 의 InlinePlayer 생성 직후 (약 170-171줄):

```python
self._player = InlinePlayer(left_w)
self._player.playback_failed.connect(self._on_play_failed)
self._player.download_requested.connect(self.download_requested.emit)  # ← 추가
```

- [ ] **Step 3: `LibraryPanel._connect_signals()` 에서 연결**

`library_panel.py` 의 `_connect_signals` (약 1504-1506줄) 아래에 추가:

```python
self._detail_widget.back_requested.connect(self._on_back_from_detail)
self._detail_widget.tag_filter_requested.connect(self._on_tag_filter_requested)
self._detail_widget.tags_updated.connect(self._on_detail_tags_updated)
self._detail_widget.download_requested.connect(self.download_requested.emit)  # ← 추가
```

- [ ] **Step 4: 커밋**

```bash
git add gui/panels/video_detail_panel.py gui/panels/library_panel.py
git commit -m "fix: 상세보기 다운로드 버튼 — download_requested 시그널 연결 누락 수정"
```

---

## Task 4: 다운로드 파일명 품질 레이블 삽입

**Files:**
- Modify: `infrastructure/downloader/ytdlp_adapter.py`
- Create: `tests/unit/domain/test_quality_label.py`

**동작 목표:**
- 다운로드 완료 후 실제 다운로드된 영상의 `height` 를 yt-dlp info 딕셔너리에서 읽는다
- 높이 → 레이블 매핑: 2160↑→`UHD (4K)`, 1440↑→`QHD (2K)`, 1080↑→`FHD`, 720↑→`HD`, 480↑→`SD`, 그 외→`{h}p`
- 파일 이름 변경: `제목.mp4` → `제목 [FHD].mp4`
- MP3/M4A 오디오 포맷은 레이블 없음

- [ ] **Step 1: 테스트 파일 작성**

`tests/unit/domain/test_quality_label.py` 를 새로 생성:

```python
"""ytdlp_adapter 의 _height_to_quality_label 단위 테스트."""
import pytest
from infrastructure.downloader.ytdlp_adapter import _height_to_quality_label


class TestHeightToQualityLabel:
    def test_4k(self):
        assert _height_to_quality_label(2160) == "UHD (4K)"

    def test_above_4k(self):
        assert _height_to_quality_label(4320) == "UHD (4K)"

    def test_qhd(self):
        assert _height_to_quality_label(1440) == "QHD (2K)"

    def test_fhd(self):
        assert _height_to_quality_label(1080) == "FHD"

    def test_hd(self):
        assert _height_to_quality_label(720) == "HD"

    def test_sd(self):
        assert _height_to_quality_label(480) == "SD"

    def test_below_sd(self):
        assert _height_to_quality_label(360) == "360p"

    def test_none_returns_empty(self):
        assert _height_to_quality_label(None) == ""
```

- [ ] **Step 2: 테스트 실행 — FAIL 확인**

```bash
pytest tests/unit/domain/test_quality_label.py -v
```
예상 결과: `ImportError` 또는 `FAILED` (함수 미존재)

- [ ] **Step 3: `_height_to_quality_label` 함수 추가**

`ytdlp_adapter.py` 의 `class YtDlpAdapter:` 선언 바로 위에 모듈 레벨 함수 추가:

```python
def _height_to_quality_label(height: int | None) -> str:
    """픽셀 높이를 사람이 읽기 쉬운 품질 레이블로 변환한다."""
    if height is None:
        return ""
    if height >= 2160:
        return "UHD (4K)"
    if height >= 1440:
        return "QHD (2K)"
    if height >= 1080:
        return "FHD"
    if height >= 720:
        return "HD"
    if height >= 480:
        return "SD"
    return f"{height}p"
```

- [ ] **Step 4: 테스트 재실행 — PASS 확인**

```bash
pytest tests/unit/domain/test_quality_label.py -v
```
예상 결과: 8개 테스트 모두 `PASSED`

- [ ] **Step 5: `download()` 메서드에 파일명 변경 로직 추가**

`ytdlp_adapter.py` 의 `download()` 메서드에서 `return Path(self._last_filepath)` 바로 앞을 수정한다.

기존 코드 (약 129-140줄):
```python
self._last_filepath: str = ""
with yt_dlp.YoutubeDL(opts) as ydl:
    info = ydl.extract_info(url, download=True)
    if info:
        rd = (info.get("requested_downloads") or [{}])[0]
        self._last_filepath = (
            rd.get("filepath")
            or info.get("filepath")
            or ydl.prepare_filename(info)
        )

return Path(self._last_filepath)
```

수정 후:
```python
self._last_filepath: str = ""
with yt_dlp.YoutubeDL(opts) as ydl:
    info = ydl.extract_info(url, download=True)
    if info:
        rd = (info.get("requested_downloads") or [{}])[0]
        self._last_filepath = (
            rd.get("filepath")
            or info.get("filepath")
            or ydl.prepare_filename(info)
        )
        # 오디오 포맷이 아닐 때만 품질 레이블을 파일명에 추가
        if settings.format not in (MediaFormat.MP3, MediaFormat.M4A):
            actual_height = rd.get("height") or info.get("height")
            label = _height_to_quality_label(actual_height)
            if label:
                p = Path(self._last_filepath)
                new_path = p.with_name(f"{p.stem} [{label}]{p.suffix}")
                try:
                    if p.exists() and not new_path.exists():
                        p.rename(new_path)
                        self._last_filepath = str(new_path)
                except OSError:
                    pass  # 이름 변경 실패 시 원본 경로 유지

return Path(self._last_filepath)
```

- [ ] **Step 6: 전체 테스트 실행**

```bash
pytest tests/ -v
```
예상 결과: 기존 테스트 포함 전체 PASSED

- [ ] **Step 7: 커밋**

```bash
git add infrastructure/downloader/ytdlp_adapter.py tests/unit/domain/test_quality_label.py
git commit -m "feat: 다운로드 파일명에 실제 품질 레이블(UHD/QHD/FHD/HD/SD) 자동 삽입"
```

---

## Task 5: 최종 확인 및 푸시

- [ ] **Step 1: 전체 테스트 실행**

```bash
pytest tests/ -v
```

- [ ] **Step 2: 푸시**

```bash
git push origin main
```
