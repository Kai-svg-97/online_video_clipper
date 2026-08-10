"""라이브러리 가져오기/내보내기 다이얼로그.

`CategorySelectDialog`는 내보내기(로컬 `CategoryDTO`)·가져오기(패키지
`ImportCategoryOptionDTO`) 양쪽에서 재사용한다 — 둘 다 `id`/`name`/`parent_id`/
`video_count` 필드만 있으면 되는 구조라 덕타이핑으로 하나의 체크트리로 충분하다.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from application.transfer.dtos import ImportConflictDTO, ImportFieldDiffDTO


class CategorySelectDialog(QDialog):
    """카테고리 체크트리 — 부모를 체크/해제하면 하위 카테고리도 함께 바뀐다."""

    def __init__(self, categories, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(360, 420)
        self._categories = list(categories)
        self._items_by_id: dict = {}
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        btn_row = QHBoxLayout()
        self._select_all_btn = QPushButton("전체 선택")
        self._select_none_btn = QPushButton("전체 해제")
        self._select_all_btn.clicked.connect(lambda: self._set_all(Qt.CheckState.Checked))
        self._select_none_btn.clicked.connect(lambda: self._set_all(Qt.CheckState.Unchecked))
        btn_row.addWidget(self._select_all_btn)
        btn_row.addWidget(self._select_none_btn)
        btn_row.addStretch()
        root.addLayout(btn_row)

        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        root.addWidget(self._tree, 1)
        self._populate_tree()
        self._tree.itemChanged.connect(self._on_item_changed)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        root.addWidget(btns)

    def _populate_tree(self) -> None:
        children_by_parent: dict = {}
        for c in self._categories:
            children_by_parent.setdefault(c.parent_id, []).append(c)

        def add_children(parent_item: QTreeWidgetItem | None, parent_id) -> None:
            for c in children_by_parent.get(parent_id, []):
                item = QTreeWidgetItem([f"{c.name} ({c.video_count})"])
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(0, Qt.CheckState.Unchecked)
                item.setData(0, Qt.ItemDataRole.UserRole, c.id)
                if parent_item is None:
                    self._tree.addTopLevelItem(item)
                else:
                    parent_item.addChild(item)
                self._items_by_id[c.id] = item
                add_children(item, c.id)

        add_children(None, None)
        self._tree.expandAll()

    def _set_all(self, state: Qt.CheckState) -> None:
        self._tree.blockSignals(True)
        try:
            for item in self._items_by_id.values():
                item.setCheckState(0, state)
        finally:
            self._tree.blockSignals(False)

    def _on_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if column != 0:
            return
        state = item.checkState(0)
        self._tree.blockSignals(True)
        try:
            self._cascade(item, state)
        finally:
            self._tree.blockSignals(False)

    def _cascade(self, item: QTreeWidgetItem, state: Qt.CheckState) -> None:
        for i in range(item.childCount()):
            child = item.child(i)
            child.setCheckState(0, state)
            self._cascade(child, state)

    def selected_category_ids(self) -> list:
        return [
            cid for cid, item in self._items_by_id.items()
            if item.checkState(0) == Qt.CheckState.Checked
        ]


class _FieldChoiceRow(QWidget):
    """충돌 필드 하나 — 기존값/가져올값을 나란히 보여주고 라디오로 고른다."""

    choice_changed = pyqtSignal(str, str)   # (field, "existing"|"incoming")

    def __init__(self, diff: ImportFieldDiffDTO, initial_choice: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._field = diff.field
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(2)
        layout.addWidget(QLabel(f"<b>{diff.label}</b>"))

        self._existing_radio = QRadioButton(
            self._describe("기존값", diff.existing_value, diff.existing_filled)
        )
        self._incoming_radio = QRadioButton(
            self._describe("가져올 값", diff.incoming_value, diff.incoming_filled)
        )
        group = QButtonGroup(self)
        group.addButton(self._existing_radio)
        group.addButton(self._incoming_radio)
        if initial_choice == "incoming":
            self._incoming_radio.setChecked(True)
        else:
            self._existing_radio.setChecked(True)
        self._existing_radio.toggled.connect(self._on_toggled)
        self._incoming_radio.toggled.connect(self._on_toggled)
        layout.addWidget(self._existing_radio)
        layout.addWidget(self._incoming_radio)

    @staticmethod
    def _describe(label: str, value: str, filled: bool) -> str:
        shown = value if filled else "(비어있음)"
        return f"{label}: {shown}"

    def _on_toggled(self, checked: bool) -> None:
        if not checked:
            return
        choice = "incoming" if self.sender() is self._incoming_radio else "existing"
        self.choice_changed.emit(self._field, choice)


class ImportConflictResolutionDialog(QDialog):
    """이미 있는 영상과 값이 다른 필드를 영상별로 보여주고 선택하게 한다.

    좌측은 충돌난 영상 목록, 우측은 선택한 영상의 필드별 기존값/가져올값 +
    라디오 선택. 기본 선택은 각 `ImportFieldDiffDTO.default_choice`를 따른다
    (빈 값을 채우는 쪽이 기본, 둘 다 채워져 있으면 기존값 유지가 기본).
    """

    def __init__(self, conflicts: tuple[ImportConflictDTO, ...], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("가져오기 — 값이 다른 영상 확인")
        self.setMinimumSize(680, 440)
        self._conflicts = list(conflicts)
        self._choices: dict[str, dict[str, str]] = {
            c.url: {f.field: f.default_choice for f in c.fields} for c in self._conflicts
        }
        self._field_rows: dict[str, _FieldChoiceRow] = {}
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        info = QLabel(
            f"이미 있는 영상 {len(self._conflicts)}개에서 값이 다른 항목을 찾았습니다. "
            "영상을 선택해 항목별로 유지할 값을 고르세요."
        )
        info.setWordWrap(True)
        root.addWidget(info)

        bulk_row = QHBoxLayout()
        self._all_incoming_btn = QPushButton("전체 가져오기값 사용")
        self._all_existing_btn = QPushButton("전체 기존값 유지")
        self._all_incoming_btn.clicked.connect(lambda: self._apply_bulk("incoming"))
        self._all_existing_btn.clicked.connect(lambda: self._apply_bulk("existing"))
        bulk_row.addWidget(self._all_incoming_btn)
        bulk_row.addWidget(self._all_existing_btn)
        bulk_row.addStretch()
        root.addLayout(bulk_row)

        split = QSplitter()
        self._list = QListWidget()
        for c in self._conflicts:
            item = QListWidgetItem(c.title)
            item.setData(Qt.ItemDataRole.UserRole, c.url)
            self._list.addItem(item)
        self._list.currentRowChanged.connect(self._on_row_changed)
        split.addWidget(self._list)

        self._detail_scroll = QScrollArea()
        self._detail_scroll.setWidgetResizable(True)
        self._detail_holder = QWidget()
        self._detail_layout = QVBoxLayout(self._detail_holder)
        self._detail_scroll.setWidget(self._detail_holder)
        split.addWidget(self._detail_scroll)
        split.setStretchFactor(1, 1)
        root.addWidget(split, 1)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        root.addWidget(btns)

        if self._conflicts:
            self._list.setCurrentRow(0)

    def _on_row_changed(self, row: int) -> None:
        while self._detail_layout.count():
            item = self._detail_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._field_rows = {}
        if row < 0 or row >= len(self._conflicts):
            return
        conflict = self._conflicts[row]
        for f in conflict.fields:
            field_row = _FieldChoiceRow(f, self._choices[conflict.url][f.field])
            field_row.choice_changed.connect(
                lambda field, choice, url=conflict.url: self._on_choice(url, field, choice)
            )
            self._detail_layout.addWidget(field_row)
            self._field_rows[f.field] = field_row
        self._detail_layout.addStretch()

    def _on_choice(self, url: str, field: str, choice: str) -> None:
        self._choices[url][field] = choice

    def _apply_bulk(self, choice: str) -> None:
        for c in self._conflicts:
            for f in c.fields:
                self._choices[c.url][f.field] = choice
        self._on_row_changed(self._list.currentRow())

    def resolutions(self) -> dict[str, dict[str, str]]:
        return {url: dict(fields) for url, fields in self._choices.items()}
