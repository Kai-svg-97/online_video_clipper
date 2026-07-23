"""설정 패널 — 인라인 QWidget (다이얼로그 아님).

사이드바 ⚙ 아이콘 클릭 시 메인 콘텐츠 스택에 표시된다.
테마 프리셋 선택 + 일반/다운로드 설정 + 저장 경로 표시 + 숨김 태그 관리.
"""
from __future__ import annotations

import logging
from typing import Callable

from PyQt6.QtCore import QByteArray, QMimeData, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPainterPath
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
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

logger = logging.getLogger(__name__)


def _t():
    return ThemeManager.instance().current()


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

        # 이름 레이블
        self._name_lbl = QLabel(tokens.display_name)
        self._name_lbl.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self._name_lbl.setStyleSheet(
            f"font-size: 11px; font-weight: 500; color: {tokens.text_secondary};"
        )
        layout.addWidget(self._name_lbl)

    # ------------------------------------------------------------------
    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        self._preview.set_selected(selected)
        tok = self._tokens
        color = tok.text_primary if selected else tok.text_secondary
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
        hint.setStyleSheet("font-size: 10px; color: #666; margin-bottom: 4px;")
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
            lbl.setStyleSheet("font-size: 14px; color: #666;")
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
        hint.setStyleSheet("font-size: 10px; color: #555;")
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

        # provider + 자격증명 입력 행
        prov_row = QHBoxLayout()
        prov_row.addWidget(QLabel("제공자"))
        self._provider_combo = QComboBox()
        self._provider_combo.addItem("로컬 폴더 (OneDrive/Drive 동기화 폴더)", "folder")
        self._provider_combo.addItem("Google Drive (API)", "gdrive")
        self._provider_combo.addItem("OneDrive (API)", "onedrive")
        self._provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        prov_row.addWidget(self._provider_combo)
        prov_row.addStretch()
        root.addLayout(prov_row)

        # 로컬 폴더 경로 행(폴더 provider 전용)
        folder_row = QHBoxLayout()
        self._folder_path = QLineEdit()
        self._folder_path.setPlaceholderText(
            "예: C:/Users/나/OneDrive/ovc-sync — 여러 PC가 같은 폴더를 가리키게 한다"
        )
        self._browse_btn = QPushButton("찾아보기…")
        self._browse_btn.clicked.connect(self._on_browse)
        folder_row.addWidget(self._folder_path, 1)
        folder_row.addWidget(self._browse_btn)
        self._folder_row_widget = QWidget()
        self._folder_row_widget.setLayout(folder_row)
        root.addWidget(self._folder_row_widget)

        # OAuth 자격증명 행(gdrive/onedrive 전용)
        self._client_id = QLineEdit()
        self._client_id.setPlaceholderText("OAuth Client ID")
        root.addWidget(self._client_id)
        self._client_secret = QLineEdit()
        self._client_secret.setPlaceholderText("OAuth Client Secret (Google Drive)")
        self._client_secret.setEchoMode(QLineEdit.EchoMode.Password)
        root.addWidget(self._client_secret)
        self._on_provider_changed()  # 초기 표시 상태 반영(기본=폴더)

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
        self._status_lbl.setStyleSheet("color: #888; font-size: 11px;")
        self._status_lbl.setWordWrap(True)
        root.addWidget(self._status_lbl)

    def _on_provider_changed(self) -> None:
        key = self._provider_combo.currentData()
        is_folder = key == "folder"
        # 폴더 provider는 경로만, API provider는 client id/secret만 노출.
        self._folder_row_widget.setVisible(is_folder)
        self._client_id.setVisible(not is_folder)
        self._client_secret.setVisible(key == "gdrive")

    def _on_browse(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "동기화 폴더 선택")
        if path:
            self._folder_path.setText(path)

    def _on_connect(self) -> None:
        key = self._provider_combo.currentData()
        if key == "folder":
            path = self._folder_path.text().strip()
            if not path:
                self._status_lbl.setText("동기화 폴더를 선택하세요.")
                return
            self._vm.connect(key, folder_path=path)
            self._status_lbl.setText("폴더 연결 중…")
            return
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
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._get_tags_fn = get_tags_fn
        self._yt_oauth = yt_oauth
        self._song_vm = song_vm
        self._sync_vm = sync_vm
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

        # 헤더
        header = QLabel("설정")
        header.setStyleSheet("font-size: 16px; font-weight: 600; margin-bottom: 24px;")
        layout.addWidget(header)
        layout.addSpacing(20)

        # ── 테마 섹션 ──
        theme_label = QLabel("테마")
        theme_label.setStyleSheet(
            "font-size: 9px; font-weight: 600; letter-spacing: 0.8px; "
            "text-transform: uppercase; color: #555; margin-bottom: 12px;"
        )
        layout.addWidget(theme_label)
        layout.addSpacing(10)

        cards_row = QHBoxLayout()
        cards_row.setContentsMargins(0, 0, 0, 0)
        cards_row.setSpacing(16)

        for name, tokens in PRESETS.items():
            card = _ThemeCard(tokens)
            self._theme_cards[name] = card
            cards_row.addWidget(card)
        cards_row.addStretch()

        layout.addLayout(cards_row)
        layout.addSpacing(8)

        hint = QLabel("클릭하면 즉시 적용됩니다. 재시작 후에도 유지됩니다.")
        hint.setStyleSheet("font-size: 10px; color: #555; margin-top: 4px;")
        layout.addWidget(hint)
        layout.addSpacing(28)

        # ── 구분선 ──
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #1a1a1a;")
        layout.addWidget(sep)
        layout.addSpacing(24)

        # ── 저장 경로 섹션 ──
        path_label = QLabel("저장 경로")
        path_label.setStyleSheet(
            "font-size: 9px; font-weight: 600; letter-spacing: 0.8px; "
            "text-transform: uppercase; color: #555; margin-bottom: 12px;"
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
            lbl.setStyleSheet("font-size: 11px; color: #555;")
            val = QLabel(path_text)
            val.setStyleSheet(
                "font-size: 10px; color: #444; font-family: monospace;"
            )
            val.setWordWrap(False)
            val.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
            )
            row.addWidget(lbl)
            row.addWidget(val, 1)
            layout.addLayout(row)
            layout.addSpacing(6)

        note = QLabel("경로를 변경하려면 data/config.yaml 을 편집하세요.")
        note.setStyleSheet("font-size: 10px; color: #444; margin-top: 8px;")
        layout.addWidget(note)
        layout.addSpacing(28)

        # ── 구분선 ──
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet("color: #1a1a1a;")
        layout.addWidget(sep2)
        layout.addSpacing(24)

        # ── 일반 섹션 ──
        gen_label = QLabel("일반")
        gen_label.setStyleSheet(
            "font-size: 9px; font-weight: 600; letter-spacing: 0.8px; "
            "text-transform: uppercase; color: #555; margin-bottom: 12px;"
        )
        layout.addWidget(gen_label)
        layout.addSpacing(10)

        try:
            from config import settings as s
            cur_concurrent = s.MAX_CONCURRENT_DOWNLOADS
            cur_feed_workers = s.MAX_CONCURRENT_FEED_WORKERS
            cur_clipboard = s.CLIPBOARD_MONITORING
        except Exception:
            logger.exception("일반 설정 로드 실패")
            cur_concurrent = 3
            cur_feed_workers = 4
            cur_clipboard = True

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
        layout.addSpacing(28)

        # ── 구분선 ──
        sep3 = QFrame()
        sep3.setFrameShape(QFrame.Shape.HLine)
        sep3.setStyleSheet("color: #1a1a1a;")
        layout.addWidget(sep3)
        layout.addSpacing(24)

        # ── 다운로드 섹션 ──
        dl_label = QLabel("다운로드")
        dl_label.setStyleSheet(
            "font-size: 9px; font-weight: 600; letter-spacing: 0.8px; "
            "text-transform: uppercase; color: #555; margin-bottom: 12px;"
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

        # ── 구분선 ──
        sep4 = QFrame()
        sep4.setFrameShape(QFrame.Shape.HLine)
        sep4.setStyleSheet("color: #1a1a1a;")
        layout.addWidget(sep4)
        layout.addSpacing(24)

        # ── 숨김 태그 관리 섹션 ──
        hidden_label = QLabel("숨김 태그 관리")
        hidden_label.setStyleSheet(
            "font-size: 9px; font-weight: 600; letter-spacing: 0.8px; "
            "text-transform: uppercase; color: #555; margin-bottom: 12px;"
        )
        layout.addWidget(hidden_label)
        layout.addSpacing(10)

        if self._get_tags_fn is not None:
            self._hidden_tags_section = _HiddenTagsSection(self._get_tags_fn)
            self._hidden_tags_section.changed.connect(self.hidden_tags_changed.emit)
            layout.addWidget(self._hidden_tags_section)
        else:
            no_tags_lbl = QLabel("태그 목록을 불러올 수 없습니다.")
            no_tags_lbl.setStyleSheet("font-size: 10px; color: #555;")
            layout.addWidget(no_tags_lbl)
            self._hidden_tags_section = None

        # ── 가사 출처 관리 섹션 (노래 탭 가사 조회 순서/사용여부) ──
        if self._song_vm is not None:
            layout.addSpacing(24)
            sep_lyr = QFrame()
            sep_lyr.setFrameShape(QFrame.Shape.HLine)
            sep_lyr.setStyleSheet("color: #1a1a1a;")
            layout.addWidget(sep_lyr)
            layout.addSpacing(24)
            lyr_label = QLabel("가사 출처 관리")
            lyr_label.setStyleSheet(
                "font-size: 9px; font-weight: 600; letter-spacing: 0.8px; "
                "text-transform: uppercase; color: #555; margin-bottom: 12px;"
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
            sep_sync.setStyleSheet("color: #1a1a1a;")
            layout.addWidget(sep_sync)
            layout.addSpacing(24)
            sync_label = QLabel("클라우드 동기화")
            sync_label.setStyleSheet(
                "font-size: 9px; font-weight: 600; letter-spacing: 0.8px; "
                "text-transform: uppercase; color: #555; margin-bottom: 12px;"
            )
            layout.addWidget(sync_label)
            layout.addSpacing(10)
            self._cloud_sync_section = _CloudSyncSection(self._sync_vm)
            layout.addWidget(self._cloud_sync_section)

        # ── YouTube API 연동 섹션 ──
        layout.addSpacing(20)
        yt_label = QLabel("YouTube API 연동")
        yt_label.setStyleSheet(
            "font-size: 9px; font-weight: 600; letter-spacing: 0.8px; "
            "text-transform: uppercase; color: #555; margin-bottom: 12px;"
        )
        layout.addWidget(yt_label)
        layout.addSpacing(10)

        yt_desc = QLabel(
            "Google Cloud Console에서 YouTube Data API v3 OAuth2 자격증명을 발급 후\n"
            "아래에 입력하고 인증하세요. 무료 — 일 10,000 유닛 할당.\n"
            "인증 완료 시 재생목록 동기화(읽기+쓰기) + 구독 채널 가져오기가 활성화됩니다."
        )
        yt_desc.setStyleSheet("font-size: 9pt; color: #888;")
        yt_desc.setWordWrap(True)
        layout.addWidget(yt_desc)
        layout.addSpacing(8)

        cid_row = QHBoxLayout()
        cid_lbl = QLabel("Client ID")
        cid_lbl.setFixedWidth(100)
        self._yt_client_id_edit = QLineEdit()
        self._yt_client_id_edit.setPlaceholderText("xxxx.apps.googleusercontent.com")
        cid_row.addWidget(cid_lbl)
        cid_row.addWidget(self._yt_client_id_edit, 1)
        layout.addLayout(cid_row)

        csec_row = QHBoxLayout()
        csec_lbl = QLabel("Client Secret")
        csec_lbl.setFixedWidth(100)
        self._yt_client_secret_edit = QLineEdit()
        self._yt_client_secret_edit.setPlaceholderText("GOCSPX-…")
        self._yt_client_secret_edit.setEchoMode(QLineEdit.EchoMode.Password)
        csec_row.addWidget(csec_lbl)
        csec_row.addWidget(self._yt_client_secret_edit, 1)
        layout.addLayout(csec_row)
        layout.addSpacing(8)

        yt_btn_row = QHBoxLayout()
        self._yt_auth_btn = QPushButton("OAuth 인증하기")
        self._yt_auth_btn.setFixedWidth(130)
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
            "font-size: 9px; font-weight: 600; letter-spacing: 0.5px; color: #666;"
        )
        layout.addWidget(feed_label)
        feed_hint = QLabel(
            "YouTube API는 구독 피드(최신 영상 목록) 엔드포인트를 제공하지 않아\n"
            "브라우저 쿠키가 필요합니다. Firefox 권장 (Chrome 실행 중 오류 발생)."
        )
        feed_hint.setWordWrap(True)
        feed_hint.setStyleSheet("font-size: 8pt; color: #888;")
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

        self._feed_status_lbl = QLabel()
        self._feed_status_lbl.setWordWrap(True)
        self._feed_status_lbl.setStyleSheet("font-size: 8pt; color: #888;")
        layout.addWidget(self._feed_status_lbl)
        self._refresh_feed_auth_ui()

        # ── 업데이트 섹션 ──
        layout.addSpacing(28)
        sep_upd = QFrame()
        sep_upd.setFrameShape(QFrame.Shape.HLine)
        sep_upd.setStyleSheet("color: #1a1a1a;")
        layout.addWidget(sep_upd)
        layout.addSpacing(24)

        upd_label = QLabel("업데이트")
        upd_label.setStyleSheet(
            "font-size: 9px; font-weight: 600; letter-spacing: 0.8px; "
            "text-transform: uppercase; color: #555; margin-bottom: 12px;"
        )
        layout.addWidget(upd_label)
        layout.addSpacing(10)

        # 업데이트 컨테이너 (깜빡임 효과 대상)
        self._update_section_frame = QFrame()
        self._update_section_frame.setObjectName("updateSectionFrame")
        upd_inner = QVBoxLayout(self._update_section_frame)
        upd_inner.setContentsMargins(8, 8, 8, 8)
        upd_inner.setSpacing(8)

        # 새 버전 알림 행 (평소엔 숨김 — set_pending_update 시 표시)
        self._upd_avail_row = QFrame()
        self._upd_avail_row.setObjectName("updAvailRow")
        self._upd_avail_row.setStyleSheet(
            "#updAvailRow { background: rgba(91,155,213,18); border-radius: 6px; }"
        )
        avail_layout = QHBoxLayout(self._upd_avail_row)
        avail_layout.setContentsMargins(10, 8, 10, 8)
        avail_layout.setSpacing(8)
        self._upd_avail_lbl = QLabel()
        self._upd_avail_lbl.setStyleSheet("font-size: 11px; font-weight: 600;")
        avail_layout.addWidget(self._upd_avail_lbl)
        avail_layout.addStretch()
        self._upd_install_btn = QPushButton("지금 설치")
        self._upd_install_btn.setFixedWidth(80)
        self._upd_install_btn.clicked.connect(self._on_install_update)
        avail_layout.addWidget(self._upd_install_btn)
        self._upd_avail_row.hide()
        upd_inner.addWidget(self._upd_avail_row)

        try:
            from config import settings as s  # noqa: PLC0415
            cur_auto_update = s.AUTO_UPDATE_CHECK
        except Exception:
            logger.exception("업데이트 설정 로드 실패")
            cur_auto_update = True

        self._auto_update_check = QCheckBox("시작 시 자동 업데이트 확인")
        self._auto_update_check.setChecked(cur_auto_update)
        self._auto_update_check.checkStateChanged.connect(self._on_auto_update_changed)
        upd_inner.addWidget(self._auto_update_check)

        upd_btn_row = QHBoxLayout()
        self._upd_check_btn = QPushButton("업데이트 확인")
        self._upd_check_btn.clicked.connect(self.check_update_requested.emit)
        upd_btn_row.addWidget(self._upd_check_btn)
        ver_lbl = QLabel(f"현재 버전: v{__version__}")
        ver_lbl.setStyleSheet("font-size: 11px; color: #888;")
        upd_btn_row.addWidget(ver_lbl)
        upd_btn_row.addStretch()
        upd_inner.addLayout(upd_btn_row)

        layout.addWidget(self._update_section_frame)
        layout.addSpacing(4)

        layout.addStretch()

    # ------------------------------------------------------------------
    def set_pending_update(self, dto) -> None:
        """자동 체크에서 새 버전 발견 시 호출 — 버튼 텍스트를 업데이트 버전으로 교체한다."""
        self._pending_dto = dto
        self._upd_check_btn.setText(f"v{dto.version}으로 업데이트하기")
        self._upd_check_btn.clicked.disconnect()
        self._upd_check_btn.clicked.connect(self._on_install_update)
        size_mb = dto.size_bytes / (1024 * 1024)
        self._upd_avail_lbl.setText(f"다운로드 크기: {size_mb:.1f} MB")
        self._upd_install_btn.hide()
        self._upd_avail_row.show()

    def scroll_and_flash_update_section(self) -> None:
        """설정 버튼 배지 클릭 후 업데이트 섹션으로 스크롤하고 깜빡임 효과를 준다."""
        self._scroll_area.ensureWidgetVisible(self._update_section_frame)
        self._flash_count = 0
        if self._flash_timer is not None:
            self._flash_timer.stop()
        self._flash_timer = QTimer(self)
        self._flash_timer.timeout.connect(self._do_flash)
        self._flash_timer.start(280)

    def _do_flash(self) -> None:
        if self._flash_count >= 6:
            self._flash_timer.stop()
            self._update_section_frame.setStyleSheet("")
            return
        if self._flash_count % 2 == 0:
            self._update_section_frame.setStyleSheet(
                "#updateSectionFrame { background: rgba(91,155,213,30);"
                " border-radius: 8px; }"
            )
        else:
            self._update_section_frame.setStyleSheet("")
        self._flash_count += 1

    def _on_install_update(self) -> None:
        """'지금 설치' 버튼 — 저장된 DTO로 UpdateDialog를 열어 설치를 진행한다."""
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

    def _refresh_yt_status(self) -> None:
        if self._yt_oauth is None:
            self._yt_status_lbl.setText("○ YouTube API 미초기화")
            self._yt_status_lbl.setStyleSheet("font-size: 9pt; color: #888;")
            return
        if self._yt_oauth.is_authenticated():
            name = self._yt_oauth.get_channel_name() or "인증됨"
            self._yt_status_lbl.setText(f"● 연결됨: {name}")
            self._yt_status_lbl.setStyleSheet("font-size: 9pt; color: #4caf50;")
        else:
            self._yt_status_lbl.setText("○ 미연결 — OAuth 인증이 필요합니다")
            self._yt_status_lbl.setStyleSheet("font-size: 9pt; color: #f44336;")

    def _on_yt_auth(self) -> None:
        if self._yt_oauth is None:
            return
        client_id = self._yt_client_id_edit.text().strip()
        client_secret = self._yt_client_secret_edit.text().strip()
        if not client_id or not client_secret:
            self._yt_status_lbl.setText("Client ID와 Client Secret을 입력하세요.")
            self._yt_status_lbl.setStyleSheet("font-size: 9pt; color: #f4a336;")
            return

        from PyQt6.QtCore import QThread, pyqtSignal as _sig  # noqa: PLC0415

        class _AuthWorker(QThread):
            done = _sig(str)   # channel_name or ""
            err  = _sig(str)

            def __init__(self, oauth, cid, csec, parent=None):
                super().__init__(parent)
                self._oauth = oauth
                self._cid   = cid
                self._csec  = csec

            def run(self):
                try:
                    self._oauth.run_auth_flow(self._cid, self._csec)
                    name = self._oauth.get_channel_name() or "인증됨"
                    self.done.emit(name)
                except Exception as exc:
                    self.err.emit(str(exc))

        self._yt_auth_btn.setEnabled(False)
        self._yt_auth_btn.setText("인증 중…")
        self._yt_status_lbl.setText("브라우저에서 Google 계정으로 승인하세요…")
        self._yt_status_lbl.setStyleSheet("font-size: 9pt; color: #888;")

        worker = _AuthWorker(self._yt_oauth, client_id, client_secret, self)

        def _on_done(name: str) -> None:
            self._yt_auth_btn.setEnabled(True)
            self._yt_auth_btn.setText("OAuth 인증하기")
            self._yt_status_lbl.setText(f"● 연결됨: {name}")
            self._yt_status_lbl.setStyleSheet("font-size: 9pt; color: #4caf50;")
            self._yt_auth_worker = None

        def _on_err(msg: str) -> None:
            self._yt_auth_btn.setEnabled(True)
            self._yt_auth_btn.setText("OAuth 인증하기")
            self._yt_status_lbl.setText(f"인증 실패: {msg[:120]}")
            self._yt_status_lbl.setStyleSheet("font-size: 9pt; color: #f44336;")
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
        except Exception:
            logger.exception("브라우저 쿠키 설정 UI 반영 실패")

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
        self._feed_status_lbl.setStyleSheet("font-size: 8pt; color: #4caf50;")

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
        self._feed_status_lbl.setStyleSheet("font-size: 8pt; color: #4caf50;")
