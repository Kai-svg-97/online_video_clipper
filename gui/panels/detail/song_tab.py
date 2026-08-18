"""노래 탭 — 가수·앨범·제목·발매년도 편집과 가사(원문·번역·싱크) 표시.

가사 후보 목록(`_LyricsCandidateList`)도 여기 있다. 조회·저장은 하지 않고 신호만
올린다 — 데이터는 LibraryPanel이 SongViewModel로 주입한다.
"""

from __future__ import annotations

import html
import logging
import time

from PyQt6.QtCore import (
    Qt,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QColor,
)
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from application.song.dtos import SongInfoDTO
from domain.song.aggregates import MAX_LYRICS_OFFSET_MS
from domain.song.value_objects import LyricsLine

from gui.themes.colors import sem

from gui.panels.detail.widgets import _EditableField, _LockedNotice, _SpinRefreshButton, _clear_layout, _t
from gui.panels.detail.text_zoom import (
    ZOOM_TOOLTIP,
    clamp_scale,
    load_scale,
    scale_label,
    scaled_pt,
)

logger = logging.getLogger(__name__)


class _LyricRow(QWidget):
    """가사 한 줄 컨테이너 — 하이라이트·클릭 대상.

    예전에는 원문/번역 라벨을 레이아웃에 낱개로 넣어 '줄'이라는 단위가 없었다.
    재생 위치를 따라 강조하고 클릭으로 seek 하려면 줄마다 위젯이 필요하다.
    """

    clicked = pyqtSignal()

    def __init__(self, line_index: int, seekable: bool, shaded: bool,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.line_index = line_index
        self.is_current = False
        self._seekable = seekable
        self._shaded = shaded
        if seekable:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._apply_style()

    def set_current(self, on: bool) -> None:
        if self.is_current == on:
            return
        self.is_current = on
        self._apply_style()

    def _apply_style(self) -> None:
        tok = _t()
        if self.is_current:
            # 트리 선택 표현과 같은 어법 — accent 14% 틴트. 색은 테마 토큰에서 파생한다.
            color = QColor(tok.accent)
            bg = f"rgba({color.red()},{color.green()},{color.blue()},0.14)"
        elif self._shaded:
            # 중립 회색 틴트 — 교대 음영 용도라 밝은/어두운 테마 어느 쪽 배경에도
            # 자연스럽게 섞이므로 테마 토큰 대신 고정값을 쓴다(기존 코드에서 이식).
            bg = "rgba(127,127,127,0.09)"
        else:
            bg = "transparent"
        self.setStyleSheet(f"background:{bg}; border-radius:4px;")

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt 시그니처)
        if self._seekable and event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

def _candidate_tooltip(dto) -> str:
    """후보 행 툴팁 — 목록 정렬의 근거(조회수·곡 길이)를 사람이 읽을 수 있게 보여준다."""
    parts = [f"{dto.source_name} · {dto.artist} - {dto.title}".strip(" ·-")]
    if dto.popularity:
        parts.append(f"조회수 {dto.popularity:,}")
    if dto.duration_sec:
        parts.append(f"길이 {dto.duration_sec // 60}:{dto.duration_sec % 60:02d}")
    if dto.line_count:
        parts.append(f"{dto.line_count}줄")
    parts.append("시간 정보 있음(자막 가능)" if dto.is_synced else "시간 정보 없음")
    return "\n".join(parts)

