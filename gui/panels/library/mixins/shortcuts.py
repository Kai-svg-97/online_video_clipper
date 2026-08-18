"""ShortcutsMixin — 라이브러리 화면 키보드 단축키.

이 앱에는 단축키가 **하나도 없었다**(플레이어 안의 재생 조작 키가 전부였다). 상세화면
뒤로가기 버튼은 툴팁에 "(Esc)"라고 적어 두고 정작 Esc를 처리하지 않았다.

여기서 거는 조합은 플레이어 키(Space·J·K·L·방향키·C·[·]·\·M·F·P)와 겹치지 않는다 —
플레이어는 수정키 없는 단일 키만 쓰므로 Ctrl/Alt 조합과 Esc·F5는 안전하다.

범위는 `WidgetWithChildrenShortcut`이다: 다운로드·설정 등 다른 페이지를 보고 있을 때는
발동하지 않는다(포커스가 이 패널 밖이다).
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence, QShortcut

from gui.panels.library.constants import (
    _NAV_ALBUM_DETAIL,
    _VIEW_ALBUMS,
    _VIEW_DETAIL,
    _VIEW_ICON,
    _VIEW_LIST,
)

logger = logging.getLogger(__name__)


class ShortcutsMixin:
    """키보드만으로 이동·검색·보기 전환을 할 수 있게 한다."""

    def _setup_shortcuts(self) -> None:
        """패널 조립이 끝난 뒤 한 번 호출한다(위젯이 다 있어야 한다)."""
        binds = [
            ("Ctrl+F", self._shortcut_focus_search),
            ("Esc", self._shortcut_escape),
            ("Alt+Left", self._shortcut_back),
            ("Alt+Right", self._shortcut_forward),
            ("F5", self._shortcut_reload),
            ("Ctrl+1", lambda: self._shortcut_view(_VIEW_ICON)),
            ("Ctrl+2", lambda: self._shortcut_view(_VIEW_LIST)),
            ("Ctrl+3", lambda: self._shortcut_view(_VIEW_DETAIL)),
            ("Ctrl+4", lambda: self._shortcut_view(_VIEW_ALBUMS)),
        ]
        self._shortcuts = []
        for keys, handler in binds:
            sc = QShortcut(QKeySequence(keys), self)
            sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            sc.activated.connect(handler)
            self._shortcuts.append(sc)

    # ── 동작 ───────────────────────────────────────────────────────
    def _shortcut_focus_search(self) -> None:
        """검색창으로 이동하고 기존 검색어를 통째로 선택한다(바로 덮어쓰기)."""
        self._search_box.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self._search_box.selectAll()

    def _shortcut_escape(self) -> None:
        """Esc — 덮여 있는 화면부터 차례로 걷어낸다.

        상세(영상·앨범)가 열려 있으면 목록으로, 목록이면 검색어를 지운다. 둘 다
        해당 없으면 아무 일도 하지 않는다(창을 닫지 않는다 — 실수로 앱이 사라지면 안 된다).
        """
        idx = self._nav_stack.currentIndex()
        if idx == 1:
            self._on_detail_back_requested()
        elif idx == _NAV_ALBUM_DETAIL:
            self._on_album_back()
        elif self._search_box.text():
            self._search_box.clear()

    def _shortcut_back(self) -> None:
        self._go_back()

    def _shortcut_forward(self) -> None:
        self._go_forward()

    def _shortcut_reload(self) -> None:
        """F5 — 현재 목록을 다시 읽는다(카테고리 개수·태그도 함께 갱신)."""
        self._vm.load()

    def _shortcut_view(self, view_id: int) -> None:
        """Ctrl+1~4 — 보기 유형 전환. 앨범은 음악 카테고리에서만 열린다."""
        if view_id == _VIEW_ALBUMS and not self.album_view_available():
            return
        self._on_view_button_clicked(view_id)
