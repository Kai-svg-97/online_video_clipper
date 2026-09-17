"""라이브러리 정리 — 중복 영상·사라진 다운로드 파일·사라진 원본을 찾아 골라 지운다.

**자동으로 지우지 않는다.** 무엇을 지울지는 사람이 고른다 — 되돌릴 수 없는 작업이고,
'비슷함'(제목·채널이 같아 보임)은 실제로 다른 영상일 수 있기 때문이다. 확실한 중복
(영상 ID 일치)만 기본 선택으로 체크해 두고, 비슷함은 사용자가 직접 켠다.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
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


class _MissingScanWorker(QThread):
    """원본 생존 점검 — 영상당 네트워크 요청이라 반드시 배경에서 돈다."""

    progress = pyqtSignal(int, int)
    done = pyqtSignal(object)

    def __init__(self, find_missing) -> None:
        # 부모를 주지 않는다 — 대화상자가 닫힐 때 실행 중 스레드가 파괴되면
        # Qt가 프로세스를 죽인다(gui/workers.py의 규칙과 같다).
        super().__init__(None)
        self._find_missing = find_missing
        self._stop = False

    def stop(self) -> None:
        """협조적 중단 — 다음 영상으로 넘어가기 전에 멈춘다."""
        self._stop = True

    def run(self) -> None:
        try:
            found = self._find_missing(
                on_progress=self.progress.emit,
                should_stop=lambda: self._stop,
            )
        except Exception:
            logger.exception("원본 점검 실패")
            found = []
        self.done.emit(found)


class LibraryCleanupDialog(QDialog):
    """정리 화면 — 탭 셋(중복 영상 / 사라진 파일 / 사라진 원본).

    앞의 둘은 로컬 점검이라 열자마자 돌지만, **원본 점검은 영상당 네트워크 요청**이라
    사용자가 버튼을 눌러야 시작한다. 수백 건이면 몇 분이 걸려 자동으로 돌릴 수 없다.
    """

    def __init__(
        self,
        find_duplicates: Callable[[], list],
        find_broken: Callable[[], list],
        delete_videos: Callable[[list], None],
        find_missing: Callable[..., list] | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._find_duplicates = find_duplicates
        self._find_broken = find_broken
        self._delete_videos = delete_videos
        self._find_missing = find_missing
        self._missing_worker: _MissingScanWorker | None = None
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
        self._missing_tree = self._make_tree(["영상", "상태", "설명"])
        self._tabs.addTab(self._build_missing_tab(), "사라진 원본")
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
        """체크된 영상 id — 중복 탭과 사라진 원본 탭 **양쪽**에서 모은다."""
        ids = []
        for i in range(self._dup_tree.topLevelItemCount()):
            head = self._dup_tree.topLevelItem(i)
            for j in range(head.childCount()):
                child = head.child(j)
                if child.checkState(0) == Qt.CheckState.Checked:
                    ids.append(child.data(0, _ROLE_VIDEO_ID))
        for i in range(self._missing_tree.topLevelItemCount()):
            row = self._missing_tree.topLevelItem(i)
            if row.checkState(0) == Qt.CheckState.Checked:
                ids.append(row.data(0, _ROLE_VIDEO_ID))
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

    # ── 사라진 원본 탭 ─────────────────────────────────────────────
    def _build_missing_tab(self) -> QWidget:
        holder = QWidget()
        col = QVBoxLayout(holder)
        col.setContentsMargins(0, 8, 0, 0)
        col.addWidget(
            QLabel("원본이 삭제되었거나 비공개로 바뀐 영상")
        )

        self._missing_btn = QPushButton("원본 확인 시작")
        self._missing_btn.clicked.connect(self._on_missing_scan)
        col.addWidget(self._missing_btn, alignment=Qt.AlignmentFlag.AlignLeft)

        self._missing_bar = QProgressBar()
        self._missing_bar.setVisible(False)
        self._missing_bar.setTextVisible(True)
        col.addWidget(self._missing_bar)

        self._missing_note = QLabel(
            "영상마다 인터넷에 한 번씩 물어보므로 시간이 걸립니다. "
            "확인하지 못한 영상은 목록에 넣지 않습니다 — 네트워크 문제로 "
            "멀쩡한 영상을 지우게 되면 안 되기 때문입니다."
        )
        self._missing_note.setWordWrap(True)
        col.addWidget(self._missing_note)

        col.addWidget(self._missing_tree, 1)
        return holder

    def _on_missing_scan(self) -> None:
        """시작/중지 토글 — 긴 작업이라 그만둘 수 있어야 한다."""
        if self._missing_worker is not None:
            self._missing_worker.stop()
            self._missing_btn.setText("중지하는 중…")
            self._missing_btn.setEnabled(False)
            return
        if self._find_missing is None:
            self._status.setText("원본 확인 기능을 쓸 수 없습니다.")
            return
        self._missing_tree.clear()
        self._missing_bar.setValue(0)
        self._missing_bar.setVisible(True)
        self._missing_btn.setText("중지")
        worker = _MissingScanWorker(self._find_missing)
        worker.progress.connect(self._on_missing_progress)
        worker.done.connect(self._on_missing_done)
        self._missing_worker = worker
        worker.start()

    def _on_missing_progress(self, current: int, total: int) -> None:
        self._missing_bar.setMaximum(max(1, total))
        self._missing_bar.setValue(current)
        self._missing_bar.setFormat(f"{current}/{total} 확인 중…")

    def _on_missing_done(self, found) -> None:
        self._missing_worker = None
        self._missing_bar.setVisible(False)
        self._missing_btn.setText("원본 확인 시작")
        self._missing_btn.setEnabled(True)
        for item in found or []:
            row = QTreeWidgetItem([item.title, item.status_label, item.detail])
            row.setData(0, _ROLE_VIDEO_ID, item.video_id)
            row.setFlags(row.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            # **기본은 선택 안 함.** 비공개는 나중에 다시 공개될 수 있고, 삭제된
            # 영상도 기록으로 남겨 두고 싶을 수 있다 — 지울지는 사람이 정한다.
            row.setCheckState(0, Qt.CheckState.Unchecked)
            self._missing_tree.addTopLevelItem(row)
        count = len(found or [])
        self._tabs.setTabText(2, f"사라진 원본 ({count})" if count else "사라진 원본")
        self._status.setText(
            f"원본이 사라진 영상 {count}건을 찾았습니다."
            if count else "사라진 원본이 없습니다."
        )

    def reject(self) -> None:
        """닫기 — 돌고 있는 점검 스레드를 반드시 정리한다.

        실행 중 QThread가 파괴되면 Qt가 프로세스를 즉시 종료한다(CLAUDE.md).
        """
        self._stop_missing_worker()
        super().reject()

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt 규약)
        self._stop_missing_worker()
        super().closeEvent(event)

    def _stop_missing_worker(self) -> None:
        worker = self._missing_worker
        if worker is None:
            return
        worker.stop()
        # 협조적 중단은 '다음 영상으로 넘어가기 전'에 걸리므로, 진행 중인 요청
        # 하나가 끝날 때까지는 기다려야 한다(타임아웃과 같은 자릿수로 잡는다).
        worker.wait(8000)
        self._missing_worker = None
