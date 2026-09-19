"""상세화면 '자막' 탭 — 대사를 찾아 그 시점으로 건너뛴다.

이 탭의 쓸모는 **목록이 아니라 점프**다. 자막 전문을 읽으려는 사람은 많지 않지만,
"그 말 나온 데가 어디였더라"는 늘 필요하다. 그래서 검색칸이 맨 위에 있고 줄을
누르면 곧바로 그 시점으로 재생이 옮겨간다.

색인이 없으면 목록 대신 '가져오기' 안내판을 띄운다 — 빈 목록만 보여 주면 왜 비었는지
알 수 없다(CLAUDE.md의 "상태를 말하지 않는 화면을 만들지 않는다").
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from gui.panels.detail.widgets import _t
from gui.smooth_scroll import apply_smooth_scroll

# 검색 결과 상한 — 색인 전체를 한 화면에 쏟으면 스크롤만 길어지고 못 찾는다.
_MAX_ROWS = 500


def _fmt_ts(ms: int) -> str:
    total = max(0, ms) // 1000
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


class SubtitleTab(QWidget):
    """자막 줄 목록 + 검색 + 색인 요청."""

    seek_requested = pyqtSignal(int)      # ms
    index_requested = pyqtSignal()
    transcribe_requested = pyqtSignal()
    transcribe_stop_requested = pyqtSignal()
    translate_requested = pyqtSignal()
    search_changed = pyqtSignal(str)

    _PAGE_EMPTY = 0
    _PAGE_LIST = 1

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # ── 검색 줄 ──
        top = QHBoxLayout()
        top.setSpacing(6)
        self._search = QLineEdit()
        self._search.setPlaceholderText("자막에서 찾기…")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self.search_changed.emit)
        self._count_lbl = QLabel("")
        self._count_lbl.setStyleSheet(f"font-size: 9pt; color: {_t().text_secondary};")
        self._refresh_btn = QPushButton("⟳")
        self._refresh_btn.setFixedWidth(30)
        self._refresh_btn.setToolTip("자막을 다시 받아 색인합니다")
        self._refresh_btn.clicked.connect(self.index_requested.emit)
        top.addWidget(self._search, 1)
        top.addWidget(self._count_lbl)
        # 번역은 **색인이 있을 때만** 쓸모가 있다 — 원문이 있어야 옮긴다.
        self._translate_btn = QPushButton("한글로 번역")
        self._translate_btn.setFixedWidth(84)
        self._translate_btn.setToolTip(
            "이 자막을 한글로 옮겨 따로 저장합니다. 원문은 그대로 남습니다."
        )
        self._translate_btn.clicked.connect(self.translate_requested.emit)
        self._translate_btn.setVisible(False)
        top.addWidget(self._translate_btn)
        top.addWidget(self._refresh_btn)
        layout.addLayout(top)

        # ── 목록 / 안내판 ──
        self._stack = QStackedWidget()

        empty = QWidget()
        empty_layout = QVBoxLayout(empty)
        empty_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_lbl = QLabel("이 영상의 자막을 아직 가져오지 않았습니다.")
        self._empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_lbl.setWordWrap(True)
        self._empty_lbl.setStyleSheet(
            f"color: {_t().text_secondary}; font-size: 10pt; padding: 12px;"
        )
        self._index_btn = QPushButton("자막 가져오기")
        self._index_btn.setFixedWidth(140)
        self._index_btn.clicked.connect(self.index_requested.emit)
        # 음성 인식은 **대안**이다 — YouTube가 자막을 주지 않는 영상에서만 쓸모가 있고,
        # 몇 분이 걸리므로 첫 수단으로 권하지 않는다.
        self._asr_btn = QPushButton("음성 인식으로 만들기")
        self._asr_btn.setFixedWidth(180)
        self._asr_btn.setToolTip(
            "영상의 소리를 듣고 자막을 만듭니다. 받아 둔 파일이 있어야 하며 "
            "영상 길이에 따라 몇 분이 걸립니다."
        )
        self._asr_btn.clicked.connect(self.transcribe_requested.emit)
        # 긴 영상은 몇십 분이 걸린다 — 시작한 사람이 되돌릴 길이 있어야 한다.
        # 중단해도 그때까지 인식한 부분은 남는다(어댑터가 모아 둔 것을 돌려준다).
        self._stop_btn = QPushButton("중단")
        self._stop_btn.setFixedWidth(100)
        self._stop_btn.setToolTip(
            "음성 인식을 멈춥니다. 그때까지 인식한 부분은 자막으로 남습니다."
        )
        self._stop_btn.clicked.connect(self.transcribe_stop_requested.emit)
        self._stop_btn.setVisible(False)
        empty_layout.addWidget(self._empty_lbl)
        empty_layout.addWidget(self._index_btn, alignment=Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(self._asr_btn, alignment=Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(self._stop_btn, alignment=Qt.AlignmentFlag.AlignCenter)
        self._stack.addWidget(empty)                       # _PAGE_EMPTY

        self._list = QListWidget()
        self._list.setWordWrap(True)
        self._list.itemActivated.connect(self._on_row)
        self._list.itemClicked.connect(self._on_row)
        apply_smooth_scroll(self._list)
        self._stack.addWidget(self._list)                  # _PAGE_LIST

        layout.addWidget(self._stack, 1)
        # 받아 둔 파일이 있어야 음성 인식이 가능하다 — 상세화면이 알려 준다.
        self._can_transcribe = False
        # 번역할 원본이 있는가 — 상세화면이 알려 준다.
        self._can_translate = False
        self.set_lines([], indexed=False)

    # ── 표시 ──────────────────────────────────────────────────────

    def set_lines(self, lines, *, indexed: bool) -> None:
        """자막 줄을 채운다. `indexed`가 False면 안내판을 띄운다."""
        self._list.clear()
        if not indexed:
            self._empty_lbl.setText("이 영상의 자막을 아직 가져오지 않았습니다.")
            self._index_btn.setVisible(True)
            self._translate_btn.setVisible(False)
            self._asr_btn.setVisible(self._can_transcribe)
            self._stop_btn.setVisible(False)
            self._stack.setCurrentIndex(self._PAGE_EMPTY)
            self._count_lbl.setText("")
            self._refresh_btn.setVisible(False)
            return

        self._refresh_btn.setVisible(True)
        self._translate_btn.setVisible(self._can_translate)
        rows = list(lines or [])[:_MAX_ROWS]
        if not rows:
            # 색인은 있는데 결과가 없다 = 검색어가 안 맞은 것이다. 가져오기 버튼을
            # 띄우면 엉뚱한 해결책을 권하는 셈이라 숨긴다.
            self._empty_lbl.setText("찾는 말이 든 자막 줄이 없습니다.")
            self._index_btn.setVisible(False)
            self._asr_btn.setVisible(False)
            self._stop_btn.setVisible(False)
            self._stack.setCurrentIndex(self._PAGE_EMPTY)
            self._count_lbl.setText("0줄")
            return

        for line in rows:
            item = QListWidgetItem(f"{_fmt_ts(line.start_ms)}   {line.text}")
            item.setData(Qt.ItemDataRole.UserRole, int(line.start_ms))
            item.setToolTip("클릭하면 이 시점부터 재생합니다")
            self._list.addItem(item)
        total = len(lines or [])
        self._count_lbl.setText(
            f"{total}줄" if total <= _MAX_ROWS else f"{_MAX_ROWS}/{total}줄"
        )
        self._stop_btn.setVisible(False)
        self._stack.setCurrentIndex(self._PAGE_LIST)

    def set_busy(self, busy: bool) -> None:
        self._index_btn.setEnabled(not busy)
        self._asr_btn.setEnabled(not busy)
        self._refresh_btn.setEnabled(not busy)
        if busy:
            self._empty_lbl.setText("자막을 가져오는 중…")
            self._stop_btn.setVisible(False)
            self._stack.setCurrentIndex(self._PAGE_EMPTY)

    def set_transcribe_available(self, available: bool) -> None:
        """음성 인식을 쓸 수 있는가 — 받아 둔 파일이 없으면 보여 줄 이유가 없다."""
        self._can_transcribe = bool(available)
        self._asr_btn.setVisible(
            self._can_transcribe and self._stack.currentIndex() == self._PAGE_EMPTY
        )

    def set_translate_available(self, available: bool) -> None:
        """번역할 원본 자막이 있는가 — 없으면 버튼을 보여 줄 이유가 없다."""
        self._can_translate = bool(available)
        self._translate_btn.setVisible(
            self._can_translate and self._stack.currentIndex() == self._PAGE_LIST
        )

    def show_transcribing(self, text: str, *, stoppable: bool = False) -> None:
        """음성 인식 진행 표시 — 몇 분이 걸리므로 무엇을 하는 중인지 계속 알린다.

        `stoppable`은 **지금 멈출 수 있는 단계인가**다. 모델을 내려받는 동안에는
        협조적 중단이 걸리지 않으므로(내려받기가 끝나야 첫 판정이 돈다) 버튼을
        띄우지 않는다 — 눌러도 몇 분간 아무 반응이 없으면 고장처럼 보인다.
        """
        self._empty_lbl.setText(text)
        self._index_btn.setVisible(False)
        self._asr_btn.setVisible(False)
        self._stop_btn.setVisible(bool(stoppable))
        self._stop_btn.setEnabled(True)
        self._stack.setCurrentIndex(self._PAGE_EMPTY)

    def show_stopping(self, text: str) -> None:
        """중단 요청을 받았다 — 실제로 멈출 때까지 한 박자 걸린다(세그먼트 경계)."""
        self._empty_lbl.setText(text)
        self._stop_btn.setEnabled(False)
        self._stack.setCurrentIndex(self._PAGE_EMPTY)

    def show_no_subtitle(self) -> None:
        """자막을 찾지 못했을 때 — 왜 비었는지 말해 준다."""
        self._empty_lbl.setText(
            "이 영상에는 가져올 수 있는 자막이 없습니다.\n"
            "(YouTube가 자동 자막도 제공하지 않는 영상입니다)"
        )
        self._index_btn.setVisible(True)
        # 자막이 아예 없는 영상 — 음성 인식이 **가장 쓸모 있는 경우**다.
        self._asr_btn.setVisible(self._can_transcribe)
        self._stop_btn.setVisible(False)
        self._stack.setCurrentIndex(self._PAGE_EMPTY)

    def show_streaming_notice(self) -> None:
        """라이브러리 밖(스트리밍) 영상 — 색인할 대상이 없다.

        버튼을 남겨 두면 눌러도 아무 일이 없어 고장처럼 보인다. 대신 무엇을 하면
        되는지 알린다(카테고리에 담으면 로컬 영상이 된다).
        """
        self._list.clear()
        self._empty_lbl.setText(
            "라이브러리에 담지 않은 영상은 자막을 색인할 수 없습니다.\n"
            "카테고리에 담으면 자막 찾기를 쓸 수 있습니다."
        )
        self._index_btn.setVisible(False)
        self._asr_btn.setVisible(False)
        self._stop_btn.setVisible(False)
        self._translate_btn.setVisible(False)
        self._refresh_btn.setVisible(False)
        self._count_lbl.setText("")
        self._stack.setCurrentIndex(self._PAGE_EMPTY)

    def clear_search(self) -> None:
        self._search.blockSignals(True)
        self._search.clear()
        self._search.blockSignals(False)

    @property
    def search_text(self) -> str:
        return self._search.text().strip()

    # ── 입력 ──────────────────────────────────────────────────────

    def _on_row(self, item: QListWidgetItem) -> None:
        ms = item.data(Qt.ItemDataRole.UserRole)
        if ms is not None:
            self.seek_requested.emit(int(ms))
