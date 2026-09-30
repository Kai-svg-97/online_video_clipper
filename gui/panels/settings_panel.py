"""설정 패널 — 인라인 QWidget (다이얼로그 아님).

사이드바 ⚙ 아이콘 클릭 시 메인 콘텐츠 스택에 표시된다.
테마 프리셋 선택 + 일반/다운로드 설정 + 저장 경로 표시 + 숨김 태그 관리.

이 파일은 **조립부**다 — 생성자 주입값 보관, 섹션을 쌓는 순서(`_build_ui`), 공통
구분선·설정 저장, 표시될 때의 새로 고침만 둔다. 섹션별 동작은
`gui/panels/settings/mixins/`에, 부품 위젯은 `gui/panels/settings/*.py`에 있다.
런타임 클래스는 여전히 `SettingsPanel` 하나다(mixin 합성).
"""
from __future__ import annotations

import logging
from typing import Callable

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from domain.shared.ports import IYouTubeAuth
from gui.panels.settings.mixins.download import DownloadSectionMixin
from gui.panels.settings.mixins.download_transfer import DownloadTransferMixin
from gui.panels.settings.mixins.feed_cookies import FeedCookieMixin
from gui.panels.settings.mixins.general import GeneralSectionMixin
from gui.panels.settings.mixins.library_tools import LibraryToolsMixin
from gui.panels.settings.mixins.subtitles import SubtitleIndexMixin
from gui.panels.settings.mixins.update import UpdateHeaderMixin
from gui.panels.settings.mixins.youtube_account import YouTubeAccountMixin
from gui.smooth_scroll import apply_smooth_scroll_tree
from gui.text import tr
from gui.themes.manager import ThemeManager
from gui.themes.tokens import ThemeTokens

# ── 분할된 부품 (gui/panels/settings/*) ─────────────────────────────
# 아래 재수출은 기존 임포트 경로(`from gui.panels.settings_panel import ...`)를
# 유지하기 위한 것이다. **monkeypatch는 여기가 아니라 쓰는 쪽 모듈에 건다**
# (예: `open_folder`는 `gui.panels.settings.mixins.general`·`.feed_cookies`가 쓴다).
from gui.panels.settings.theme_cards import (  # noqa: F401
    _ThemeCard,
    _ThemePreview,
)
from gui.panels.settings.hidden_tags import (  # noqa: F401
    _HiddenTagsSection,
    _TagMoveDelegate,
    _TagMoveList,
)
from gui.panels.settings.sections import (  # noqa: F401
    _CloudSyncSection,
    _ImportExportSection,
    _LyricsSourcesSection,
)
from gui.panels.settings.helpers import (  # noqa: F401
    _t,
    open_folder,
)
from gui.panels.settings.mixins.feed_cookies import cookie_help_text  # noqa: F401

logger = logging.getLogger(__name__)