class _LyricsCandidateList(QWidget):
    """가사 검색 후보 목록 — |출처|가수|제목|가사 첫째 줄|싱크|.

    검색을 시작하면 조회할 출처마다 '조회중…' 행을 **먼저** 만들고, 결과가 도착하는
    대로 그 행을 채운다(전 출처가 끝나기를 기다리지 않는다 — 느린 출처 하나 때문에
    이미 확보한 후보를 못 보는 일이 없게). 결과가 없는 출처는 회색 '없음'으로 남고
    선택할 수 없다.
    """

    chosen = pyqtSignal(object)   # LyricsCandidateDTO — 사용자가 고른 후보
    closed = pyqtSignal()

    _HEADERS = ("출처", "가수", "제목", "가사 첫째 줄", "싱크")
    _COL_SOURCE, _COL_ARTIST, _COL_TITLE, _COL_FIRST, _COL_SYNC = range(5)
    _DTO_ROLE = Qt.ItemDataRole.UserRole

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # 표는 아래 상태로부터 매번 다시 그린다(_rebuild). 출처마다 후보 수가 달라 행이
        # 늘었다 줄었다 하므로, 행 인덱스를 직접 관리하면 삽입 때마다 어긋난다.
        self._order: list[str] = []                  # 출처 표시 순서
        self._results: dict[str, list] = {}          # 출처 → 후보 DTO 목록
        self._pending: set[str] = set()              # 아직 조회 중인 출처
        self._selected = None                        # 선택 유지용(재구성 후 되찾는다)
        self._rows: list[tuple[str, object]] = []    # 화면 행 → (출처, DTO | None)
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)

        header = QHBoxLayout()
        header.addWidget(QLabel("<b>가사 후보</b>"))
        self._status_lbl = QLabel("")
        self._status_lbl.setStyleSheet(f"font-size:9pt; color:{_t().text_secondary};")
        header.addWidget(self._status_lbl)
        header.addStretch()
        self._apply_btn = QPushButton("이 가사 사용")
        self._apply_btn.setFixedHeight(24)
        self._apply_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._apply_btn.setEnabled(False)
        self._apply_btn.clicked.connect(self._emit_chosen)
        header.addWidget(self._apply_btn)
        close_btn = QPushButton("닫기")
        close_btn.setFixedHeight(24)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.clicked.connect(self.closed.emit)
        header.addWidget(close_btn)
        root.addLayout(header)

        self._table = QTableWidget(0, len(self._HEADERS))
        self._table.setHorizontalHeaderLabels(list(self._HEADERS))
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.setWordWrap(False)
        hh = self._table.horizontalHeader()
        hh.setSectionResizeMode(self._COL_SOURCE, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(self._COL_ARTIST, QHeaderView.ResizeMode.Interactive)
        hh.setSectionResizeMode(self._COL_TITLE, QHeaderView.ResizeMode.Interactive)
        hh.setSectionResizeMode(self._COL_FIRST, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(self._COL_SYNC, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setColumnWidth(self._COL_ARTIST, 130)
        self._table.setColumnWidth(self._COL_TITLE, 160)
        self._table.itemSelectionChanged.connect(self._on_selection_changed)
        self._table.itemDoubleClicked.connect(lambda _i: self._emit_chosen())
        root.addWidget(self._table, stretch=1)

    # ── 채우기 ────────────────────────────────────────────────────
    def begin(self, source_names: list[str]) -> None:
        """조회 시작 — 출처마다 '조회중…' 행을 미리 만든다."""
        self._order = list(source_names)
        self._results = {name: [] for name in self._order}
        self._pending = set(self._order)
        self._selected = None
        self._rebuild()
        if not source_names:
            self._status_lbl.setText("조회할 가사 출처가 없습니다 (설정에서 출처를 켜세요)")

    def add_result(self, source_name: str, dto: object) -> None:
        """후보 **한 건**을 목록에 더한다(한 출처가 여러 번 부를 수 있다).

        같은 제목이라도 가수가 다른 곡이 흔해 출처마다 여러 곡이 올라온다. 먼저 도착한
        후보를 자동 선택해 두어, 원하는 곡이 맨 위면 바로 적용할 수 있게 한다.
        """
        if dto is None or source_name not in self._results:
            return   # 취소된 이전 검색의 늦은 결과
        self._results[source_name].append(dto)
        if self._selected is None:
            self._selected = dto
        self._rebuild()

    def source_done(self, source_name: str, count: int) -> None:
        """출처 하나의 조회가 끝났음을 반영한다(0건이면 '결과 없음'으로 굳는다)."""
        if source_name not in self._results:
            return
        self._pending.discard(source_name)
        self._rebuild()

    def finish(self, found: int) -> None:
        # 취소·오류로 통지 없이 끝난 출처가 '조회중…'으로 남지 않게 정리한다.
        self._pending.clear()
        self._rebuild()
        self._status_lbl.setText(
            f"후보 {found}건 — 원하는 가사를 고르고 '이 가사 사용'을 누르세요"
            if found
            else "가사를 찾지 못했습니다 (가수·제목을 고쳐서 다시 검색해 보세요)"
        )

    def _rebuild(self) -> None:
        """상태(_order/_results/_pending)로부터 표 전체를 다시 그린다."""
        rows: list[tuple[str, object]] = []
        for name in self._order:
            found = self._results.get(name) or []
            if found:
                rows.extend((name, dto) for dto in found)
            else:
                rows.append((name, None))   # 조회중 또는 결과 없음
        self._rows = rows

        self._table.blockSignals(True)
        self._table.clearContents()
        self._table.setRowCount(len(rows))
        select_row = -1
        for row, (name, dto) in enumerate(rows):
            if dto is None:
                placeholder = "조회중…" if name in self._pending else "결과 없음"
                self._set_row_text(row, name, "", "", placeholder, "")
                self._set_row_selectable(row, False)
                self._table.item(row, self._COL_FIRST).setForeground(
                    QColor(_t().text_secondary)
                )
                continue
            first = dto.first_line or "(빈 가사)"
            if dto.line_count:
                first = f"{first}   ({dto.line_count}줄)"
            self._set_row_text(
                row, name, dto.artist, dto.title, first, "싱크" if dto.is_synced else "—",
                tooltip=_candidate_tooltip(dto),
            )
            self._set_row_selectable(row, True)
            self._table.item(row, self._COL_SOURCE).setData(self._DTO_ROLE, dto)
            if dto.is_synced:
                # 자막 표시가 가능한 후보라 의미상 강조한다(성공 의미 색).
                self._table.item(row, self._COL_SYNC).setForeground(QColor(sem("success")))
            if dto is self._selected:
                select_row = row
        self._table.blockSignals(False)

        if select_row >= 0:
            self._table.selectRow(select_row)
        else:
            self._selected = None
            self._table.clearSelection()
        self._apply_btn.setEnabled(self._selected is not None)
        self._update_status()

    def _update_status(self) -> None:
        if not self._order:
            return
        done = len(self._order) - len(self._pending)
        count = sum(len(v) for v in self._results.values())
        if self._pending:
            self._status_lbl.setText(
                f"조회중… {done}/{len(self._order)} 출처 · 후보 {count}건"
            )

    def _set_row_text(self, row: int, *values: str, tooltip: str = "") -> None:
        for col, text in enumerate(values):
            item = QTableWidgetItem(text)
            # 정렬 근거(조회수·곡 길이)는 열로 빼지 않고 툴팁에 담는다 — 요청받은 다섯 열을
            # 유지하면서도 "왜 이 순서인가"를 확인할 수 있게 한다.
            item.setToolTip(tooltip or text)
            if col == self._COL_SYNC:
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(row, col, item)

    def _set_row_selectable(self, row: int, on: bool) -> None:
        flags = (
            Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
            if on
            else Qt.ItemFlag.NoItemFlags
        )
        for col in range(self._table.columnCount()):
            item = self._table.item(row, col)
            if item is not None:
                item.setFlags(flags)

    # ── 선택 ─────────────────────────────────────────────────────
    def selected_candidate(self):
        rows = self._table.selectionModel().selectedRows() if self._table.selectionModel() else []
        if not rows:
            return None
        item = self._table.item(rows[0].row(), self._COL_SOURCE)
        return item.data(self._DTO_ROLE) if item is not None else None

    def _on_selection_changed(self) -> None:
        # 사용자가 고른 행은 재구성(_rebuild) 후에도 유지해야 한다 — 다른 출처의 결과가
        # 뒤늦게 도착할 때마다 선택이 풀리면 고르는 도중에 놓친다.
        self._selected = self.selected_candidate()
        self._apply_btn.setEnabled(self._selected is not None)

    def _emit_chosen(self) -> None:
        dto = self.selected_candidate()
        if dto is not None:
            self.chosen.emit(dto)

class _SongTab(QWidget):
    """상세화면 '노래' 탭 — 가수/앨범/제목/발매년도 + 가사(원문·한글 병행).

    필드는 더블클릭으로 인라인 편집하고, 가사는 표시 영역 더블클릭 → 편집 모드
    (원문 한 줄당 한 줄). ⟳로 정보를 재수집하고, '노래로 표시' 토글로 노래 여부를
    수동 지정한다. 실제 저장·조회는 상위(VideoDetailWidget→LibraryPanel→SongViewModel)가
    담당하며, 이 위젯은 신호만 방출한다.
    """

    field_edited = pyqtSignal(str, str)      # (field_key, value)
    lyrics_edited = pyqtSignal(object)       # list[LyricsLine]
    candidates_requested = pyqtSignal()      # 가사 검색 — 전 출처를 훑어 후보 목록을 띄운다
    candidate_chosen = pyqtSignal(object)    # 후보 목록에서 고른 LyricsCandidateDTO
    translate_requested = pyqtSignal()       # 현재 가사를 한글로 재번역
    flag_toggled = pyqtSignal(bool)
    filter_requested = pyqtSignal(str, str)  # (field_key, value) — 같은 가수/앨범 필터
    synced_requested = pyqtSignal()          # 싱크(시간 정보) 가사 찾기
    lyrics_seek_requested = pyqtSignal(int)  # 가사 줄 클릭 → 그 줄 시작 ms
    offset_changed = pyqtSignal(int)         # 사용자가 싱크 보정값을 바꿈(절대 ms)
    font_scale_reset_requested = pyqtSignal()  # 배율 버튼 — 글자 크기를 기본값으로
    category_requested = pyqtSignal()        # 안내판의 '카테고리에 담기' 클릭

    # 가사 영역 스택 인덱스
    _STACK_VIEW = 0         # 가사 표시
    _STACK_EDIT = 1         # 가사 직접 편집
    _STACK_CANDIDATES = 2   # 가사 검색 후보 목록
    _STACK_LOCKED = 3       # 카테고리 미지정 — 안내판

    _FIELDS = (
        ("artist", "가수"),
        ("album", "앨범"),
        ("song_title", "노래 제목"),
        ("release_year", "발매년도"),
    )
    # 값 오른쪽 » 필터 아이콘을 붙일 필드
    _FILTER_FIELDS = {"artist": "같은 가수의 영상 보기", "album": "같은 앨범의 영상 보기"}

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._editable = True
        self._lyrics_lines: list[LyricsLine] = []
        self._current_dto: SongInfoDTO | None = None
        self._font_scale: float = load_scale()
        self._side_by_side = False   # 번역 배치: False=원문 아래, True=원문 오른쪽
        self._rows: list[_LyricRow] = []
        self._current_row: _LyricRow | None = None
        self._scroll_hold_until = 0.0   # 사용자 스크롤 후 자동 스크롤을 멈추는 시각(monotonic)
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # 헤더: 제목 + 노래 토글 + 상태 (가사 갱신 버튼은 아래 '가사' 레이블 옆으로 이동)
        header = QHBoxLayout()
        header.addWidget(QLabel("<b>노래 정보</b>"))
        header.addStretch()
        self._flag_chk = QCheckBox("노래로 표시")
        self._flag_chk.setToolTip("이 영상을 노래로 표시/해제 (영상 제목으로 가수·앨범·제목·발매년도를 채움)")
        self._flag_chk.toggled.connect(self._on_flag_toggled)
        header.addWidget(self._flag_chk)
        self._status_lbl = QLabel("")
        self._status_lbl.setStyleSheet(f"font-size:9pt; color:{_t().text_secondary};")
        header.addWidget(self._status_lbl)
        root.addLayout(header)

        # 필드 그리드
        grid_w = QWidget()
        grid = QGridLayout(grid_w)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(6)
        grid.setColumnStretch(1, 1)
        self._fields: dict[str, _EditableField] = {}
        for row, (key, label) in enumerate(self._FIELDS):
            name_lbl = QLabel(label)
            name_lbl.setFixedWidth(64)
            name_lbl.setStyleSheet(f"color:{_t().text_secondary}; font-weight:bold;")
            # 값(_EditableField)이 세로 중앙 정렬이므로 레이블도 중앙으로 맞춰 이질감 제거
            name_lbl.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
            action_tip = self._FILTER_FIELDS.get(key, "")
            field = _EditableField(with_action=bool(action_tip), action_tip=action_tip)
            field.edited.connect(lambda v, k=key: self.field_edited.emit(k, v))
            if action_tip:
                field.action_clicked.connect(
                    lambda k=key, f=field: self.filter_requested.emit(k, f.value)
                )
            grid.addWidget(name_lbl, row, 0, Qt.AlignmentFlag.AlignVCenter)
            grid.addWidget(field, row, 1, Qt.AlignmentFlag.AlignVCenter)
            self._fields[key] = field
        root.addWidget(grid_w)

        # 가사 헤더 ('가사' 레이블 + 가사 갱신 ⟳ + 출처 + 편집 힌트)
        lyr_header = QHBoxLayout()
        lyr_header.addWidget(QLabel("<b>가사</b>"))
        self._lyrics_refresh_btn = _SpinRefreshButton()
        self._lyrics_refresh_btn.setFixedSize(26, 24)
        self._lyrics_refresh_btn.setToolTip("가사 검색")
        self._lyrics_refresh_btn.clicked.connect(self._on_lyrics_search_clicked)
        lyr_header.addWidget(self._lyrics_refresh_btn)
        # 번역 버튼 — 가사가 이미 있을 때만 노출(현재 가사를 한글로 재번역).
        self._translate_btn = QPushButton("번역")
        self._translate_btn.setFixedHeight(24)
        self._translate_btn.setToolTip("현재 가사를 한글로 다시 번역")
        self._translate_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._translate_btn.clicked.connect(self.translate_requested.emit)
        self._translate_btn.setVisible(False)
        lyr_header.addWidget(self._translate_btn)
        # 싱크 가사 찾기 — 시간 정보가 없는 가사일 때만 노출(자막 기능의 전제).
        self._synced_btn = QPushButton("⏱")
        self._synced_btn.setFixedSize(26, 24)
        self._synced_btn.setToolTip("싱크(시간 정보) 가사 찾기 — 자막 표시에 필요합니다")
        self._synced_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._synced_btn.clicked.connect(self.synced_requested.emit)
        self._synced_btn.setVisible(False)
        lyr_header.addWidget(self._synced_btn)
        # 싱크 보정 — 시간 정보가 있는 가사일 때만 노출(⏱과 상호 배타적).
        # 영상 위 자막(💬)의 [ / ] · , / . 단축키·우클릭 메뉴와 같은 값을 다룬다.
        self._offset_spin = QDoubleSpinBox()
        self._offset_spin.setRange(-MAX_LYRICS_OFFSET_MS / 1000, MAX_LYRICS_OFFSET_MS / 1000)
        self._offset_spin.setDecimals(2)
        self._offset_spin.setSingleStep(0.25)
        self._offset_spin.setSuffix(" s")
        self._offset_spin.setFixedWidth(76)
        self._offset_spin.setToolTip(
            "가사 시작 시각 보정 — 양수면 자막이 늦게, 음수면 빠르게 뜹니다.\n"
            "영상 위 자막(💬) 단축키 [ / ] 또는 , / . 로도 조절할 수 있습니다."
        )
        self._offset_spin.valueChanged.connect(self._on_offset_spin_changed)
        self._offset_spin.setVisible(False)
        lyr_header.addWidget(self._offset_spin)
        self._src_lbl = QLabel("")
        self._src_lbl.setStyleSheet(f"font-size:8pt; color:{_t().text_secondary};")
        self._src_lbl.setOpenExternalLinks(True)
        lyr_header.addWidget(self._src_lbl)
        lyr_header.addStretch()
        hint = QLabel("(더블클릭하여 편집)")
        hint.setStyleSheet(f"font-size:8pt; color:{_t().text_secondary};")
        lyr_header.addWidget(hint)
        # 글자 크기 — 지금 배율을 보여 주고, 누르면 기본값으로 되돌린다.
        self._zoom_btn = QPushButton(scale_label(self._font_scale))
        self._zoom_btn.setFixedSize(46, 22)
        self._zoom_btn.setFlat(True)
        self._zoom_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._zoom_btn.setToolTip(ZOOM_TOOLTIP)
        self._zoom_btn.clicked.connect(self.font_scale_reset_requested.emit)
        lyr_header.addWidget(self._zoom_btn)
        # 번역 배치 전환 아이콘 (비한국어 병행 가사일 때만 노출)
        self._layout_btn = QPushButton("⬌")
        self._layout_btn.setFixedSize(24, 22)
        self._layout_btn.setFlat(True)
        self._layout_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._layout_btn.setToolTip("번역을 오른쪽에 표시")
        self._layout_btn.clicked.connect(self._toggle_lyrics_layout)
        self._layout_btn.setVisible(False)
        lyr_header.addWidget(self._layout_btn)
        root.addLayout(lyr_header)

        # 가사 표시/편집 스택
        self._lyrics_stack = QStackedWidget()
        self._lyrics_scroll = QScrollArea()
        self._lyrics_scroll.setWidgetResizable(True)
        self._lyrics_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._lyrics_holder = QWidget()
        self._lyrics_layout = QVBoxLayout(self._lyrics_holder)
        self._lyrics_layout.setContentsMargins(4, 4, 4, 4)
        self._lyrics_layout.setSpacing(2)
        self._lyrics_scroll.setWidget(self._lyrics_holder)
        self._lyrics_stack.addWidget(self._lyrics_scroll)     # index 0: 표시
        # 사용자가 직접 스크롤하면 자동 스크롤을 잠시 멈춘다. valueChanged가 아니라
        # sliderPressed·actionTriggered를 쓰는 이유: valueChanged는 자동 스크롤 자신이
        # 일으키는 변화까지 잡아버려서, 한 번 자동 스크롤되고 나면 영구히 억제된다.
        self._lyrics_scroll.verticalScrollBar().sliderPressed.connect(self._on_user_scroll)
        self._lyrics_scroll.verticalScrollBar().actionTriggered.connect(
            lambda _a: self._on_user_scroll()
        )

        self._lyrics_editor = QPlainTextEdit()
        self._lyrics_editor.setPlaceholderText("가사를 입력하세요 (한 줄당 한 줄)…")
        self._lyrics_stack.addWidget(self._lyrics_editor)     # index 1: 편집
        # index 2: 가사 검색 후보 목록 — 가사 영역을 그대로 쓰므로 레이아웃이 흔들리지 않는다.
        self._candidates = _LyricsCandidateList()
        self._candidates.chosen.connect(self._on_candidate_chosen)
        self._candidates.closed.connect(self.close_candidates)
        self._lyrics_stack.addWidget(self._candidates)
        # index 3: 카테고리 미지정 안내 — 가사는 영상별로 저장되므로 로컬 영상이어야 한다.
        self._locked = _LockedNotice(
            "이 영상은 아직 라이브러리에 없습니다.\n"
            "카테고리에 담으면 가사 조회·편집과 자막 싱크를 사용할 수 있습니다."
        )
        self._locked.action_clicked.connect(self.category_requested.emit)
        self._lyrics_stack.addWidget(self._locked)
        root.addWidget(self._lyrics_stack, stretch=1)

    # ── 채우기 ────────────────────────────────────────────────────
    def set_editable(self, editable: bool) -> None:
        """스트리밍 영상 등에서 편집을 막는다."""
        self._editable = editable
        self._flag_chk.setEnabled(editable)
        self._lyrics_refresh_btn.setEnabled(editable)
        self._translate_btn.setEnabled(editable)
        self._synced_btn.setEnabled(editable)
        self._offset_spin.setEnabled(editable)
        for f in self._fields.values():
            f.set_editable(editable)

    def set_locked(self, locked: bool) -> None:
        """카테고리 미지정(라이브러리 밖) 영상 — 가사 영역에 안내판을 띄운다."""
        if locked:
            self._lyrics_stack.setCurrentIndex(self._STACK_LOCKED)
        elif self._lyrics_stack.currentIndex() == self._STACK_LOCKED:
            self._lyrics_stack.setCurrentIndex(self._STACK_VIEW)

    def _on_offset_spin_changed(self, value: float) -> None:
        self.offset_changed.emit(int(round(value * 1000)))

    def set_offset_ms(self, ms: int) -> None:
        """외부(플레이어 단축키·메뉴)에서 바뀐 오프셋을 표시에만 반영한다.

        `blockSignals`로 감싸지 않으면 이 갱신이 `offset_changed`를 다시 쏘아
        플레이어→탭→플레이어로 되돌아가는 무의미한 루프가 생긴다.
        """
        self._offset_spin.blockSignals(True)
        self._offset_spin.setValue(ms / 1000.0)
        self._offset_spin.blockSignals(False)

    def _on_lyrics_search_clicked(self) -> None:
        """가사 검색 — 활성 출처를 전부 훑어 후보 목록을 띄운다.

        예전에는 첫 성공 출처를 곧바로 채택하고(가사가 있으면 '다음 출처'로 순환) 어떤
        가사인지는 적용된 뒤에야 볼 수 있었다. 이제 |출처|가수|제목|가사 첫째 줄|싱크|를
        나열해 사용자가 직접 고른다.
        """
        self.candidates_requested.emit()

    # ── 가사 후보 목록 (외부=LibraryPanel/SongViewModel이 결과를 밀어 넣는다) ──
    def begin_candidates(self, source_names: list[str]) -> None:
        """검색 시작 — 출처별 '조회중…' 행을 만들고 후보 목록으로 전환한다."""
        self._candidates.begin(list(source_names))
        self._lyrics_stack.setCurrentIndex(self._STACK_CANDIDATES)
        self._lyrics_refresh_btn.start_spin()

    def add_candidate_result(self, source_name: str, dto: object) -> None:
        """후보 한 건 추가 — 출처당 여러 번 불릴 수 있다."""
        self._candidates.add_result(source_name, dto)

    def candidate_source_done(self, source_name: str, count: int) -> None:
        self._candidates.source_done(source_name, count)

    def finish_candidates(self, found: int) -> None:
        self._candidates.finish(found)
        self._lyrics_refresh_btn.stop_spin()

    def close_candidates(self) -> None:
        """후보 목록을 닫고 가사 표시로 돌아간다."""
        if self._lyrics_stack.currentIndex() == self._STACK_CANDIDATES:
            self._lyrics_stack.setCurrentIndex(self._STACK_VIEW)
        self._lyrics_refresh_btn.stop_spin()

    def _on_candidate_chosen(self, dto: object) -> None:
        # 적용은 번역까지 포함해 시간이 걸리므로 목록을 먼저 닫아 진행 중임을 보인다
        # (반영이 끝나면 set_info가 새 가사로 표시를 갱신한다).
        self.close_candidates()
        self.candidate_chosen.emit(dto)

    def set_busy(self, busy: bool) -> None:
        self._status_lbl.setText("불러오는 중…" if busy else "")
        # 갱신 중에는 버튼을 비활성화하지 않고 아이콘을 회전시켜 진행을 표시한다
        # (중복 클릭은 SongViewModel의 _in_flight 가드가 흡수).
        self._lyrics_refresh_btn.setEnabled(self._editable)
        if busy:
            self._lyrics_refresh_btn.start_spin()
        else:
            self._lyrics_refresh_btn.stop_spin()

    def set_info(self, dto: SongInfoDTO | None) -> None:
        self._current_dto = dto
        # 가사 검색/번역 버튼 상태 — 가사가 있으면 '다음 출처'+'번역' 노출.
        has_lyrics = bool(dto and dto.has_lyrics)
        self._translate_btn.setVisible(has_lyrics and self._editable)
        self._lyrics_refresh_btn.setToolTip(
            "다음 출처에서 가사 검색" if has_lyrics else "가사 검색"
        )
        is_synced = bool(dto and dto.is_synced)
        # 싱크 가사가 이미 있으면 찾을 이유가 없다.
        self._synced_btn.setVisible(has_lyrics and not is_synced and self._editable)
        self._synced_btn.setEnabled(self._editable)
        # 오프셋 조정은 시간 정보가 있어야 의미가 있다 — ⏱과 상호 배타적으로 노출.
        self._offset_spin.setVisible(is_synced)
        self._offset_spin.setEnabled(self._editable)
        self.set_offset_ms(dto.lyrics_offset_ms if dto else 0)
        is_song = bool(dto and dto.is_song)
        self._flag_chk.blockSignals(True)
        self._flag_chk.setChecked(is_song)
        self._flag_chk.blockSignals(False)

        self._fields["artist"].set_value(dto.artist if dto else "")
        self._fields["album"].set_value(dto.album if dto else "")
        self._fields["song_title"].set_value(dto.song_title if dto else "")
        self._fields["release_year"].set_value(dto.release_year if dto else "")

        # 출처 표시
        if dto and dto.source_name:
            if dto.source_url:
                self._src_lbl.setText(
                    f'· 출처: <a href="{html.escape(dto.source_url, quote=True)}">'
                    f'{html.escape(dto.source_name)}</a>'
                )
            else:
                self._src_lbl.setText(f"· 출처: {html.escape(dto.source_name)}")
        else:
            self._src_lbl.setText("")

        self._lyrics_lines = list(dto.lyrics_lines) if dto else []
        self._render_lyrics(dto)
        # 후보 목록을 보고 있는 중이면 유지한다 — 검색 도중 다른 저장(필드 편집 등)이
        # song_info_changed를 쏘아 목록이 사라지면, 사용자가 고르던 후보를 잃는다.
        # 잠금 안내판도 같은 이유로 유지한다(스트리밍 상세에서 빈 가사로 되돌아가면
        # 왜 못 쓰는지 설명이 사라진다).
        if self._lyrics_stack.currentIndex() not in (
            self._STACK_CANDIDATES, self._STACK_LOCKED
        ):
            self._lyrics_stack.setCurrentIndex(self._STACK_VIEW)

    def _render_lyrics(self, dto: SongInfoDTO | None) -> None:
        _clear_layout(self._lyrics_layout)
        self._rows = []
        self._current_row = None
        bilingual = bool(dto and dto.is_bilingual)
        # 번역 배치 전환 아이콘은 병행(번역 있는) 가사일 때만 노출
        self._layout_btn.setVisible(bilingual)
        if not dto or not dto.lyrics_lines:
            msg = (
                "가사 정보가 없습니다.\n'가사' 옆 ⟳ 버튼으로 조회하거나 더블클릭하여 직접 입력하세요."
                if (dto and dto.is_song)
                else "'노래로 표시'하면 영상 제목으로 정보를 채웁니다."
            )
            empty = QLabel(msg)
            empty.setStyleSheet(f"color:{_t().text_secondary}; padding:12px;")
            empty.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            self._lyrics_layout.addWidget(empty)
            self._lyrics_layout.addStretch()
            return
        tok = _t()
        side = self._side_by_side and bilingual
        content_idx = 0   # 오른쪽 배치 시 행 교대 음영용(빈 줄 제외)
        for idx, line in enumerate(dto.lyrics_lines):
            if not line.original.strip() and not line.translation.strip():
                spacer = QLabel(" ")
                spacer.setFixedHeight(8)
                self._lyrics_layout.addWidget(spacer)
                continue
            # 오른쪽 배치일 때만 교대 음영을 준다(원문 아래 배치는 두 줄이 한 덩어리라
            # 음영을 주면 오히려 경계가 헷갈린다).
            row = _LyricRow(
                line_index=idx,
                seekable=line.start_ms is not None,
                shaded=side and content_idx % 2 == 0,
            )
            if line.start_ms is not None:
                row.clicked.connect(
                    lambda ms=int(line.start_ms): self.lyrics_seek_requested.emit(ms)
                )
            if side:
                rl = QHBoxLayout(row)
                rl.setContentsMargins(6, 3, 6, 3)
                rl.setSpacing(12)
                orig = self._lyric_label(line.original or " ", tok.text_primary, 10)
                orig.setAlignment(Qt.AlignmentFlag.AlignTop)
                trans = self._lyric_label(line.translation or "", tok.text_secondary, 9)
                trans.setAlignment(Qt.AlignmentFlag.AlignTop)
                rl.addWidget(orig, 1)
                rl.addWidget(trans, 1)
            else:
                rl = QVBoxLayout(row)
                rl.setContentsMargins(6, 1, 6, 1)
                rl.setSpacing(0)
                rl.addWidget(self._lyric_label(line.original or " ", tok.text_primary, 10))
                if line.translation:
                    rl.addWidget(
                        self._lyric_label(line.translation, tok.text_secondary, 9)
                    )
            self._lyrics_layout.addWidget(row)
            self._rows.append(row)
            content_idx += 1
        self._lyrics_layout.addStretch()

    def _lyric_label(self, text: str, color: str, pt: int) -> QLabel:
        """가사 한 줄 라벨 — 평문 렌더(가사 속 &·< 등이 엔티티로 오표기되지 않도록).

        크기는 사용자가 정한 배율(`set_font_scale`)을 곱해 정한다 — 읽는 글이라
        화면·시력에 따라 알맞은 크기가 다르다.
        """
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setTextFormat(Qt.TextFormat.PlainText)
        lbl.setStyleSheet(
            f"color:{color}; font-size:{scaled_pt(pt, self._font_scale)}pt;"
            " background:transparent;"
        )
        return lbl

    def set_font_scale(self, scale: float) -> None:
        """가사 글자 배율을 바꾸고 즉시 다시 그린다(현재 강조 줄은 유지)."""
        scale = clamp_scale(scale)
        if scale == self._font_scale:
            return
        self._font_scale = scale
        self._zoom_btn.setText(scale_label(scale))
        current = self._current_row.line_index if self._current_row else None
        self._render_lyrics(self._current_dto)
        if current is not None:
            self.set_current_line(current)

    # ── 재생 연동 (현재 줄 강조·자동 스크롤) ──────────────────────
    _SCROLL_HOLD_SEC = 3.0   # 사용자가 직접 스크롤한 뒤 자동 스크롤을 멈추는 시간

    def _on_user_scroll(self) -> None:
        """사용자가 가사를 직접 훑는 중에는 화면을 끌고 가지 않는다."""
        self._scroll_hold_until = time.monotonic() + self._SCROLL_HOLD_SEC

    def _autoscroll_suppressed(self) -> bool:
        return time.monotonic() < self._scroll_hold_until

    def set_current_line(self, index: int | None) -> None:
        """재생 중인 가사 줄을 강조하고(필요하면) 보이도록 스크롤한다.

        ``index``는 ``SongInfoDTO.lyrics_lines`` 기준 인덱스다(빈 줄 때문에 화면 행
        순서와 다를 수 있어 ``_LyricRow.line_index``로 찾는다).
        """
        target = None
        if index is not None:
            target = next((r for r in self._rows if r.line_index == index), None)
        if target is self._current_row:
            return
        if self._current_row is not None:
            self._current_row.set_current(False)
        self._current_row = target
        if target is None:
            return
        target.set_current(True)
        if not self._autoscroll_suppressed():
            self._lyrics_scroll.ensureWidgetVisible(target, 0, target.height() * 2)

    def _toggle_lyrics_layout(self) -> None:
        """번역 배치를 원문 아래 ↔ 오른쪽으로 전환한다(세션 내 유지)."""
        self._side_by_side = not self._side_by_side
        self._layout_btn.setText("⬍" if self._side_by_side else "⬌")
        self._layout_btn.setToolTip(
            "번역을 아래에 표시" if self._side_by_side else "번역을 오른쪽에 표시"
        )
        self._render_lyrics(self._current_dto)

    # ── 편집 상호작용 ─────────────────────────────────────────────
    def lyrics_viewport(self):
        return self._lyrics_scroll.viewport()

    def enter_lyrics_edit(self) -> None:
        if not self._editable:
            return
        text = "\n".join(ln.original for ln in self._lyrics_lines)
        self._lyrics_editor.setPlainText(text)
        self._lyrics_stack.setCurrentIndex(self._STACK_EDIT)
        self._lyrics_editor.setFocus()

    def lyrics_editor(self):
        return self._lyrics_editor

    def commit_lyrics_edit(self) -> None:
        if self._lyrics_stack.currentIndex() != self._STACK_EDIT:
            return
        text = self._lyrics_editor.toPlainText()
        self._lyrics_stack.setCurrentIndex(self._STACK_VIEW)
        new_lines = [LyricsLine(original=ln, translation="") for ln in text.split("\n")]
        old_originals = [ln.original for ln in self._lyrics_lines]
        if [ln.original for ln in new_lines] != old_originals:
            self._lyrics_lines = new_lines
            self.lyrics_edited.emit(new_lines)

    def _on_flag_toggled(self, checked: bool) -> None:
        if self._editable:
            self.flag_toggled.emit(checked)
