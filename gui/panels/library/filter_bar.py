"""목록 위 복합 필터 막대 — 접었다 펴는 한 줄.

엔진(`SearchQuery`·리포지토리 SQL)에는 처음부터 날짜·길이·채널·다운로드 여부 필터가
있었는데 **화면에서 넘기는 곳이 없어** 쓸 수 없었다. 이 막대가 그 연결이다.

**기본은 접힌 상태다.** 늘 펴 두면 목록이 그만큼 좁아지는데, 대부분의 시간에는
필터를 쓰지 않는다. 대신 필터가 걸려 있으면 **접혀 있어도 알 수 있게** 토글 버튼에
개수를 적는다 — 그러지 않으면 "왜 영상이 몇 개 없지"의 원인을 찾을 수 없다.

날짜·길이는 직접 입력이 아니라 프리셋이다(`domain/library/filters.py` 참고).
"""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QWidget,
)

from domain.library.filters import (
    DATE_PRESETS,
    DOWNLOAD_PRESETS,
    DURATION_PRESETS,
    WATCHED_PRESETS,
    describe,
    resolve_date_preset,
    resolve_download_preset,
    resolve_duration_preset,
    resolve_watched_preset,
)
from gui.panels.library.formatting import _t


class FilterBar(QWidget):
    """복합 필터 입력 한 줄. 값이 바뀌면 `changed`를 낸다."""

    changed = pyqtSignal()
    # 저장된 검색 — 이 막대는 조건만 알고, 어디에 담는지는 패널이 정한다.
    save_requested = pyqtSignal()
    apply_requested = pyqtSignal(object)   # SavedSearch

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(4, 2, 4, 6)
        row.setSpacing(6)

        self._date = self._combo(DATE_PRESETS, "업로드")
        self._duration = self._combo(DURATION_PRESETS, "길이")
        self._download = self._combo(DOWNLOAD_PRESETS, "다운로드")
        self._watched = self._combo(WATCHED_PRESETS, "시청")

        self._channel = QLineEdit()
        self._channel.setPlaceholderText("채널 이름…")
        self._channel.setClearButtonEnabled(True)
        self._channel.setFixedWidth(150)
        # 입력 중마다 조회하면 글자마다 DB를 읽는다 — 엔터·포커스 이동에만 건다.
        self._channel.editingFinished.connect(self.changed)

        self._favorite = QCheckBox("즐겨찾기만")
        self._favorite.checkStateChanged.connect(self.changed)

        self._save = QPushButton("검색 저장…")
        self._save.setFixedWidth(84)
        self._save.setToolTip("지금 조건에 이름을 붙여 저장합니다")
        self._save.clicked.connect(self.save_requested)

        self._reset = QPushButton("필터 초기화")
        self._reset.setFixedWidth(90)
        self._reset.clicked.connect(self.reset)

        for widget in (
            self._label("업로드"), self._date,
            self._label("길이"), self._duration,
            self._label("다운로드"), self._download,
            self._label("시청"), self._watched,
            self._channel, self._favorite,
        ):
            row.addWidget(widget)
        row.addStretch()
        row.addWidget(self._save)
        row.addWidget(self._reset)

    # ── 조립 도우미 ───────────────────────────────────────────────

    def _combo(self, presets, tooltip: str) -> QComboBox:
        combo = QComboBox()
        for row in presets:
            combo.addItem(row[1], row[0])
        combo.setToolTip(tooltip)
        combo.currentIndexChanged.connect(self.changed)
        return combo

    def _label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(f"font-size: 9pt; color: {_t().text_secondary};")
        return lbl

    # ── 값 ────────────────────────────────────────────────────────

    def filters(self) -> dict:
        """뷰모델의 `set_advanced_filters(**...)`에 그대로 넘길 수 있는 값."""
        published_from, published_to = resolve_date_preset(self._date.currentData())
        lo, hi = resolve_duration_preset(self._duration.currentData())
        return {
            "published_from": published_from,
            "published_to": published_to,
            "channel_name": self._channel.text().strip(),
            "downloaded": resolve_download_preset(self._download.currentData()),
            "favorite_only": self._favorite.isChecked(),
            "watched": resolve_watched_preset(self._watched.currentData()),
            "min_duration_sec": lo,
            "max_duration_sec": hi,
        }

    def active_count(self) -> int:
        """걸린 필터 개수 — 접혀 있을 때 토글 버튼에 적는다."""
        count = sum(
            1 for combo in (self._date, self._duration, self._download, self._watched)
            if combo.currentData() != "all"
        )
        if self._channel.text().strip():
            count += 1
        if self._favorite.isChecked():
            count += 1
        return count

    def summary(self) -> str:
        """걸린 필터를 한 줄로 — 목록이 비었을 때 왜 비었는지 말해 준다."""
        return describe(
            date_key=self._date.currentData(),
            duration_key=self._duration.currentData(),
            download_key=self._download.currentData(),
            watched_key=self._watched.currentData(),
            channel_name=self._channel.text(),
            favorite_only=self._favorite.isChecked(),
        )

    def apply_saved(self, search) -> None:
        """저장된 검색을 막대에 얹는다. **신호는 한 번만** 낸다.

        조건마다 신호를 내면 되부르기 한 번에 조회가 예닐곱 번 나간다.
        """
        widgets = (
            self._date, self._duration, self._download, self._watched,
            self._channel, self._favorite,
        )
        for w in widgets:
            w.blockSignals(True)
        for combo, key in (
            (self._date, search.date_key),
            (self._duration, search.duration_key),
            (self._download, search.download_key),
            (self._watched, search.watched_key),
        ):
            idx = combo.findData(key)
            combo.setCurrentIndex(idx if idx >= 0 else 0)   # 모르는 키면 '전체'
        self._channel.setText(search.channel_name)
        self._favorite.setChecked(bool(search.favorite_only))
        for w in widgets:
            w.blockSignals(False)
        self.changed.emit()

    def condition_keys(self) -> dict:
        """지금 고른 것을 **프리셋 키 그대로** 준다 — 저장용.

        `filters()`는 값으로 푼 것(날짜 등)이라 저장하면 그 시점으로 얼어붙는다.
        """
        return {
            "date_key": self._date.currentData(),
            "duration_key": self._duration.currentData(),
            "download_key": self._download.currentData(),
            "watched_key": self._watched.currentData(),
            "channel_name": self._channel.text().strip(),
            "favorite_only": self._favorite.isChecked(),
        }

    def reset(self) -> None:
        """전부 '전체'로. **신호는 한 번만 낸다** — 칸마다 내면 조회가 여섯 번 나간다."""
        blocked = (
            self._date, self._duration, self._download, self._watched,
            self._channel, self._favorite,
        )
        for widget in blocked:
            widget.blockSignals(True)
        for combo in (self._date, self._duration, self._download, self._watched):
            combo.setCurrentIndex(0)
        self._channel.clear()
        self._favorite.setChecked(False)
        for widget in blocked:
            widget.blockSignals(False)
        self.changed.emit()
