"""LibraryToolsMixin — 라이브러리 도구 섹션 — 가사 출처·클라우드 동기화·가져오기/내보내기·워치 폴더·북마크 가져오기·라이브러리 정리.

    SettingsPanel에 섞여 들어가는 mixin이라 패널 상태(`self._auth`·`self._subtitle_vm`
    같은 주입값, 다른 섹션의 위젯)를 그대로 쓴다(런타임 클래스는 하나다).
"""

from __future__ import annotations

import logging
from pathlib import Path

from PyQt6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
)

from gui.panels.settings.helpers import _t
from gui.panels.settings.sections import (
    _CloudSyncSection,
    _ImportExportSection,
    _LyricsSourcesSection,
)
from gui.text import tr

logger = logging.getLogger(__name__)


class LibraryToolsMixin:
    """라이브러리 도구 섹션 — 가사 출처·클라우드 동기화·가져오기/내보내기·워치 폴더·북마크 가져오기·라이브러리 정리."""

    def _build_lyrics_sources_section(self, layout) -> None:
        """가사 출처 관리(노래 탭 조회 순서/사용여부)."""
        # ── 가사 출처 관리 섹션 (노래 탭 가사 조회 순서/사용여부) ──
        if self._song_vm is not None:
            layout.addSpacing(24)
            sep_lyr = QFrame()
            sep_lyr.setFrameShape(QFrame.Shape.HLine)
            sep_lyr.setStyleSheet(f"color: {_t().border};")
            layout.addWidget(sep_lyr)
            layout.addSpacing(24)
            lyr_label = QLabel(tr("가사 출처 관리"))
            lyr_label.setStyleSheet(
                "font-size: 9px; font-weight: 600; letter-spacing: 0.8px; "
                f"text-transform: uppercase; color: {_t().text_muted}; margin-bottom: 12px;"
            )
            layout.addWidget(lyr_label)
            layout.addSpacing(10)
            self._lyrics_sources_section = _LyricsSourcesSection(self._song_vm)
            layout.addWidget(self._lyrics_sources_section)

    def _build_cloud_sync_section(self, layout) -> None:
        """클라우드 동기화(여러 PC 간 라이브러리 공유)."""
        # ── 클라우드 동기화 섹션 (여러 PC 간 라이브러리 동기화) ──
        if self._sync_vm is not None:
            layout.addSpacing(24)
            sep_sync = QFrame()
            sep_sync.setFrameShape(QFrame.Shape.HLine)
            sep_sync.setStyleSheet(f"color: {_t().border};")
            layout.addWidget(sep_sync)
            layout.addSpacing(24)
            sync_label = QLabel(tr("클라우드 동기화"))
            sync_label.setStyleSheet(
                "font-size: 9px; font-weight: 600; letter-spacing: 0.8px; "
                f"text-transform: uppercase; color: {_t().text_muted}; margin-bottom: 12px;"
            )
            layout.addWidget(sync_label)
            layout.addSpacing(10)
            self._cloud_sync_section = _CloudSyncSection(self._sync_vm)
            layout.addWidget(self._cloud_sync_section)

    def _build_transfer_section(self, layout) -> None:
        """라이브러리 가져오기/내보내기."""
        # ── 라이브러리 가져오기/내보내기 섹션 ──
        if self._transfer_vm is not None:
            layout.addSpacing(24)
            sep_transfer = QFrame()
            sep_transfer.setFrameShape(QFrame.Shape.HLine)
            sep_transfer.setStyleSheet(f"color: {_t().border};")
            layout.addWidget(sep_transfer)
            layout.addSpacing(24)
            transfer_label = QLabel(tr("라이브러리 가져오기/내보내기"))
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

    # ── 워치 폴더 ─────────────────────────────────────────────────

    def _build_watch_folder_section(self, layout) -> None:
        """주소가 담긴 파일을 떨구면 알아서 담는 폴더.

        브라우저에서 주소를 앱까지 끌어다 놓으려면 앱이 떠 있어야 한다. 폴더 하나를
        정해 두면 앱이 꺼져 있어도 거기 모아 뒀다가 켤 때 한꺼번에 담는다.
        """
        from config import settings as cfg  # noqa: PLC0415
        from domain.library.watch_folder import (  # noqa: PLC0415
            DONE_DIR_NAME,
            WATCHED_SUFFIXES,
        )

        self._add_divider(layout)
        label = QLabel(tr("워치 폴더"))
        label.setStyleSheet(
            "font-size: 9px; font-weight: 600; letter-spacing: 0.8px; "
            f"text-transform: uppercase; color: {_t().text_muted};"
        )
        layout.addWidget(label)
        layout.addSpacing(8)

        hint = QLabel(
            tr(
                "이 폴더에 주소가 든 파일({suffixes})을 넣어 두면 "
                "앱이 30초마다 훑어 라이브러리에 담습니다. 브라우저에서 링크를 폴더로 끌면 "
                ".url 파일이 생기므로 그것만으로 끝납니다. 담은 파일은 '{done_dir}' "
                "폴더로 옮겨 둬, 무엇이 처리됐는지 폴더만 봐도 알 수 있습니다."
            ).format(suffixes=" · ".join(WATCHED_SUFFIXES), done_dir=DONE_DIR_NAME)
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(f"font-size: 10px; color: {_t().text_secondary};")
        layout.addWidget(hint)

        row = QHBoxLayout()
        row.setContentsMargins(0, 6, 0, 0)
        self._watch_edit = QLineEdit()
        self._watch_edit.setPlaceholderText(tr("비워 두면 쓰지 않습니다"))
        self._watch_edit.setText(cfg.WATCH_FOLDER or "")
        self._watch_edit.editingFinished.connect(self._on_watch_folder_changed)
        browse = QPushButton(tr("찾기…"))
        browse.setMinimumWidth(60)
        browse.clicked.connect(self._on_watch_folder_browse)
        clear = QPushButton(tr("사용 안 함"))
        clear.setMinimumWidth(80)
        clear.clicked.connect(self._on_watch_folder_clear)
        row.addWidget(self._watch_edit, 1)
        row.addWidget(browse)
        row.addWidget(clear)
        layout.addLayout(row)

        self._watch_status = QLabel("")
        self._watch_status.setWordWrap(True)
        self._watch_status.setStyleSheet(
            f"font-size: 10px; color: {_t().text_secondary};"
        )
        layout.addWidget(self._watch_status)
        layout.addSpacing(24)
        self._refresh_watch_status()

    def _refresh_watch_status(self) -> None:
        """설정된 폴더가 **실제로 있는지** 알린다.

        경로만 적어 두면 오타나 옮겨진 폴더를 알아차릴 수 없다 — 쿠키 파일에서
        똑같은 일이 있었다.
        """
        from pathlib import Path as _Path  # noqa: PLC0415

        raw = self._watch_edit.text().strip()
        if not raw:
            self._watch_status.setText(tr("쓰지 않는 중입니다."))
            return
        if not _Path(raw).is_dir():
            self._watch_status.setText(tr("⚠ 이 경로에 폴더가 없습니다."))
            return
        self._watch_status.setText(
            tr("폴더를 확인했습니다. 바뀐 설정은 앱을 다시 켤 때 적용됩니다.")
        )

    def _on_watch_folder_changed(self) -> None:
        self._save_setting("watch_folder", self._watch_edit.text().strip())
        self._refresh_watch_status()

    def _on_watch_folder_browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, tr("워치 폴더 선택"))
        if folder:
            self._watch_edit.setText(folder)
            self._on_watch_folder_changed()

    def _on_watch_folder_clear(self) -> None:
        self._watch_edit.clear()
        self._on_watch_folder_changed()

    # ── 북마크에서 가져오기 ───────────────────────────────────────

    def _build_bookmark_section(self, layout) -> None:
        """브라우저 북마크(HTML)에서 영상을 담아온다.

        브라우저마다 내보내기 메뉴는 다르지만 결과 형식은 하나로 수렴한다
        (Netscape Bookmark File Format) — 파서 하나로 Chrome·Edge·Firefox·Safari를
        모두 받는다.
        """
        if self._add_videos_fn is None:
            return

        self._add_divider(layout)
        label = QLabel(tr("북마크에서 가져오기"))
        label.setStyleSheet(
            "font-size: 9px; font-weight: 600; letter-spacing: 0.8px; "
            f"text-transform: uppercase; color: {_t().text_muted};"
        )
        layout.addWidget(label)
        layout.addSpacing(8)

        hint = QLabel(
            tr(
                "브라우저에서 북마크를 HTML로 내보낸 뒤 그 파일을 고르면, 담을 영상을 "
                "골라 라이브러리에 넣습니다. 북마크에는 영상이 아닌 링크도 섞여 있으므로 "
                "흔한 영상 사이트만 미리 골라 두고 나머지는 직접 고르게 합니다."
            )
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(f"font-size: 10px; color: {_t().text_secondary};")
        layout.addWidget(hint)

        row = QHBoxLayout()
        row.setContentsMargins(0, 6, 0, 0)
        self._bookmark_btn = QPushButton(tr("북마크 파일 고르기…"))
        self._bookmark_btn.clicked.connect(self._on_bookmark_import_clicked)
        row.addWidget(self._bookmark_btn)
        row.addStretch()
        layout.addLayout(row)

        self._bookmark_status = QLabel("")
        self._bookmark_status.setWordWrap(True)
        self._bookmark_status.setStyleSheet(
            f"font-size: 10px; color: {_t().text_secondary};"
        )
        layout.addWidget(self._bookmark_status)
        layout.addSpacing(24)

    def _on_bookmark_import_clicked(self) -> None:
        from domain.library.bookmarks import parse_bookmarks  # noqa: PLC0415
        from gui.dialogs.bookmark_import_dialog import (  # noqa: PLC0415
            BookmarkImportDialog,
        )

        path, _ = QFileDialog.getOpenFileName(
            self, tr("북마크 파일 선택"), "", tr("북마크 (*.html *.htm);;모든 파일 (*)")
        )
        if not path:
            return
        try:
            # 브라우저가 UTF-8로 쓰지만, 오래된 파일은 다른 인코딩일 수 있다.
            # 읽기 자체가 실패하면 아무것도 못 하므로 깨진 글자를 감수하고 읽는다.
            content = Path(path).read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            logger.exception("북마크 파일 읽기 실패: %s", path)
            self._bookmark_status.setText(tr("파일을 읽지 못했습니다: {exc}").format(exc=exc))
            return

        marks = parse_bookmarks(content)
        if not marks:
            self._bookmark_status.setText(
                tr(
                    "이 파일에서 주소를 찾지 못했습니다. 브라우저의 '북마크 내보내기'로 "
                    "저장한 HTML 파일인지 확인해 주세요."
                )
            )
            return

        categories = self._get_categories_fn() if self._get_categories_fn else []
        dlg = BookmarkImportDialog(marks, categories, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        urls = dlg.selected_urls()
        if not urls:
            return
        self._add_videos_fn(urls, dlg.selected_category_id())
        self._bookmark_status.setText(
            tr("{n}개를 담는 중입니다 — 제목·썸네일은 조회되는 대로 채워집니다.").format(
                n=len(urls)
            )
        )

    def _build_cleanup_section(self, layout) -> None:
        """라이브러리 정리 — 중복 영상·사라진 파일 점검(정리 콜백 주입 시에만 표시).

        찾아 주기만 하고 지우는 것은 사용자가 고른다(되돌릴 수 없는 작업이라 자동으로
        지우지 않는다).
        """
        if self._cleanup_fns is None:
            return
        label = QLabel(tr("라이브러리 정리"))
        label.setStyleSheet(
            "font-size: 9px; font-weight: 600; letter-spacing: 0.8px; "
            f"text-transform: uppercase; color: {_t().text_muted}; margin-bottom: 8px;"
        )
        layout.addWidget(label)
        hint = QLabel(
            tr("같은 영상이 두 번 들어왔거나, 다운로드한 파일이 사라진 기록을 찾습니다.")
        )
        hint.setStyleSheet(f"font-size: 10px; color: {_t().text_secondary};")
        layout.addWidget(hint)
        button = QPushButton(tr("라이브러리 정리 열기…"))
        button.clicked.connect(self._open_cleanup_dialog)
        layout.addWidget(button)
        layout.addSpacing(24)

    def _open_cleanup_dialog(self) -> None:
        from gui.dialogs.library_cleanup_dialog import (  # noqa: PLC0415
            LibraryCleanupDialog,
        )

        # 콜백 개수는 조립 루트가 정한다. 옛 조립(3종)과도 맞물리도록 길이를 본다 —
        # 테스트·다른 진입점이 3종만 넘기는 경우가 있어 여기서 터지면 정리 화면 전체가
        # 열리지 않는다.
        fns = tuple(self._cleanup_fns or ())
        find_duplicates, find_broken, delete_videos = fns[:3]
        find_missing = fns[3] if len(fns) > 3 else None
        LibraryCleanupDialog(
            find_duplicates, find_broken, delete_videos, find_missing, self
        ).exec()