class SettingsPanel(
    UpdateHeaderMixin,
    GeneralSectionMixin,
    DownloadSectionMixin,
    DownloadTransferMixin,
    LibraryToolsMixin,
    SubtitleIndexMixin,
    YouTubeAccountMixin,
    FeedCookieMixin,
    QWidget,
):
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
        cleanup_fns=None,        # (중복찾기, 사라진파일찾기, 삭제, 원본소실찾기) | None
        subtitle_vm=None,        # SubtitleViewModel | None
        get_categories_fn: Callable | None = None,
        add_videos_fn: Callable | None = None,   # (urls, category_id) -> None
        auth_service: IYouTubeAuth | None = None,   # 브라우저 쿠키 인증 | None
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._get_tags_fn = get_tags_fn
        # 구독 피드 — 브라우저 쿠키 섹션이 쓴다. 없으면 그 섹션의 동작만 빠진다
        # (프로필·후보 목록이 비고, 저장·로그인 버튼은 아무것도 하지 않는다).
        self._auth = auth_service
        self._subtitle_vm = subtitle_vm
        self._yt_oauth = yt_oauth
        self._song_vm = song_vm
        self._sync_vm = sync_vm
        self._transfer_vm = transfer_vm
        # 라이브러리 정리 — 조회·삭제를 콜백으로 받는다(설정 화면은 저장소를 모른다).
        self._cleanup_fns = cleanup_fns
        self._get_categories_fn = get_categories_fn
        # 북마크 가져오기가 영상을 담을 때 쓴다. 없으면 그 섹션을 만들지 않는다.
        self._add_videos_fn = add_videos_fn
        self._theme_cards: dict[str, _ThemeCard] = {}
        self._yt_auth_worker = None
        self._pending_dto = None
        self._flash_timer = None
        self._flash_count = 0
        self._build_ui()
        apply_smooth_scroll_tree(self)
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
        header = QLabel(tr("설정"))
        header.setStyleSheet("font-size: 16px; font-weight: 600;")
        header_row.addWidget(header)
        header_row.addStretch()
        header_row.addWidget(self._build_update_header())
        layout.addLayout(header_row)
        layout.addSpacing(20)

        self._build_help_section(layout)
        self._add_divider(layout)
        self._build_language_section(layout)
        self._add_divider(layout)
        self._build_theme_section(layout)
        self._add_divider(layout)
        self._build_paths_section(layout)
        self._add_divider(layout)
        self._build_general_section(layout)
        self._add_divider(layout)
        self._build_download_section(layout)
        self._build_lyrics_sources_section(layout)
        self._build_cloud_sync_section(layout)
        self._build_transfer_section(layout)
        self._build_watch_folder_section(layout)
        self._build_bookmark_section(layout)
        self._build_cleanup_section(layout)
        self._build_subtitle_index_section(layout)
        self._build_youtube_api_section(layout)
        self._build_cookie_section(layout)
        self._build_hidden_tags_section(layout)

        layout.addStretch()

    def _add_divider(self, layout) -> None:
        """섹션 사이 구분선."""
        # ── 구분선 ──
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {_t().border};")
        layout.addWidget(sep)
        layout.addSpacing(24)

    @staticmethod
    def _save_setting(key: str, value) -> None:
        from config import settings as s  # noqa: PLC0415
        s.save_setting(key, value)

    def _build_hidden_tags_section(self, layout) -> None:
        """숨김 태그 관리 — 목록이 길어 맨 아래에 둔다."""
        # ── 숨김 태그 관리 섹션 (맨 아래 — 긴 목록이 다른 설정 접근을 방해하지 않도록) ──
        layout.addSpacing(28)
        sep_hidden = QFrame()
        sep_hidden.setFrameShape(QFrame.Shape.HLine)
        sep_hidden.setStyleSheet(f"color: {_t().border};")
        layout.addWidget(sep_hidden)
        layout.addSpacing(24)

        hidden_label = QLabel(tr("숨김 태그 관리"))
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
            no_tags_lbl = QLabel(tr("태그 목록을 불러올 수 없습니다."))
            no_tags_lbl.setStyleSheet(f"font-size: 10px; color: {_t().text_muted};")
            layout.addWidget(no_tags_lbl)
            self._hidden_tags_section = None

    # ------------------------------------------------------------------
    def showEvent(self, event) -> None:  # type: ignore[override]
        """설정 패널이 표시될 때 숨김 태그 목록을 최신 상태로 갱신한다."""
        super().showEvent(event)
        if self._hidden_tags_section is not None:
            self._hidden_tags_section.refresh()
        self._refresh_yt_status()
        self._refresh_feed_auth_ui()

    # ------------------------------------------------------------------
    def _on_theme_changed(self, tokens: ThemeTokens) -> None:
        """테마 변경 시 선택 상태를 업데이트한다."""
        for name, card in self._theme_cards.items():
            card.set_selected(name == tokens.name)
