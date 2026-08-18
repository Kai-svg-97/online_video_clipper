"""주입된 뷰모델이 있을 때만 나타나는 큰 설정 섹션들.

가사 출처(song_vm)·클라우드 동기화(sync_vm)·라이브러리 가져오기/내보내기(transfer_vm).
각 섹션은 자기 뷰모델하고만 이야기하므로 설정 패널은 배치만 담당한다.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


from gui.panels.settings.helpers import _t

logger = logging.getLogger(__name__)


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
