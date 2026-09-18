"""브라우저 북마크에서 영상 담아오기.

북마크 파일에는 영상만 있지 않다 — 쇼핑몰·문서·블로그가 섞여 있다. 그렇다고 우리가
목록을 들고 걸러 버리면 **yt-dlp가 받을 수 있는 사이트를 우리가 막는 꼴**이 된다
(1000개가 넘는다). 그래서 판단을 여기서 사람에게 넘긴다 — 흔한 영상 호스트는 미리
체크해 두고, 나머지는 보고 고른다.

북마크 폴더 이름을 함께 보여 준다. "음악" 폴더에서 온 것인지 "나중에 볼 것"에서
온 것인지가 어느 카테고리에 담을지 정하는 가장 좋은 단서다.
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from domain.library.bookmarks import Bookmark
from gui.smooth_scroll import apply_smooth_scroll

logger = logging.getLogger(__name__)

_URL_ROLE = Qt.ItemDataRole.UserRole + 1


class BookmarkImportDialog(QDialog):
    """북마크 목록에서 담을 것을 고른다.

    `selected_urls()`와 `selected_category_id()`로 결과를 읽는다.
    """

    def __init__(
        self,
        bookmarks: list[Bookmark],
        categories,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("북마크에서 가져오기")
        self.setMinimumSize(620, 480)
        self._bookmarks = list(bookmarks)
        self._categories = list(categories or [])
        self._build_ui()
        self._fill()

    # ── 조립 ──────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        self._summary = QLabel("")
        self._summary.setWordWrap(True)
        root.addWidget(self._summary)

        top = QHBoxLayout()
        self._video_only = QCheckBox("영상으로 보이는 것만 보기")
        self._video_only.setChecked(True)
        self._video_only.checkStateChanged.connect(self._fill)
        all_btn = QPushButton("전체 선택")
        none_btn = QPushButton("전체 해제")
        all_btn.clicked.connect(lambda: self._set_all(True))
        none_btn.clicked.connect(lambda: self._set_all(False))
        top.addWidget(self._video_only)
        top.addStretch()
        top.addWidget(all_btn)
        top.addWidget(none_btn)
        root.addLayout(top)

        self._tree = QTreeWidget()
        self._tree.setColumnCount(3)
        self._tree.setHeaderLabels(["제목", "북마크 폴더", "주소"])
        self._tree.setRootIsDecorated(False)
        self._tree.setUniformRowHeights(True)
        self._tree.itemChanged.connect(self._refresh_summary)
        apply_smooth_scroll(self._tree)
        root.addWidget(self._tree, 1)

        cat_row = QHBoxLayout()
        cat_row.addWidget(QLabel("담을 카테고리"))
        self._cat_combo = QComboBox()
        self._cat_combo.addItem("담지 않음 (미분류)", None)
        for cat in self._categories:
            self._cat_combo.addItem(cat.name, cat.id)
        cat_row.addWidget(self._cat_combo, 1)
        root.addLayout(cat_row)

        hint = QLabel(
            "가져오면 각 주소의 제목·채널·썸네일을 인터넷에서 한 번씩 조회하므로 "
            "건수가 많으면 시간이 걸립니다. 이미 라이브러리에 있는 영상은 건너뜁니다."
        )
        hint.setWordWrap(True)
        root.addWidget(hint)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("가져오기")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("취소")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self._buttons = buttons
        root.addWidget(buttons)

    # ── 채우기 ────────────────────────────────────────────────────

    def _visible(self) -> list[Bookmark]:
        if self._video_only.isChecked():
            return [b for b in self._bookmarks if b.is_likely_video]
        return self._bookmarks

    def _fill(self, *_args) -> None:
        """목록을 다시 그린다 — 체크 상태는 '영상으로 보이는가'로 되돌린다.

        걸러 보기를 껐다 켤 때 이전 체크를 살리려면 상태를 따로 들고 있어야 하는데,
        그 복잡도만큼의 값어치가 없다(고르는 일은 한 번뿐이다).
        """
        self._tree.blockSignals(True)
        self._tree.clear()
        for mark in self._visible():
            item = QTreeWidgetItem([mark.title, mark.folder, mark.url])
            item.setData(0, _URL_ROLE, mark.url)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                0,
                Qt.CheckState.Checked
                if mark.is_likely_video
                else Qt.CheckState.Unchecked,
            )
            item.setToolTip(0, mark.url)
            self._tree.addTopLevelItem(item)
        for col in range(3):
            self._tree.resizeColumnToContents(col)
        self._tree.blockSignals(False)
        self._refresh_summary()

    def _set_all(self, checked: bool) -> None:
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        self._tree.blockSignals(True)
        for i in range(self._tree.topLevelItemCount()):
            self._tree.topLevelItem(i).setCheckState(0, state)
        self._tree.blockSignals(False)
        self._refresh_summary()

    def _refresh_summary(self, *_args) -> None:
        picked = len(self.selected_urls())
        total = len(self._bookmarks)
        shown = self._tree.topLevelItemCount()
        self._summary.setText(
            f"북마크 {total}개 중 {shown}개 표시 · {picked}개 선택됨"
        )
        # 아무것도 안 고르고 누르면 아무 일이 없다 — 누를 수 없게 막는다.
        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(picked > 0)

    # ── 결과 ──────────────────────────────────────────────────────

    def selected_urls(self) -> list[str]:
        out: list[str] = []
        for i in range(self._tree.topLevelItemCount()):
            item = self._tree.topLevelItem(i)
            if item.checkState(0) == Qt.CheckState.Checked:
                out.append(item.data(0, _URL_ROLE))
        return out

    def selected_category_id(self):
        return self._cat_combo.currentData()
