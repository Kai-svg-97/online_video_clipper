"""라이브러리 정리 — 중복 영상·사라진 다운로드 파일을 찾아 골라 지운다.

**자동으로 지우지 않는다.** 무엇을 지울지는 사람이 고른다 — 되돌릴 수 없는 작업이고,
'비슷함'(제목·채널이 같아 보임)은 실제로 다른 영상일 수 있기 때문이다. 확실한 중복
(영상 ID 일치)만 기본 선택으로 체크해 두고, 비슷함은 사용자가 직접 켠다.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QMessageBox,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from domain.library.duplicates import DUPLICATE_EXACT
from gui.smooth_scroll import apply_smooth_scroll
from gui.themes.manager import ThemeManager

logger = logging.getLogger(__name__)

_ROLE_VIDEO_ID = Qt.ItemDataRole.UserRole + 1
_ROLE_PATH = Qt.ItemDataRole.UserRole + 2


class LibraryCleanupDialog(QDialog):
    """정리 화면 — 탭 두 개(중복 영상 / 사라진 파일)."""

    def __init__(
        self,
        find_duplicates: Callable[[], list],
        find_broken: Callable[[], list],
        delete_videos: Callable[[list], None],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._find_duplicates = find_duplicates
        self._find_broken = find_broken
        self._delete_videos = delete_videos
        self.setWindowTitle("라이브러리 정리")
        self.setMinimumSize(720, 480)

        layout = QVBoxLayout(self)
        self._tabs = QTabWidget()
        self._dup_tree = self._make_tree(["영상", "채널", "주소"])
        self._broken_tree = self._make_tree(["영상", "사라진 파일"])
        self._tabs.addTab(self._wrap(self._dup_tree, "중복으로 보이는 영상"), "중복 영상")
        self._tabs.addTab(
            self._wrap(self._broken_tree, "파일이 사라진 다운로드 기록"), "사라진 파일"
        )
        layout.addWidget(self._tabs, 1)

        self._status = QLabel("")
        layout.addWidget(self._status)

        buttons = QDialogButtonBox()
        self._btn_delete = buttons.addButton(
            "선택한 영상 삭제", QDialogButtonBox.ButtonRole.DestructiveRole
        )
        self._btn_delete.clicked.connect(self._on_delete)
        self._btn_refresh = buttons.addButton(
            "다시 검사", QDialogButtonBox.ButtonRole.ActionRole
        )
        self._btn_refresh.clicked.connect(self.refresh)
        buttons.addButton(QDialogButtonBox.StandardButton.Close).clicked.connect(self.reject)
        layout.addWidget(buttons)

        self._apply_theme(ThemeManager.instance().current())
        ThemeManager.instance().theme_changed.connect(self._apply_theme)
        self.refresh()

    # ── 구성 ───────────────────────────────────────────────────────
    def _make_tree(self, headers: list[str]) -> QTreeWidget:
        tree = QTreeWidget()
        tree.setHeaderLabels(headers)
        tree.setRootIsDecorated(True)
        tree.setAlternatingRowColors(True)
        apply_smooth_scroll(tree)
        return tree

    def _wrap(self, tree: QTreeWidget, caption: str) -> QWidget:
        holder = QWidget()
        col = QVBoxLayout(holder)
        col.setContentsMargins(0, 8, 0, 0)
        label = QLabel(caption)
        col.addWidget(label)
        col.addWidget(tree, 1)
        return holder

    def _apply_theme(self, tokens) -> None:
        self._status.setStyleSheet(f"color:{tokens.text_secondary}; font-size:9pt;")

    # ── 채우기 ─────────────────────────────────────────────────────
    def refresh(self) -> None:
        self._fill_duplicates()
        self._fill_broken()

    def _fill_duplicates(self) -> None:
        self._dup_tree.clear()
        try:
            groups = self._find_duplicates()
        except Exception:
            logger.exception("중복 점검 실패")
            groups = []
        removable = 0
        for group in groups:
            exact = group.kind == DUPLICATE_EXACT
            head = QTreeWidgetItem([
                ("같은 영상" if exact else "비슷한 영상") + f" · {len(group.videos)}건",
                "", "",
            ])
            head.setFirstColumnSpanned(True)
            self._dup_tree.addTopLevelItem(head)
            head.setExpanded(True)
            for order, video in enumerate(group.videos):
                child = QTreeWidgetItem([
                    video.title, video.channel_name or "", video.url,
                ])
                child.setData(0, _ROLE_VIDEO_ID, video.id)
                child.setFlags(child.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                # 첫 번째는 남긴다 — 확실한 중복만 나머지를 기본 선택한다.
                keep = order == 0 or not exact
                child.setCheckState(
                    0, Qt.CheckState.Unchecked if keep else Qt.CheckState.Checked
                )
                head.addChild(child)
                if not keep:
                    removable += 1
        self._status.setText(
            f"중복 {len(groups)}묶음 · 기본 선택 {removable}건"
            if groups else "중복으로 보이는 영상이 없습니다."
        )

    def _fill_broken(self) -> None:
        self._broken_tree.clear()
        try:
            broken = self._find_broken()
        except Exception:
            logger.exception("다운로드 파일 점검 실패")
            broken = []
        for item in broken:
            row = QTreeWidgetItem([item.title, item.file_path])
            row.setData(0, _ROLE_PATH, item.file_path)
            self._broken_tree.addTopLevelItem(row)
        if broken:
            self._tabs.setTabText(1, f"사라진 파일 ({len(broken)})")

    # ── 삭제 ───────────────────────────────────────────────────────
    def checked_video_ids(self) -> list:
        """중복 탭에서 체크된 영상 id(테스트·삭제 공용)."""
        ids = []
        for i in range(self._dup_tree.topLevelItemCount()):
            head = self._dup_tree.topLevelItem(i)
            for j in range(head.childCount()):
                child = head.child(j)
                if child.checkState(0) == Qt.CheckState.Checked:
                    ids.append(child.data(0, _ROLE_VIDEO_ID))
        return ids

    def _on_delete(self) -> None:
        ids = self.checked_video_ids()
        if not ids:
            self._status.setText("선택된 영상이 없습니다.")
            return
        answer = QMessageBox.question(
            self, "영상 삭제",
            f"선택한 {len(ids)}개 영상을 라이브러리에서 삭제할까요?\n"
            "(다운로드한 파일은 그대로 남습니다.)",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self._delete_videos(ids)
        except Exception:
            logger.exception("중복 영상 삭제 실패")
            self._status.setText("삭제 중 오류가 발생했습니다. 로그를 확인하세요.")
            return
        self._status.setText(f"{len(ids)}개 영상을 삭제했습니다.")
        self.refresh()
