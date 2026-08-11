"""설정 패널 — 인라인 QWidget (다이얼로그 아님).

사이드바 ⚙ 아이콘 클릭 시 메인 콘텐츠 스택에 표시된다.
테마 프리셋 선택 + 일반/다운로드 설정 + 저장 경로 표시 + 숨김 태그 관리.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Callable

from PyQt6.QtCore import QByteArray, QMimeData, QSize, Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QColor, QDesktopServices, QFont, QPainter, QPainterPath
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)

from gui.themes.manager import ThemeManager
from gui.themes.tokens import PRESETS, ThemeTokens
from version import __version__
from gui.themes.colors import sem

logger = logging.getLogger(__name__)


def _t():
    return ThemeManager.instance().current()


def open_folder(path) -> None:
    """OS 파일 탐색기로 폴더를 연다 — 경로를 직접 찾아 입력할 필요를 없앤다."""
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


# 쿠키 파일 등록 방법 안내 — "이건 컴퓨터 전문가용 앱이 아니다"는 사용자 신고에 따라,
# 브라우저 프로필 자동 감지가 전혀 동작하지 않는 환경(기업 보안 정책, 지원되지 않는
# 브라우저 등)에서도 일반 사용자가 이해할 수 있는 대체 경로를 안내한다.
COOKIE_HELP_TEXT = (
    "브라우저/프로필 자동 감지가 계속 실패한다면, 쿠키 파일을 직접 등록하는 "
    "방법이 가장 확실합니다.\n\n"
    "1. 사용 중인 브라우저의 웹 스토어에서 'Get cookies.txt LOCALLY' (또는 "
    "'cookies.txt') 확장 프로그램을 설치하세요.\n"
    "2. www.youtube.com 에 접속해 로그인되어 있는지 확인하세요.\n"
    "3. 확장 프로그램 아이콘을 클릭하고 '내보내기(Export)'를 눌러 쿠키 파일을 "
    "저장하세요. 특별히 지정하지 않으면 보통 다운로드 폴더에 저장됩니다.\n"
    "4. 이 설정 화면으로 돌아와 '다시 검색'을 누르면 저장한 파일이 "
    "'감지된 쿠키 파일' 목록에 나타납니다. 선택하면 끝입니다.\n\n"
    "문제가 계속되면 아래 '로그 폴더 열기'로 연 폴더의 app.log 파일을 함께 "
    "보내주세요."
)


class _ThemeCard(QWidget):
    """테마 프리셋 선택 카드 — 미니 창 목업 + 이름."""

    _CARD_W = 80
    _CARD_H = 56

    def __init__(self, tokens: ThemeTokens, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._tokens = tokens
        self._selected = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedWidth(self._CARD_W + 16)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # 미리보기 캔버스
        self._preview = _ThemePreview(tokens)
        self._preview.setFixedSize(self._CARD_W, self._CARD_H)
        layout.addWidget(self._preview, alignment=Qt.AlignmentFlag.AlignHCenter)

        # 이름 레이블 — 카드가 놓인 배경은 "현재" 테마이므로 미리보기 테마 색이 아니라
        # 현재 테마 색으로 칠해야 한다(어두운 프리셋 이름이 밝은 배경에서 흐려지지 않게).
        self._name_lbl = QLabel(tokens.display_name)
        self._name_lbl.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.set_selected(False)
        layout.addWidget(self._name_lbl)

    # ------------------------------------------------------------------
    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        self._preview.set_selected(selected)
        cur = _t()
        color = cur.accent if selected else cur.text_secondary
        weight = "600" if selected else "500"
        self._name_lbl.setStyleSheet(
            f"font-size: 11px; font-weight: {weight}; color: {color};"
        )

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        ThemeManager.instance().apply(self._tokens.name)


class _ThemePreview(QWidget):
    """테마 미리보기 — QPainter로 미니 창을 그린다."""

    def __init__(self, tokens: ThemeTokens, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._tokens = tokens
        self._selected = False

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        self.update()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        tok = self._tokens
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        r = 5  # corner radius

        # 외곽 테두리 (선택 시 액센트 색상)
        border_color = tok.selected_border if self._selected else tok.border_muted
        border_w = 2 if self._selected else 1

        # 배경
        path = QPainterPath()
        path.addRoundedRect(0, 0, w, h, r, r)
        p.fillPath(path, QColor(tok.bg_base))

        # 테두리
        pen = p.pen()
        pen.setColor(QColor(border_color))
        pen.setWidth(border_w)
        p.setPen(pen)
        p.drawRoundedRect(border_w // 2, border_w // 2,
                          w - border_w, h - border_w, r, r)

        # 사이드바 (좌측 10px)
        sb_w = 10
        p.fillRect(border_w, border_w, sb_w, h - border_w * 2,
                   QColor(tok.bg_surface))

        # 사이드바 아이콘 점
        dot_x = border_w + sb_w // 2 - 2
        p.fillRect(dot_x, 8, 4, 4, QColor(tok.accent))
        p.fillRect(dot_x, 16, 4, 4, QColor(tok.bg_overlay))
        p.fillRect(dot_x, 24, 4, 4, QColor(tok.bg_overlay))

        # 콘텐츠 영역 카드들
        cx = border_w + sb_w + 4
        cw = (w - cx - border_w - 4) // 3 - 2
        ch = (h - border_w * 2 - 12) // 2 - 1
        for col in range(3):
            card_x = cx + col * (cw + 2)
            p.fillRect(card_x, border_w + 8, cw, ch, QColor(tok.bg_elevated))

        # 상단 바 (URL 바)
        p.fillRect(border_w + sb_w, border_w, w - border_w - sb_w - border_w,
                   7, QColor(tok.bg_surface))

        p.end()


# ---------------------------------------------------------------------------
# 태그 이동 목록 (드래그 앤 드롭 지원)
# ---------------------------------------------------------------------------

_MOVE_MIME = "application/x-settings-tag-name"


class _TagMoveDelegate(QStyledItemDelegate):
    """태그 이름(왼쪽)과 영상 수(오른쪽)를 나란히 그리는 델리게이트."""

    def sizeHint(self, option, index) -> QSize:
        return QSize(max(option.rect.width(), 160), 26)

    def paint(self, painter, option, index) -> None:
        from PyQt6.QtWidgets import QApplication, QStyle  # noqa: PLC0415
        QApplication.style().drawPrimitive(
            QStyle.PrimitiveElement.PE_PanelItemViewItem, option, painter, option.widget
        )
        name  = index.data(Qt.ItemDataRole.UserRole + 2) or ""
        count = index.data(Qt.ItemDataRole.UserRole + 1) or 0
        tok   = _t()
        selected = bool(option.state & QStyle.StateFlag.State_Selected)

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 태그명
        painter.setFont(QFont("", 9))
        painter.setPen(QColor(tok.text_on_accent if selected else tok.text_primary))
        name_rect = option.rect.adjusted(8, 0, -44, 0)
        painter.drawText(
            name_rect,
            Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextSingleLine,
            f"#{name}",
        )

        # 영상 수 뱃지
        painter.setFont(QFont("", 8))
        painter.setPen(QColor(tok.text_on_accent if selected else tok.text_muted))
        count_rect = option.rect.adjusted(0, 0, -6, 0)
        painter.drawText(
            count_rect,
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight | Qt.TextFlag.TextSingleLine,
            str(count),
        )

        painter.restore()


class _TagMoveList(QListWidget):
    """다른 _TagMoveList로부터의 드래그 드롭을 수락하는 태그 목록."""

    drop_received = pyqtSignal(list)  # list[str] — tag names

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setItemDelegate(_TagMoveDelegate(self))
        self.setSpacing(1)

    def mimeTypes(self) -> list[str]:
        return [_MOVE_MIME]

    def mimeData(self, items) -> QMimeData:
        mime = QMimeData()
        names = [i.data(Qt.ItemDataRole.UserRole + 2) for i in items
                 if i.data(Qt.ItemDataRole.UserRole + 2)]
        mime.setData(_MOVE_MIME, QByteArray("|".join(names).encode()))
        return mime

    def dragEnterEvent(self, event) -> None:
        if event.source() is not self and event.mimeData().hasFormat(_MOVE_MIME):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:
        if event.source() is not self and event.mimeData().hasFormat(_MOVE_MIME):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:
        if event.source() is not self and event.mimeData().hasFormat(_MOVE_MIME):
            raw   = bytes(event.mimeData().data(_MOVE_MIME)).decode()
            names = [n for n in raw.split("|") if n]
            if names:
                self.drop_received.emit(names)
            event.acceptProposedAction()
        else:
            event.ignore()


class _HiddenTagsSection(QWidget):
    """태그 숨김 관리 섹션 — 표시 태그 ↔ 숨긴 태그 두 목록."""

    changed = pyqtSignal()

    def __init__(
        self,
        get_tags_fn: Callable,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._get_tags = get_tags_fn
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        # 안내 문구
        hint = QLabel(
            "표시 태그를 더블클릭하거나 오른쪽으로 드래그하면 태그 목록에서 숨겨집니다."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(f"font-size: 10px; color: {_t().text_secondary}; margin-bottom: 4px;")
        root.addWidget(hint)

        lists_row = QHBoxLayout()
        lists_row.setSpacing(12)

        # ── 표시 태그 ──────────────────────────────────
        vis_col = QVBoxLayout()
        vis_col.setSpacing(4)
        vis_lbl = QLabel("표시 태그  (더블클릭 → 숨기기)")
        vis_lbl.setStyleSheet("font-size: 10px; font-weight: 600;")
        self._vis_list = _TagMoveList()
        self._vis_list.setMinimumHeight(200)
        self._vis_list.itemDoubleClicked.connect(
            lambda item: self._move_to_hidden([item.data(Qt.ItemDataRole.UserRole + 2)])
        )
        self._vis_list.drop_received.connect(self._move_to_visible)
        vis_col.addWidget(vis_lbl)
        vis_col.addWidget(self._vis_list)
        lists_row.addLayout(vis_col)

        # ── 화살표 힌트 ───────────────────────────────
        arrow_col = QVBoxLayout()
        arrow_col.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        lbl_r = QLabel("→")
        lbl_l = QLabel("←")
        for lbl in (lbl_r, lbl_l):
            lbl.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            lbl.setStyleSheet(f"font-size: 14px; color: {_t().text_secondary};")
        arrow_col.addStretch()
        arrow_col.addWidget(lbl_r)
        arrow_col.addSpacing(8)
        arrow_col.addWidget(lbl_l)
        arrow_col.addStretch()
        lists_row.addLayout(arrow_col)

        # ── 숨긴 태그 ──────────────────────────────────
        hid_col = QVBoxLayout()
        hid_col.setSpacing(4)
        hid_lbl = QLabel("숨긴 태그  (더블클릭 → 표시)")
        hid_lbl.setStyleSheet("font-size: 10px; font-weight: 600;")
        self._hid_list = _TagMoveList()
        self._hid_list.setMinimumHeight(200)
        self._hid_list.itemDoubleClicked.connect(
            lambda item: self._move_to_visible([item.data(Qt.ItemDataRole.UserRole + 2)])
        )
        self._hid_list.drop_received.connect(self._move_to_hidden)
        hid_col.addWidget(hid_lbl)
        hid_col.addWidget(self._hid_list)
        lists_row.addLayout(hid_col)

        root.addLayout(lists_row)

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        """태그 목록을 새로 불러와 두 목록을 재구성한다."""
        from config.settings import load_hidden_tag_names  # noqa: PLC0415
        hidden_names = load_hidden_tag_names()
        all_tags = sorted(self._get_tags(), key=lambda t: t.name)

        self._vis_list.clear()
        self._hid_list.clear()

        for tag in all_tags:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole,     tag.id)
            item.setData(Qt.ItemDataRole.UserRole + 1, tag.count)
            item.setData(Qt.ItemDataRole.UserRole + 2, tag.name)
            if tag.name in hidden_names:
                self._hid_list.addItem(item)
            else:
                self._vis_list.addItem(item)

    # ------------------------------------------------------------------
    def _move_to_hidden(self, names: list[str]) -> None:
        from config.settings import load_hidden_tag_names, save_hidden_tag_names  # noqa: PLC0415
        hidden = load_hidden_tag_names()
        for n in names:
            hidden.add(n)
        save_hidden_tag_names(hidden)
        self.refresh()
        self.changed.emit()

    def _move_to_visible(self, names: list[str]) -> None:
        from config.settings import load_hidden_tag_names, save_hidden_tag_names  # noqa: PLC0415
        hidden = load_hidden_tag_names()
        for n in names:
            hidden.discard(n)
        save_hidden_tag_names(hidden)
        self.refresh()
        self.changed.emit()


# ---------------------------------------------------------------------------
# 설정 패널
# ---------------------------------------------------------------------------


class _LyricsSourcesSection(QWidget):
    """가사·메타데이터 출처(사이트) 관리형 목록 — 활성/순서/추가/삭제.

    노래 상세 탭이 가사를 조회할 때 이 목록을 priority 순으로 순회한다. 사용자가
    출처를 켜고/끄고, 순서를 바꾸고, 커스텀 출처를 추가할 수 있게 한다(확장 가능).
    """

    def __init__(self, song_vm, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._vm = song_vm
        self._ordered_ids: list = []
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        self._rows_holder = QWidget()
        self._rows_layout = QVBoxLayout(self._rows_holder)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(4)
        root.addWidget(self._rows_holder)

        add_row = QHBoxLayout()
        add_row.setSpacing(6)
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("이름 (예: 가사위키)")
        self._key_edit = QLineEdit()
        self._key_edit.setPlaceholderText("provider_key (lrclib/genius/melon/bugs/genie)")
        add_btn = QPushButton("추가")
        add_btn.clicked.connect(self._on_add)
        add_row.addWidget(self._name_edit, 2)
        add_row.addWidget(self._key_edit, 2)
        add_row.addWidget(add_btn)
        root.addLayout(add_row)

        hint = QLabel(
            "위에서 아래 순서로 조회하며 부족한 항목을 채웁니다. 체크 해제 시 건너뜁니다."
        )
        hint.setStyleSheet(f"font-size: 10px; color: {_t().text_muted};")
        hint.setWordWrap(True)
        root.addWidget(hint)

        if self._vm is not None:
            self._vm.sources_changed.connect(self.reload)
        self.reload()

    def reload(self) -> None:
        while self._rows_layout.count():
            item = self._rows_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if self._vm is None:
            return
        sources = self._vm.list_lyrics_sources()
        self._ordered_ids = [s.id for s in sources]
        for idx, s in enumerate(sources):
            self._rows_layout.addWidget(self._build_row(idx, s, len(sources)))

    def _build_row(self, idx: int, src, total: int) -> QWidget:
        tok = _t()
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(6, 2, 6, 2)
        rl.setSpacing(8)

        chk = QCheckBox()
        chk.setChecked(src.enabled)
        chk.setToolTip("이 출처 사용")
        chk.toggled.connect(lambda on, sid=src.id: self._vm.update_lyrics_source(sid, enabled=on))
        rl.addWidget(chk)

        name = QLabel(f"{src.name}  ·  {src.provider_key}")
        name.setStyleSheet(f"font-size: 11px; color: {tok.text_primary};")
        rl.addWidget(name, 1)

        up = QPushButton("▲")
        up.setFixedSize(24, 24)
        up.setEnabled(idx > 0)
        up.clicked.connect(lambda _, i=idx: self._move(i, -1))
        rl.addWidget(up)
        down = QPushButton("▼")
        down.setFixedSize(24, 24)
        down.setEnabled(idx < total - 1)
        down.clicked.connect(lambda _, i=idx: self._move(i, +1))
        rl.addWidget(down)
        dele = QPushButton("삭제")
        dele.setFixedHeight(24)
        dele.clicked.connect(lambda _, sid=src.id: self._vm.delete_lyrics_source(sid))
        rl.addWidget(dele)
        return row

    def _move(self, idx: int, delta: int) -> None:
        ids = list(self._ordered_ids)
        j = idx + delta
        if 0 <= j < len(ids):
            ids[idx], ids[j] = ids[j], ids[idx]
            self._vm.reorder_lyrics_sources(ids)

    def _on_add(self) -> None:
        name = self._name_edit.text().strip()
        key = self._key_edit.text().strip()
        if not name or not key:
            return
        self._vm.add_lyrics_source(name, key)
        self._name_edit.clear()
        self._key_edit.clear()


class _CloudSyncSection(QWidget):
    """클라우드 동기화 연결/해제·상태·지금 동기화 UI (SyncViewModel 주입 시에만 표시).

    provider(Google Drive/OneDrive) 선택 + OAuth 자격증명 입력 → 연결. 연결되면 상태·계정을
    표시하고 '지금 동기화' 버튼을 노출한다. 실제 OAuth·동기화는 sync_vm이 QThread로 수행.
    """

    def __init__(self, sync_vm, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._vm = sync_vm
        self._build()
        sync_vm.status_changed.connect(self._on_status)
        sync_vm.busy_changed.connect(self._on_busy)
        sync_vm.sync_finished.connect(self._on_sync_finished)
        sync_vm.error_occurred.connect(self._on_error)
        self._vm.refresh_status()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        # 안내 — 폴더 방식이 기본. 로그인·개발자 설정 없이 바로 동기화.
        help_lbl = QLabel(
            "여러 PC에서 라이브러리·메모·다운로드 이력·미디어 파일을 동기화합니다.\n"
            "OneDrive/Google Drive 데스크톱 앱이 동기화하는 폴더를 지정하면 로그인 없이 바로 "
            "동기화됩니다. 다른 PC에서도 같은 폴더(그 PC의 OneDrive 안 같은 위치)를 지정하세요."
        )
        help_lbl.setWordWrap(True)
        help_lbl.setStyleSheet(f"color: {_t().text_secondary}; font-size: 11px;")
        root.addWidget(help_lbl)

        # 로컬 폴더 경로 행 (기본 방식)
        folder_row = QHBoxLayout()
        self._folder_path = QLineEdit()
        detected = os.environ.get("OneDrive") or os.environ.get("OneDriveConsumer")
        if detected:
            self._folder_path.setText(str(Path(detected) / "ovc-sync"))
        self._folder_path.setPlaceholderText("예: C:/Users/나/OneDrive/ovc-sync")
        self._browse_btn = QPushButton("찾아보기…")
        self._browse_btn.clicked.connect(self._on_browse)
        folder_row.addWidget(self._folder_path, 1)
        folder_row.addWidget(self._browse_btn)
        self._folder_row_widget = QWidget()
        self._folder_row_widget.setLayout(folder_row)
        root.addWidget(self._folder_row_widget)

        # 고급: 클라우드 API 직접 연결(OAuth) — 기본 숨김.
        self._advanced_check = QCheckBox("고급: 클라우드 API로 직접 연결 (OAuth)")
        self._advanced_check.toggled.connect(self._on_advanced_toggled)
        root.addWidget(self._advanced_check)

        self._api_box = QWidget()
        api_layout = QVBoxLayout(self._api_box)
        api_layout.setContentsMargins(0, 0, 0, 0)
        prov_row = QHBoxLayout()
        prov_row.addWidget(QLabel("제공자"))
        self._provider_combo = QComboBox()
        self._provider_combo.addItem("Google Drive", "gdrive")
        self._provider_combo.addItem("OneDrive", "onedrive")
        self._provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        prov_row.addWidget(self._provider_combo)
        prov_row.addStretch()
        api_layout.addLayout(prov_row)
        self._client_id = QLineEdit()
        self._client_id.setPlaceholderText("OAuth Client ID")
        api_layout.addWidget(self._client_id)
        self._client_secret = QLineEdit()
        self._client_secret.setPlaceholderText("OAuth Client Secret (Google Drive)")
        self._client_secret.setEchoMode(QLineEdit.EchoMode.Password)
        api_layout.addWidget(self._client_secret)
        self._api_box.setVisible(False)
        root.addWidget(self._api_box)

        btn_row = QHBoxLayout()
        self._connect_btn = QPushButton("연결")
        self._connect_btn.clicked.connect(self._on_connect)
        self._disconnect_btn = QPushButton("연결 해제")
        self._disconnect_btn.clicked.connect(self._vm.disconnect)
        self._sync_btn = QPushButton("지금 동기화")
        self._sync_btn.clicked.connect(self._vm.sync_now)
        btn_row.addWidget(self._connect_btn)
        btn_row.addWidget(self._disconnect_btn)
        btn_row.addWidget(self._sync_btn)
        btn_row.addStretch()
        root.addLayout(btn_row)

        self._status_lbl = QLabel("상태 확인 중…")
        self._status_lbl.setStyleSheet(f"color: {_t().text_secondary}; font-size: 11px;")
        self._status_lbl.setWordWrap(True)
        root.addWidget(self._status_lbl)
        self._on_provider_changed()

    def _on_advanced_toggled(self, checked: bool) -> None:
        # 고급(API) 모드 ↔ 폴더 모드 전환.
        self._api_box.setVisible(checked)
        self._folder_row_widget.setVisible(not checked)

    def _on_provider_changed(self) -> None:
        # OneDrive는 client secret 불필요(공용 클라이언트).
        self._client_secret.setVisible(self._provider_combo.currentData() == "gdrive")

    def _on_browse(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "동기화 폴더 선택")
        if path:
            self._folder_path.setText(path)

    def _on_connect(self) -> None:
        # 기본(고급 미체크) = 폴더 방식.
        if not self._advanced_check.isChecked():
            path = self._folder_path.text().strip()
            if not path:
                self._status_lbl.setText("동기화 폴더를 선택하세요.")
                return
            self._vm.connect("folder", folder_path=path)
            self._status_lbl.setText("폴더 연결 중…")
            return
        key = self._provider_combo.currentData()
        cid = self._client_id.text().strip()
        if not cid:
            self._status_lbl.setText("Client ID를 입력하세요.")
            return
        if key == "gdrive":
            secret = self._client_secret.text().strip()
            if not secret:
                self._status_lbl.setText("Google Drive는 Client Secret이 필요합니다.")
                return
            self._vm.connect(key, client_id=cid, client_secret=secret)
        else:
            self._vm.connect(key, client_id=cid)
        self._status_lbl.setText("브라우저에서 인증을 진행하세요…")

    def _on_status(self, dto) -> None:
        if dto is None:
            return
        if dto.connected:
            acct = dto.account_name or "(계정 미상)"
            last = dto.last_pull_utc[:19].replace("T", " ") if dto.last_pull_utc else "없음"
            self._status_lbl.setText(f"연결됨: {acct} · 마지막 동기화: {last}")
            self._connect_btn.setEnabled(False)
            self._disconnect_btn.setEnabled(True)
            self._sync_btn.setEnabled(True)
        else:
            self._status_lbl.setText("연결 안 됨")
            self._connect_btn.setEnabled(True)
            self._disconnect_btn.setEnabled(False)
            self._sync_btn.setEnabled(False)

    def _on_busy(self, busy: bool) -> None:
        # 작업 중엔 버튼 잠금(상태 라벨로 진행 표시).
        self._connect_btn.setEnabled(not busy)
        self._sync_btn.setEnabled(not busy and self._vm.is_connected())

    def _on_sync_finished(self, pushed: int, pulled: int) -> None:
        self._status_lbl.setText(f"동기화 완료 (올림 {pushed} · 내려받음 {pulled})")

    def _on_error(self, msg: str) -> None:
        self._status_lbl.setText(f"오류: {msg}")


class _ImportExportSection(QWidget):
    """라이브러리 가져오기/내보내기 UI (transfer_vm 주입 시에만 표시).

    내보내기: 카테고리 체크트리(``CategorySelectDialog``) → 저장 위치 선택 → 백그라운드
    내보내기. 가져오기: 패키지 파일 선택 → 미리보기(카테고리 체크트리) → 충돌 감지 →
    값이 다른 영상이 있으면 필드별 선택(``ImportConflictResolutionDialog``) → 병합.
    실제 파일 I/O·병합 로직은 전부 transfer_vm(QThread)이 수행하고, 이 위젯은 다이얼로그
    순서만 조율한다.
    """

    def __init__(self, transfer_vm, get_categories_fn, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._vm = transfer_vm
        self._get_categories_fn = get_categories_fn
        self._archive_path = ""
        self._import_category_ids: list[str] = []
        self._build()
        transfer_vm.export_finished.connect(self._on_export_finished)
        transfer_vm.preview_ready.connect(self._on_preview_ready)
        transfer_vm.conflicts_ready.connect(self._on_conflicts_ready)
        transfer_vm.import_finished.connect(self._on_import_finished)
        transfer_vm.error_occurred.connect(self._on_error)
        transfer_vm.busy_changed.connect(self._on_busy_changed)

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        help_lbl = QLabel(
            "선택한 카테고리의 영상·태그·노래 정보(가사·싱크 오프셋)를 파일 하나로 내보내\n"
            "다른 사람에게 전달하거나 백업할 수 있습니다. 가져올 때 같은 이름의 카테고리는\n"
            "합쳐지고, 이미 있는 영상은 값이 다른 항목만 골라서 반영합니다."
        )
        help_lbl.setWordWrap(True)
        help_lbl.setStyleSheet(f"color: {_t().text_secondary}; font-size: 11px;")
        root.addWidget(help_lbl)

        btn_row = QHBoxLayout()
        self._export_btn = QPushButton("내보내기…")
        self._import_btn = QPushButton("가져오기…")
        self._export_btn.clicked.connect(self._on_export_clicked)
        self._import_btn.clicked.connect(self._on_import_clicked)
        btn_row.addWidget(self._export_btn)
        btn_row.addWidget(self._import_btn)
        btn_row.addStretch()
        root.addLayout(btn_row)

        self._status_lbl = QLabel("")
        self._status_lbl.setWordWrap(True)
        self._status_lbl.setStyleSheet(f"font-size: 9pt; color: {_t().text_secondary};")
        root.addWidget(self._status_lbl)

    # ── 내보내기 ──────────────────────────────────────────────────────────

    def _on_export_clicked(self) -> None:
        from gui.dialogs.library_transfer_dialogs import CategorySelectDialog  # noqa: PLC0415

        categories = self._get_categories_fn() if self._get_categories_fn else []
        if not categories:
            self._status_lbl.setText("내보낼 카테고리가 없습니다.")
            return
        dlg = CategorySelectDialog(categories, "내보낼 카테고리 선택", self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        selected = dlg.selected_category_ids()
        if not selected:
            self._status_lbl.setText("내보낼 카테고리를 선택하세요.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "내보내기", "", "라이브러리 패키지 (*.ovcpkg)"
        )
        if not path:
            return
        if not path.lower().endswith(".ovcpkg"):
            path += ".ovcpkg"
        self._status_lbl.setText("내보내는 중…")
        self._vm.export_library(selected, path)

    def _on_export_finished(self, result) -> None:
        self._status_lbl.setText(
            f"● 내보내기 완료 — 카테고리 {result.category_count}개, "
            f"영상 {result.video_count}개 → {result.path}"
        )

    # ── 가져오기 ──────────────────────────────────────────────────────────

    def _on_import_clicked(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "가져오기", "", "라이브러리 패키지 (*.ovcpkg)"
        )
        if not path:
            return
        self._archive_path = path
        self._status_lbl.setText("패키지 확인 중…")
        self._vm.preview_import(path)

    def _on_preview_ready(self, preview) -> None:
        from gui.dialogs.library_transfer_dialogs import CategorySelectDialog  # noqa: PLC0415

        if not preview.categories:
            self._status_lbl.setText("패키지에 카테고리가 없습니다.")
            return
        dlg = CategorySelectDialog(list(preview.categories), "가져올 카테고리 선택", self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            self._status_lbl.setText("")
            return
        selected = dlg.selected_category_ids()
        if not selected:
            self._status_lbl.setText("가져올 카테고리를 선택하세요.")
            return
        self._import_category_ids = selected
        self._status_lbl.setText("겹치는 영상 확인 중…")
        self._vm.detect_conflicts(self._archive_path, selected)

    def _on_conflicts_ready(self, conflicts_dto) -> None:
        from gui.dialogs.library_transfer_dialogs import (  # noqa: PLC0415
            ImportConflictResolutionDialog,
        )

        resolutions: dict[str, dict[str, str]] = {}
        if conflicts_dto.conflicts:
            dlg = ImportConflictResolutionDialog(conflicts_dto.conflicts, self)
            if dlg.exec() != QDialog.DialogCode.Accepted:
                self._status_lbl.setText("가져오기를 취소했습니다.")
                return
            resolutions = dlg.resolutions()
        self._status_lbl.setText("가져오는 중…")
        self._vm.import_library(self._archive_path, self._import_category_ids, resolutions)

    def _on_import_finished(self, result) -> None:
        self._status_lbl.setText(
            f"● 가져오기 완료 — 새 영상 {result.created_count}개, "
            f"병합 {result.merged_count}개, 카테고리 {result.category_count}개"
        )

    def _on_error(self, msg: str) -> None:
        self._status_lbl.setText(f"오류: {msg[:200]}")

    def _on_busy_changed(self, busy: bool) -> None:
        self._export_btn.setEnabled(not busy)
        self._import_btn.setEnabled(not busy)


class SettingsPanel(QWidget):
    """설정 패널 (인라인, QDialog 아님)."""

    hidden_tags_changed = pyqtSignal()
    feed_workers_changed = pyqtSignal(int)
    check_update_requested = pyqtSignal()
    install_update_requested = pyqtSignal(object)   # UpdateDTO

    def __init__(
        self,
        get_tags_fn: Callable | None = None,
        yt_oauth=None,   # YouTubeOAuthAdapter | None
        song_vm=None,    # SongViewModel | None
        sync_vm=None,    # SyncViewModel | None
        transfer_vm=None,        # LibraryTransferViewModel | None
        get_categories_fn: Callable | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._get_tags_fn = get_tags_fn
        self._yt_oauth = yt_oauth
        self._song_vm = song_vm
        self._sync_vm = sync_vm
        self._transfer_vm = transfer_vm
        self._get_categories_fn = get_categories_fn
        self._theme_cards: dict[str, _ThemeCard] = {}
        self._yt_auth_worker = None
        self._pending_dto = None
        self._flash_timer = None
        self._flash_count = 0
        self._build_ui()
        ThemeManager.instance().theme_changed.connect(self._on_theme_changed)
        self._on_theme_changed(ThemeManager.instance().current())

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        scroll = QScrollArea(self)
        self._scroll_area = scroll
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.addWidget(scroll)

        content = QWidget()
        scroll.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(0)

        # 헤더 + 우측 컴팩트 업데이트 상태
        header_row = QHBoxLayout()
        header = QLabel("설정")
        header.setStyleSheet("font-size: 16px; font-weight: 600;")
        header_row.addWidget(header)
        header_row.addStretch()
        header_row.addWidget(self._build_update_header())
        layout.addLayout(header_row)
        layout.addSpacing(20)

        # ── 테마 섹션 ──
        theme_label = QLabel("테마")
        theme_label.setStyleSheet(
            "font-size: 9px; font-weight: 600; letter-spacing: 0.8px; "
            f"text-transform: uppercase; color: {_t().text_muted}; margin-bottom: 12px;"
        )
        layout.addWidget(theme_label)
        layout.addSpacing(10)

        # 프리셋이 늘어 한 줄에 다 들어가지 않으므로 격자로 배치한다.
        cards_grid = QGridLayout()
        cards_grid.setContentsMargins(0, 0, 0, 0)
        cards_grid.setHorizontalSpacing(16)
        cards_grid.setVerticalSpacing(14)
        per_row = 6
        for i, (name, tokens) in enumerate(PRESETS.items()):
            card = _ThemeCard(tokens)
            self._theme_cards[name] = card
            cards_grid.addWidget(card, i // per_row, i % per_row)
        cards_grid.setColumnStretch(per_row, 1)

        layout.addLayout(cards_grid)
        layout.addSpacing(8)

        hint = QLabel("클릭하면 즉시 적용됩니다. 재시작 후에도 유지됩니다.")
        hint.setStyleSheet(f"font-size: 10px; color: {_t().text_muted}; margin-top: 4px;")
        layout.addWidget(hint)
        layout.addSpacing(28)

        # ── 구분선 ──
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {_t().border};")
        layout.addWidget(sep)
        layout.addSpacing(24)

        # ── 저장 경로 섹션 ──
        path_label = QLabel("저장 경로")
        path_label.setStyleSheet(
            "font-size: 9px; font-weight: 600; letter-spacing: 0.8px; "
            f"text-transform: uppercase; color: {_t().text_muted}; margin-bottom: 12px;"
        )
        layout.addWidget(path_label)
        layout.addSpacing(10)

        try:
            from config import settings as s
            paths = {
                "데이터베이스": str(s.DATABASE_PATH),
                "다운로드 폴더": str(s.DOWNLOAD_DIR),
                "썸네일 폴더": str(s.THUMBNAIL_DIR),
                "로그 폴더": str(s.LOG_DIR),
            }
        except Exception:
            logger.exception("설정 경로 로드 실패")
            paths = {}

        for label_text, path_text in paths.items():
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(12)
            lbl = QLabel(label_text)
            lbl.setFixedWidth(90)
            lbl.setStyleSheet(f"font-size: 11px; color: {_t().text_muted};")
            val = QLabel(path_text)
            val.setStyleSheet(
                f"font-size: 10px; color: {_t().text_muted}; font-family: monospace;"
            )
            val.setWordWrap(False)
            val.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
            )
            open_btn = QPushButton("열기")
            open_btn.setFixedWidth(48)
            open_btn.clicked.connect(lambda _checked=False, p=path_text: open_folder(p))
            row.addWidget(lbl)
            row.addWidget(val, 1)
            row.addWidget(open_btn)
            layout.addLayout(row)
            layout.addSpacing(6)

        note = QLabel("경로를 변경하려면 data/config.yaml 을 편집하세요.")
        note.setStyleSheet(f"font-size: 10px; color: {_t().text_muted}; margin-top: 8px;")
        layout.addWidget(note)
        layout.addSpacing(28)

        # ── 구분선 ──
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet(f"color: {_t().border};")
        layout.addWidget(sep2)
        layout.addSpacing(24)

        # ── 일반 섹션 ──
        gen_label = QLabel("일반")
        gen_label.setStyleSheet(
            "font-size: 9px; font-weight: 600; letter-spacing: 0.8px; "
            f"text-transform: uppercase; color: {_t().text_muted}; margin-bottom: 12px;"
        )
        layout.addWidget(gen_label)
        layout.addSpacing(10)

        try:
            from config import settings as s
            cur_concurrent = s.MAX_CONCURRENT_DOWNLOADS
            cur_feed_workers = s.MAX_CONCURRENT_FEED_WORKERS
            cur_clipboard = s.CLIPBOARD_MONITORING
            cur_auto_enrich = s.AUTO_ENRICH_ON_ADD
        except Exception:
            logger.exception("일반 설정 로드 실패")
            cur_concurrent = 3
            cur_feed_workers = 4
            cur_clipboard = True
            cur_auto_enrich = True

        # 동시 다운로드 수
        concurrent_row = QHBoxLayout()
        concurrent_row.setContentsMargins(0, 0, 0, 0)
        concurrent_lbl = QLabel("동시 다운로드 수")
        concurrent_lbl.setFixedWidth(130)
        concurrent_lbl.setStyleSheet("font-size: 11px;")
        self._concurrent_spin = QSpinBox()
        self._concurrent_spin.setRange(1, 8)
        self._concurrent_spin.setValue(cur_concurrent)
        self._concurrent_spin.setFixedWidth(64)
        self._concurrent_spin.valueChanged.connect(self._on_concurrent_changed)
        concurrent_row.addWidget(concurrent_lbl)
        concurrent_row.addWidget(self._concurrent_spin)
        concurrent_row.addStretch()
        layout.addLayout(concurrent_row)
        layout.addSpacing(10)

        # 노드 동시 로딩 수 (피드·채널·카테고리·재생목록 등 모든 트리 노드 공통)
        feed_workers_row = QHBoxLayout()
        feed_workers_row.setContentsMargins(0, 0, 0, 0)
        feed_workers_lbl = QLabel("노드 동시 로딩 수")
        feed_workers_lbl.setFixedWidth(130)
        feed_workers_lbl.setStyleSheet("font-size: 11px;")
        self._feed_workers_spin = QSpinBox()
        self._feed_workers_spin.setRange(1, 8)
        self._feed_workers_spin.setValue(cur_feed_workers)
        self._feed_workers_spin.setFixedWidth(64)
        self._feed_workers_spin.valueChanged.connect(self._on_feed_workers_changed)
        feed_workers_row.addWidget(feed_workers_lbl)
        feed_workers_row.addWidget(self._feed_workers_spin)
        feed_workers_row.addStretch()
        layout.addLayout(feed_workers_row)
        layout.addSpacing(10)

        # 클립보드 URL 자동 감지
        self._clipboard_check = QCheckBox("클립보드 URL 자동 감지")
        self._clipboard_check.setChecked(cur_clipboard)
        self._clipboard_check.checkStateChanged.connect(self._on_clipboard_changed)
        layout.addWidget(self._clipboard_check)
        layout.addSpacing(10)

        # 등록 시 요약·가사 자동 채우기
        self._auto_enrich_check = QCheckBox("등록 시 요약·가사 자동 채우기")
        self._auto_enrich_check.setChecked(cur_auto_enrich)
        self._auto_enrich_check.checkStateChanged.connect(self._on_auto_enrich_changed)
        layout.addWidget(self._auto_enrich_check)

        enrich_hint = QLabel(
            "영상을 한 건씩 등록할 때 음원용 영상은 가사를, 그 외 영상은 Gemini 요약을 "
            "백그라운드에서 채웁니다. 재생목록·채널 일괄 가져오기는 대상이 아닙니다.\n"
            "요약은 YouTube 로그인 쿠키가 필요합니다 — Chrome 127 이상은 쿠키 자동 추출이 "
            "불가하므로 아래 인증 섹션에서 쿠키 파일을 직접 등록해야 합니다."
        )
        enrich_hint.setWordWrap(True)
        enrich_hint.setStyleSheet(f"font-size: 10px; color: {_t().text_secondary}; margin-left: 22px;")
        layout.addWidget(enrich_hint)
        layout.addSpacing(28)

        # ── 구분선 ──
        sep3 = QFrame()
        sep3.setFrameShape(QFrame.Shape.HLine)
        sep3.setStyleSheet(f"color: {_t().border};")
        layout.addWidget(sep3)
        layout.addSpacing(24)

        # ── 다운로드 섹션 ──
        dl_label = QLabel("다운로드")
        dl_label.setStyleSheet(
            "font-size: 9px; font-weight: 600; letter-spacing: 0.8px; "
            f"text-transform: uppercase; color: {_t().text_muted}; margin-bottom: 12px;"
        )
        layout.addWidget(dl_label)
        layout.addSpacing(10)

        try:
            from config import settings as s
            cur_dl_dir = str(s.DOWNLOAD_DIR)
            cur_quality = s.DEFAULT_QUALITY
            cur_format = s.DEFAULT_FORMAT
        except Exception:
            logger.exception("다운로드 설정 로드 실패")
            cur_dl_dir = ""
            cur_quality = "best[ext=mp4]/best"
            cur_format = "mp4"

        # 다운로드 폴더
        folder_row = QHBoxLayout()
        folder_row.setContentsMargins(0, 0, 0, 0)
        folder_lbl = QLabel("다운로드 폴더")
        folder_lbl.setFixedWidth(100)
        folder_lbl.setStyleSheet("font-size: 11px;")
        self._folder_edit = QLineEdit(cur_dl_dir)
        self._folder_edit.setReadOnly(True)
        self._folder_edit.setStyleSheet("font-size: 10px; font-family: monospace;")
        browse_btn = QPushButton("찾아보기")
        browse_btn.setFixedWidth(72)
        browse_btn.clicked.connect(self._on_browse_folder)
        folder_row.addWidget(folder_lbl)
        folder_row.addWidget(self._folder_edit, 1)
        folder_row.addWidget(browse_btn)
        layout.addLayout(folder_row)
        layout.addSpacing(10)

        # 기본 품질
        quality_row = QHBoxLayout()
        quality_row.setContentsMargins(0, 0, 0, 0)
        quality_lbl = QLabel("기본 품질")
        quality_lbl.setFixedWidth(100)
        quality_lbl.setStyleSheet("font-size: 11px;")
        self._quality_combo = QComboBox()
        quality_options = [
            ("자동 (최고 품질)", "best[ext=mp4]/best"),
            ("4K / UHD (2160p)", "bestvideo[height<=2160][ext=mp4]+bestaudio/best[height<=2160]"),
            ("1440p / QHD", "bestvideo[height<=1440][ext=mp4]+bestaudio/best[height<=1440]"),
            ("1080p / FHD", "bestvideo[height<=1080][ext=mp4]+bestaudio/best[height<=1080]"),
            ("720p / HD", "bestvideo[height<=720][ext=mp4]+bestaudio/best[height<=720]"),
            ("480p", "bestvideo[height<=480][ext=mp4]+bestaudio/best[height<=480]"),
            ("360p", "bestvideo[height<=360][ext=mp4]+bestaudio/best[height<=360]"),
        ]
        for label, fmt in quality_options:
            self._quality_combo.addItem(label, fmt)
        matched = next((i for i, (_, f) in enumerate(quality_options) if f == cur_quality), 0)
        self._quality_combo.setCurrentIndex(matched)
        self._quality_combo.currentIndexChanged.connect(self._on_quality_changed)
        quality_row.addWidget(quality_lbl)
        quality_row.addWidget(self._quality_combo)
        quality_row.addStretch()
        layout.addLayout(quality_row)
        layout.addSpacing(10)

        # 기본 포맷
        format_row = QHBoxLayout()
        format_row.setContentsMargins(0, 0, 0, 0)
        format_lbl = QLabel("기본 포맷")
        format_lbl.setFixedWidth(100)
        format_lbl.setStyleSheet("font-size: 11px;")
        self._format_combo = QComboBox()
        for fmt in ("mp4", "mkv", "webm", "mp3", "m4a"):
            self._format_combo.addItem(fmt)
        fmt_idx = self._format_combo.findText(cur_format)
        self._format_combo.setCurrentIndex(fmt_idx if fmt_idx >= 0 else 0)
        self._format_combo.currentIndexChanged.connect(self._on_format_changed)
        format_row.addWidget(format_lbl)
        format_row.addWidget(self._format_combo)
        format_row.addStretch()
        layout.addLayout(format_row)
        layout.addSpacing(28)

        # ── 가사 출처 관리 섹션 (노래 탭 가사 조회 순서/사용여부) ──
        if self._song_vm is not None:
            layout.addSpacing(24)
            sep_lyr = QFrame()
            sep_lyr.setFrameShape(QFrame.Shape.HLine)
            sep_lyr.setStyleSheet(f"color: {_t().border};")
            layout.addWidget(sep_lyr)
            layout.addSpacing(24)
            lyr_label = QLabel("가사 출처 관리")
            lyr_label.setStyleSheet(
                "font-size: 9px; font-weight: 600; letter-spacing: 0.8px; "
                f"text-transform: uppercase; color: {_t().text_muted}; margin-bottom: 12px;"
            )
            layout.addWidget(lyr_label)
            layout.addSpacing(10)
            self._lyrics_sources_section = _LyricsSourcesSection(self._song_vm)
            layout.addWidget(self._lyrics_sources_section)

        # ── 클라우드 동기화 섹션 (여러 PC 간 라이브러리 동기화) ──
        if self._sync_vm is not None:
            layout.addSpacing(24)
            sep_sync = QFrame()
            sep_sync.setFrameShape(QFrame.Shape.HLine)
            sep_sync.setStyleSheet(f"color: {_t().border};")
            layout.addWidget(sep_sync)
            layout.addSpacing(24)
            sync_label = QLabel("클라우드 동기화")
            sync_label.setStyleSheet(
                "font-size: 9px; font-weight: 600; letter-spacing: 0.8px; "
                f"text-transform: uppercase; color: {_t().text_muted}; margin-bottom: 12px;"
            )
            layout.addWidget(sync_label)
            layout.addSpacing(10)
            self._cloud_sync_section = _CloudSyncSection(self._sync_vm)
            layout.addWidget(self._cloud_sync_section)

        # ── 라이브러리 가져오기/내보내기 섹션 ──
        if self._transfer_vm is not None:
            layout.addSpacing(24)
            sep_transfer = QFrame()
            sep_transfer.setFrameShape(QFrame.Shape.HLine)
            sep_transfer.setStyleSheet(f"color: {_t().border};")
            layout.addWidget(sep_transfer)
            layout.addSpacing(24)
            transfer_label = QLabel("라이브러리 가져오기/내보내기")
            transfer_label.setStyleSheet(
                "font-size: 9px; font-weight: 600; letter-spacing: 0.8px; "
                f"text-transform: uppercase; color: {_t().text_muted}; margin-bottom: 12px;"
            )
            layout.addWidget(transfer_label)
            layout.addSpacing(10)
            self._import_export_section = _ImportExportSection(
                self._transfer_vm, self._get_categories_fn
            )
            layout.addWidget(self._import_export_section)

        # ── YouTube API 연동 섹션 ──
        layout.addSpacing(20)
        yt_label = QLabel("YouTube API 연동")
        yt_label.setStyleSheet(
            "font-size: 9px; font-weight: 600; letter-spacing: 0.8px; "
            f"text-transform: uppercase; color: {_t().text_muted}; margin-bottom: 12px;"
        )
        layout.addWidget(yt_label)
        layout.addSpacing(10)

        yt_desc = QLabel(
            "Google 계정을 연결하면 YouTube 재생목록 동기화(읽기·쓰기)와\n"
            "구독 채널 가져오기를 사용할 수 있습니다.\n"
            "로그인은 기본 브라우저의 Google 페이지에서 안전하게 진행됩니다."
        )
        yt_desc.setStyleSheet(f"font-size: 9pt; color: {_t().text_secondary};")
        yt_desc.setWordWrap(True)
        layout.addWidget(yt_desc)
        layout.addSpacing(8)

        yt_btn_row = QHBoxLayout()
        self._yt_auth_btn = QPushButton("Google 계정으로 연결")
        self._yt_auth_btn.setFixedWidth(160)
        self._yt_auth_btn.clicked.connect(self._on_yt_auth)
        yt_btn_row.addWidget(self._yt_auth_btn)

        self._yt_disconnect_btn = QPushButton("연결 해제")
        self._yt_disconnect_btn.setFixedWidth(80)
        self._yt_disconnect_btn.clicked.connect(self._on_yt_disconnect)
        yt_btn_row.addWidget(self._yt_disconnect_btn)
        yt_btn_row.addStretch()
        layout.addLayout(yt_btn_row)
        layout.addSpacing(6)

        self._yt_status_lbl = QLabel()
        self._yt_status_lbl.setWordWrap(True)
        layout.addWidget(self._yt_status_lbl)
        self._refresh_yt_status()

        # ── 구독 피드 브라우저 쿠키 (YouTube API에는 피드 엔드포인트 없음) ──
        layout.addSpacing(16)
        feed_label = QLabel("구독 피드 — 브라우저 쿠키 (선택)")
        feed_label.setStyleSheet(
            f"font-size: 9px; font-weight: 600; letter-spacing: 0.5px; color: {_t().text_secondary};"
        )
        layout.addWidget(feed_label)
        feed_hint = QLabel(
            "YouTube API는 구독 피드(최신 영상 목록) 엔드포인트를 제공하지 않아\n"
            "브라우저 쿠키가 필요합니다. Firefox 권장 (Chrome 실행 중 오류 발생).\n"
            "쿠키 파일을 등록하면 가장 안정적입니다 — 다운로드·데스크톱 폴더를 "
            "자동으로 검색해 아래에서 바로 선택할 수 있습니다."
        )
        feed_hint.setWordWrap(True)
        feed_hint.setStyleSheet(f"font-size: 8pt; color: {_t().text_secondary};")
        layout.addWidget(feed_hint)
        layout.addSpacing(6)

        browser_row = QHBoxLayout()
        b_lbl = QLabel("브라우저")
        b_lbl.setFixedWidth(100)
        self._feed_browser_combo = QComboBox()
        self._feed_browser_combo.addItems(["firefox", "chrome", "edge", "chromium"])
        self._feed_browser_combo.setFixedWidth(120)
        self._feed_browser_combo.currentTextChanged.connect(self._on_feed_browser_changed)
        browser_row.addWidget(b_lbl)
        browser_row.addWidget(self._feed_browser_combo)
        browser_row.addStretch()
        layout.addLayout(browser_row)

        profile_row = QHBoxLayout()
        p_lbl = QLabel("프로필")
        p_lbl.setFixedWidth(100)
        self._feed_profile_combo = QComboBox()
        self._feed_profile_combo.setFixedWidth(220)
        self._feed_profile_combo.setToolTip("브라우저 프로필을 선택하세요")
        self._feed_profile_combo.currentIndexChanged.connect(self._on_feed_profile_changed)
        profile_row.addWidget(p_lbl)
        profile_row.addWidget(self._feed_profile_combo, 1)
        layout.addLayout(profile_row)

        cand_row = QHBoxLayout()
        cand_lbl = QLabel("감지된 쿠키 파일")
        cand_lbl.setFixedWidth(100)
        self._feed_cookie_candidates_combo = QComboBox()
        self._feed_cookie_candidates_combo.setToolTip(
            "다운로드·데스크톱 폴더에서 자동으로 찾은 쿠키 파일입니다. 선택하면 "
            "아래 경로란에 채워집니다."
        )
        self._feed_cookie_candidates_combo.currentIndexChanged.connect(
            self._on_cookie_candidate_selected
        )
        cand_refresh = QPushButton("다시 검색")
        cand_refresh.setFixedWidth(70)
        cand_refresh.clicked.connect(self._reload_cookie_candidates)
        cand_row.addWidget(cand_lbl)
        cand_row.addWidget(self._feed_cookie_candidates_combo, 1)
        cand_row.addWidget(cand_refresh)
        layout.addLayout(cand_row)

        cookie_row = QHBoxLayout()
        ck_lbl = QLabel("또는 쿠키 파일")
        ck_lbl.setFixedWidth(100)
        self._feed_cookie_edit = QLineEdit()
        self._feed_cookie_edit.setPlaceholderText("Netscape 포맷 쿠키 파일 경로 (선택)")
        ck_browse = QPushButton("찾기…")
        ck_browse.setFixedWidth(48)
        ck_browse.clicked.connect(self._on_browse_cookie_file)
        cookie_row.addWidget(ck_lbl)
        cookie_row.addWidget(self._feed_cookie_edit, 1)
        cookie_row.addWidget(ck_browse)
        layout.addLayout(cookie_row)

        ck_apply = QPushButton("쿠키 파일 적용")
        ck_apply.setFixedWidth(110)
        ck_apply.clicked.connect(self._on_apply_cookie_file)
        layout.addWidget(ck_apply)

        help_row = QHBoxLayout()
        self._cookie_help_btn = QPushButton("쿠키 파일 등록 방법 보기")
        self._cookie_help_btn.setFixedWidth(160)
        self._cookie_help_btn.clicked.connect(self._on_show_cookie_help)
        self._open_log_dir_btn = QPushButton("로그 폴더 열기")
        self._open_log_dir_btn.setFixedWidth(100)
        self._open_log_dir_btn.clicked.connect(self._on_open_log_dir)
        help_row.addWidget(self._cookie_help_btn)
        help_row.addWidget(self._open_log_dir_btn)
        help_row.addStretch()
        layout.addLayout(help_row)

        self._feed_status_lbl = QLabel()
        self._feed_status_lbl.setWordWrap(True)
        self._feed_status_lbl.setStyleSheet(f"font-size: 8pt; color: {_t().text_secondary};")
        layout.addWidget(self._feed_status_lbl)
        self._refresh_feed_auth_ui()

        # ── 숨김 태그 관리 섹션 (맨 아래 — 긴 목록이 다른 설정 접근을 방해하지 않도록) ──
        layout.addSpacing(28)
        sep_hidden = QFrame()
        sep_hidden.setFrameShape(QFrame.Shape.HLine)
        sep_hidden.setStyleSheet(f"color: {_t().border};")
        layout.addWidget(sep_hidden)
        layout.addSpacing(24)

        hidden_label = QLabel("숨김 태그 관리")
        hidden_label.setStyleSheet(
            "font-size: 9px; font-weight: 600; letter-spacing: 0.8px; "
            f"text-transform: uppercase; color: {_t().text_muted}; margin-bottom: 12px;"
        )
        layout.addWidget(hidden_label)
        layout.addSpacing(10)

        if self._get_tags_fn is not None:
            self._hidden_tags_section = _HiddenTagsSection(self._get_tags_fn)
            self._hidden_tags_section.changed.connect(self.hidden_tags_changed.emit)
            layout.addWidget(self._hidden_tags_section)
        else:
            no_tags_lbl = QLabel("태그 목록을 불러올 수 없습니다.")
            no_tags_lbl.setStyleSheet(f"font-size: 10px; color: {_t().text_muted};")
            layout.addWidget(no_tags_lbl)
            self._hidden_tags_section = None

        layout.addStretch()

    def _build_update_header(self) -> QWidget:
        """헤더 우측 컴팩트 업데이트 위젯 — 자동확인 토글 + 상태 + (준비 시)설치 버튼."""
        try:
            from config import settings as s  # noqa: PLC0415
            cur_auto = s.AUTO_UPDATE_CHECK
        except Exception:
            logger.exception("업데이트 설정 로드 실패")
            cur_auto = True
        w = QWidget()
        row = QHBoxLayout(w)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        self._auto_update_check = QCheckBox("자동 업데이트")
        self._auto_update_check.setToolTip("시작 시 자동으로 업데이트를 확인·다운로드합니다")
        self._auto_update_check.setChecked(cur_auto)
        self._auto_update_check.checkStateChanged.connect(self._on_auto_update_changed)
        row.addWidget(self._auto_update_check)
        self._upd_status_lbl = QLabel(f"v{__version__}")
        self._upd_status_lbl.setStyleSheet(f"font-size: 11px; color: {_t().text_secondary};")
        row.addWidget(self._upd_status_lbl)
        # 수동 확인 — 자동 확인은 1시간 간격이라, 실패한 뒤 바로 다시 시도할 길이 필요하다.
        self._upd_check_btn = QPushButton("확인")
        self._upd_check_btn.setToolTip("지금 업데이트를 확인합니다")
        self._upd_check_btn.clicked.connect(self.check_update_requested.emit)
        row.addWidget(self._upd_check_btn)
        self._upd_install_btn = QPushButton("지금 설치")
        self._upd_install_btn.setToolTip("앱을 재시작하여 업데이트를 설치합니다")
        self._upd_install_btn.clicked.connect(self._on_install_update)
        self._upd_install_btn.hide()
        row.addWidget(self._upd_install_btn)
        return w

    # ------------------------------------------------------------------
    def set_update_ready(self, dto) -> None:
        """자동 다운로드 완료 — 헤더 상태를 '준비됨'으로 바꾸고 설치 버튼을 노출한다."""
        self._pending_dto = dto
        self._upd_status_lbl.setText(f"업데이트 준비됨 · v{dto.version}")
        self._upd_status_lbl.setStyleSheet(
            f"font-size: 11px; color: {sem('danger')}; font-weight: 600;"
        )
        self._upd_install_btn.setText("지금 설치")
        self._upd_install_btn.setToolTip("앱을 재시작하여 업데이트를 설치합니다")
        self._upd_install_btn.show()

    def set_update_available(self, dto) -> None:
        """새 버전을 찾았지만 자동 설치 준비에 실패한 상태.

        예전에는 이때 기어의 빨간 점만 켜지고 설정 화면은 그대로여서, 사용자가
        업데이트를 진행할 방법이 화면에 없었다. 여기서 직접 내려받을 버튼을 준다.
        """
        self._pending_dto = dto
        self._upd_status_lbl.setText(f"업데이트 있음 · v{dto.version}")
        self._upd_status_lbl.setStyleSheet(
            f"font-size: 11px; color: {sem('warning')}; font-weight: 600;"
        )
        self._upd_install_btn.setText("설치하기")
        self._upd_install_btn.setToolTip("업데이트를 내려받아 설치합니다")
        self._upd_install_btn.show()

    def set_update_busy(self, busy: bool) -> None:
        """확인·다운로드 진행 중 표시(중복 요청 방지)."""
        self._upd_check_btn.setEnabled(not busy)
        if busy:
            self._upd_status_lbl.setText("확인 중…")
            self._upd_status_lbl.setStyleSheet(
                f"font-size: 11px; color: {_t().text_secondary};"
            )
        elif self._pending_dto is None:
            self._upd_status_lbl.setText(f"v{__version__}")
            self._upd_status_lbl.setStyleSheet(
                f"font-size: 11px; color: {_t().text_secondary};"
            )

    def scroll_and_flash_update_section(self) -> None:
        # 업데이트 상태가 헤더에 상시 노출되므로 스크롤/플래시는 불필요(no-op).
        pass

    def _on_install_update(self) -> None:
        """'지금 설치' — 저장된 DTO로 설치를 요청한다(앱 재시작 후 pending 설치)."""
        if self._pending_dto is not None:
            self.install_update_requested.emit(self._pending_dto)

    # ------------------------------------------------------------------
    def showEvent(self, event) -> None:  # type: ignore[override]
        """설정 패널이 표시될 때 숨김 태그 목록을 최신 상태로 갱신한다."""
        super().showEvent(event)
        if self._hidden_tags_section is not None:
            self._hidden_tags_section.refresh()
        self._refresh_yt_status()
        self._refresh_feed_auth_ui()

    # ------------------------------------------------------------------
    def _on_concurrent_changed(self, value: int) -> None:
        from config import settings as s
        s.save_setting("max_concurrent_downloads", value)

    def _on_feed_workers_changed(self, value: int) -> None:
        from config import settings as s
        s.save_setting("max_concurrent_feed_workers", value)
        self.feed_workers_changed.emit(value)

    def _on_clipboard_changed(self, state) -> None:
        from config import settings as s
        checked = (state == Qt.CheckState.Checked)
        s.save_setting("clipboard_monitoring", checked)

    def _on_auto_enrich_changed(self, state) -> None:
        from config import settings as s
        checked = (state == Qt.CheckState.Checked)
        s.save_setting("auto_enrich_on_add", checked)

    def _on_browse_folder(self) -> None:
        from config import settings as s
        folder = QFileDialog.getExistingDirectory(
            self, "다운로드 폴더 선택", self._folder_edit.text()
        )
        if folder:
            self._folder_edit.setText(folder)
            s.save_path_setting("downloads", folder)

    def _on_quality_changed(self, index: int) -> None:
        from config import settings as s
        fmt = self._quality_combo.itemData(index)
        if fmt:
            s.save_setting("default_quality", fmt)

    def _on_format_changed(self, index: int) -> None:
        from config import settings as s
        fmt = self._format_combo.currentText()
        s.save_setting("default_format", fmt)

    def _on_auto_update_changed(self, state) -> None:
        from config import settings as s
        s.save_setting("auto_update_check", state == Qt.CheckState.Checked)

    # ------------------------------------------------------------------
    def _on_theme_changed(self, tokens: ThemeTokens) -> None:
        """테마 변경 시 선택 상태를 업데이트한다."""
        for name, card in self._theme_cards.items():
            card.set_selected(name == tokens.name)

    # ── YouTube API OAuth ──────────────────────────────────────────────────

    _YT_BTN_DISCONNECTED = "Google 계정으로 연결"
    _YT_BTN_WORKING = "연결 중…"
    _YT_BTN_CONNECTED = "Google 계정 다시 연결"

    def _refresh_yt_status(self) -> None:
        if self._yt_oauth is None:
            self._yt_status_lbl.setText("○ YouTube API 미초기화")
            self._yt_status_lbl.setStyleSheet(f"font-size: 9pt; color: {_t().text_secondary};")
            self._yt_auth_btn.setEnabled(False)
            return
        if not self._yt_oauth.has_client_config():
            self._yt_status_lbl.setText(
                "YouTube OAuth 설정이 앱에 포함되지 않았습니다. 배포자에게 문의하세요."
            )
            self._yt_status_lbl.setStyleSheet(f"font-size: 9pt; color: {sem('warning')};")
            self._yt_auth_btn.setEnabled(False)
            self._yt_auth_btn.setText(self._YT_BTN_DISCONNECTED)
            return
        self._yt_auth_btn.setEnabled(True)
        if self._yt_oauth.is_authenticated():
            name = self._yt_oauth.get_channel_name() or "인증됨"
            self._yt_status_lbl.setText(
                f"● 연결됨: {name}\n앱을 다시 시작하면 모든 YouTube 연동 기능이 활성화됩니다."
            )
            self._yt_status_lbl.setStyleSheet(f"font-size: 9pt; color: {sem('success')};")
            self._yt_auth_btn.setText(self._YT_BTN_CONNECTED)
        else:
            self._yt_status_lbl.setText("○ 미연결 — Google 계정으로 연결하세요")
            self._yt_status_lbl.setStyleSheet(f"font-size: 9pt; color: {sem('danger')};")
            self._yt_auth_btn.setText(self._YT_BTN_DISCONNECTED)

    def _on_yt_auth(self) -> None:
        if self._yt_oauth is None or not self._yt_oauth.has_client_config():
            return

        from PyQt6.QtCore import QThread, pyqtSignal as _sig  # noqa: PLC0415

        class _AuthWorker(QThread):
            done = _sig(str)   # channel_name or ""
            err  = _sig(str)

            def __init__(self, oauth, parent=None):
                super().__init__(parent)
                self._oauth = oauth

            def run(self):
                try:
                    self._oauth.run_auth_flow()
                    name = self._oauth.get_channel_name() or "인증됨"
                    self.done.emit(name)
                except Exception as exc:
                    logger.exception("YouTube OAuth 인증 실패")
                    self.err.emit(str(exc))

        self._yt_auth_btn.setEnabled(False)
        self._yt_auth_btn.setText(self._YT_BTN_WORKING)
        self._yt_status_lbl.setText("브라우저에서 Google 계정으로 승인하세요…")
        self._yt_status_lbl.setStyleSheet(f"font-size: 9pt; color: {_t().text_secondary};")

        worker = _AuthWorker(self._yt_oauth, self)

        def _on_done(name: str) -> None:
            self._yt_auth_btn.setEnabled(True)
            self._yt_auth_btn.setText(self._YT_BTN_CONNECTED)
            self._yt_status_lbl.setText(
                f"● 연결됨: {name}\n앱을 다시 시작하면 모든 YouTube 연동 기능이 활성화됩니다."
            )
            self._yt_status_lbl.setStyleSheet(f"font-size: 9pt; color: {sem('success')};")
            self._yt_auth_worker = None

        def _on_err(msg: str) -> None:
            self._yt_auth_btn.setEnabled(True)
            self._yt_auth_btn.setText(self._YT_BTN_DISCONNECTED)
            self._yt_status_lbl.setText(f"연결 실패: {msg[:120]}")
            self._yt_status_lbl.setStyleSheet(f"font-size: 9pt; color: {sem('danger')};")
            self._yt_auth_worker = None

        worker.done.connect(_on_done)
        worker.err.connect(_on_err)
        self._yt_auth_worker = worker
        worker.start()

    def _on_yt_disconnect(self) -> None:
        if self._yt_oauth is None:
            return
        self._yt_oauth.clear()
        self._refresh_yt_status()

    # ── 브라우저 쿠키 (구독 피드) ──────────────────────────────────────────────

    def _refresh_feed_auth_ui(self) -> None:
        """현재 저장된 브라우저 쿠키 설정을 UI에 반영한다."""
        try:
            import config.settings as s  # noqa: PLC0415
            browser = getattr(s, "YT_AUTH_BROWSER", "firefox") or "firefox"
            idx = self._feed_browser_combo.findText(browser)
            if idx >= 0:
                self._feed_browser_combo.setCurrentIndex(idx)
            self._reload_profiles(browser)
            cookiefile = getattr(s, "YT_AUTH_COOKIEFILE", None)
            if cookiefile:
                self._feed_cookie_edit.setText(cookiefile)
            profile = getattr(s, "YT_AUTH_PROFILE", None)
            self._feed_status_lbl.setText(
                f"프로필: {profile}" if profile else
                (f"쿠키 파일: {cookiefile}" if cookiefile else "미설정")
            )
            self._reload_cookie_candidates()
        except Exception:
            logger.exception("브라우저 쿠키 설정 UI 반영 실패")

    def _reload_cookie_candidates(self) -> None:
        """다운로드·데스크톱 폴더에서 쿠키 파일 후보를 다시 스캔해 목록에 채운다."""
        from infrastructure.auth.youtube_auth import (  # noqa: PLC0415
            find_cookie_file_candidates,
        )

        self._feed_cookie_candidates_combo.blockSignals(True)
        self._feed_cookie_candidates_combo.clear()
        try:
            candidates = find_cookie_file_candidates()
        except Exception:
            logger.exception("쿠키 파일 후보 탐색 실패")
            candidates = []
        if candidates:
            self._feed_cookie_candidates_combo.addItem("아래에서 선택하세요", None)
            for path in candidates:
                self._feed_cookie_candidates_combo.addItem(
                    f"{path.name}  ({path.parent.name})", str(path)
                )
        else:
            self._feed_cookie_candidates_combo.addItem(
                "다운로드·데스크톱에서 찾지 못함 — 아래 '찾기…'로 직접 선택", None
            )
        self._feed_cookie_candidates_combo.blockSignals(False)

    def _on_cookie_candidate_selected(self, _index: int) -> None:
        path = self._feed_cookie_candidates_combo.currentData()
        if not path:
            return
        self._feed_cookie_edit.setText(path)

    def _reload_profiles(self, browser: str) -> None:
        from infrastructure.auth.youtube_auth import YouTubeAuthService  # noqa: PLC0415
        import config.settings as s  # noqa: PLC0415
        self._feed_profile_combo.blockSignals(True)
        self._feed_profile_combo.clear()
        self._feed_profile_combo.addItem("(선택 안 함)", None)
        try:
            profiles = YouTubeAuthService().detect_profiles(browser)
            for p in profiles:
                self._feed_profile_combo.addItem(p.display_name, p.profile_key)
            # 현재 저장된 프로필 선택
            saved = getattr(s, "YT_AUTH_PROFILE", None)
            if saved:
                for i in range(self._feed_profile_combo.count()):
                    if self._feed_profile_combo.itemData(i) == saved:
                        self._feed_profile_combo.setCurrentIndex(i)
                        break
        except Exception:
            logger.exception("브라우저 프로필 목록 로드 실패")
        finally:
            self._feed_profile_combo.blockSignals(False)

    def _on_feed_browser_changed(self, browser: str) -> None:
        self._reload_profiles(browser)

    def _on_feed_profile_changed(self, _index: int) -> None:
        profile_key = self._feed_profile_combo.currentData()
        if profile_key is None:
            return
        from infrastructure.auth.youtube_auth import YouTubeAuthService  # noqa: PLC0415
        browser = self._feed_browser_combo.currentText()
        YouTubeAuthService().save_auth(browser=browser, profile_key=profile_key, cookiefile=None)
        self._feed_status_lbl.setText(
            f"저장됨: {self._feed_profile_combo.currentText()}"
        )
        self._feed_status_lbl.setStyleSheet(f"font-size: 8pt; color: {sem('success')};")

    def _on_browse_cookie_file(self) -> None:
        from PyQt6.QtWidgets import QFileDialog  # noqa: PLC0415
        path, _ = QFileDialog.getOpenFileName(
            self, "쿠키 파일 선택", "", "텍스트 파일 (*.txt);;모든 파일 (*)"
        )
        if path:
            self._feed_cookie_edit.setText(path)

    def _on_apply_cookie_file(self) -> None:
        cookiefile = self._feed_cookie_edit.text().strip()
        if not cookiefile:
            return
        from infrastructure.auth.youtube_auth import YouTubeAuthService  # noqa: PLC0415
        browser = self._feed_browser_combo.currentText()
        YouTubeAuthService().save_auth(browser=browser, profile_key=None, cookiefile=cookiefile)
        self._feed_status_lbl.setText("쿠키 파일이 설정되었습니다.")
        self._feed_status_lbl.setStyleSheet(f"font-size: 8pt; color: {sem('success')};")

    def _on_show_cookie_help(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("쿠키 파일 등록 방법")
        v = QVBoxLayout(dialog)
        text_lbl = QLabel(COOKIE_HELP_TEXT)
        text_lbl.setWordWrap(True)
        v.addWidget(text_lbl)
        btn_row = QHBoxLayout()
        dl_btn = QPushButton("다운로드 폴더 열기")
        dl_btn.clicked.connect(lambda: open_folder(Path.home() / "Downloads"))
        close_btn = QPushButton("닫기")
        close_btn.clicked.connect(dialog.accept)
        btn_row.addWidget(dl_btn)
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        v.addLayout(btn_row)
        dialog.exec()

    def _on_open_log_dir(self) -> None:
        from config import settings as s  # noqa: PLC0415
        open_folder(s.LOG_DIR)
