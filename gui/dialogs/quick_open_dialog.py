"""빠른 이동(Ctrl+K) — 한 입력창에서 카테고리·재생목록·영상을 찾아 바로 연다.

좌측 트리는 깊어질수록 원하는 곳까지 클릭이 늘어나고, 영상은 이름을 알아도 어느
카테고리에 있는지 기억해야 찾을 수 있었다. 여기서는 **무엇이든 이름 일부만 치면**
바로 이동한다.

설계 메모
* 결과는 **카테고리·재생목록 먼저, 영상 나중**이다 — 장소(어디로 갈지)가 물건(무엇을
  열지)보다 먼저 떠오르는 게 자연스럽고, 영상 결과는 수가 많아 장소를 밀어낸다.
* 입력은 디바운스한다(영상 검색이 DB 조회라 키 입력마다 돌리면 낭비다).
* 조회는 **주입받은 콜백**으로만 한다 — 이 다이얼로그는 리포지토리도 뷰모델도 모른다.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from PyQt6.QtCore import QTimer, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)

from gui.smooth_scroll import apply_smooth_scroll
from gui.themes.manager import ThemeManager

logger = logging.getLogger(__name__)

# 입력이 멎은 뒤 조회한다(영상 검색은 DB 조회다).
_DEBOUNCE_MS = 180
# 종류별 표시 상한 — 영상이 목록을 삼키지 않게.
_MAX_PLACES = 8
_MAX_VIDEOS = 12

KIND_CATEGORY = "category"
KIND_PLAYLIST = "playlist"
KIND_VIDEO = "video"

_GLYPH = {KIND_CATEGORY: "📁", KIND_PLAYLIST: "≡", KIND_VIDEO: "▶"}


@dataclass(frozen=True, slots=True)
class QuickHit:
    """빠른 이동 결과 한 줄."""

    kind: str          # KIND_*
    key: object        # category_id | playlist_id | video_id
    title: str
    subtitle: str = ""


class QuickOpenDialog(QDialog):
    """Ctrl+K 팔레트. 고르면 `chosen(QuickHit)`을 내고 닫힌다."""

    chosen = pyqtSignal(object)   # QuickHit

    def __init__(self, search: Callable[[str], list[QuickHit]], parent=None) -> None:
        super().__init__(parent)
        self._search = search
        self.setWindowTitle("빠른 이동")
        self.setModal(True)
        self.setMinimumWidth(520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self._input = QLineEdit()
        self._input.setPlaceholderText("카테고리·재생목록·영상 이름을 입력하세요")
        self._input.textChanged.connect(self._on_text)
        self._input.returnPressed.connect(self._accept_current)
        layout.addWidget(self._input)

        self._list = QListWidget()
        self._list.itemActivated.connect(lambda _i: self._accept_current())
        self._list.itemClicked.connect(lambda _i: self._accept_current())
        apply_smooth_scroll(self._list)
        layout.addWidget(self._list, 1)

        self._hint = QLabel("↑↓ 이동 · Enter 열기 · Esc 닫기")
        layout.addWidget(self._hint)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(_DEBOUNCE_MS)
        self._timer.timeout.connect(self._run_search)
        self._apply_theme(ThemeManager.instance().current())
        ThemeManager.instance().theme_changed.connect(self._apply_theme)
        self._run_search()          # 빈 입력에서도 최근 목록을 보여 준다

    def _apply_theme(self, tokens) -> None:
        self._hint.setStyleSheet(f"color:{tokens.text_muted}; font-size:8pt;")

    # ── 입력 ───────────────────────────────────────────────────────
    def _on_text(self, _text: str) -> None:
        self._timer.start()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        """↑↓는 입력창에 있어도 결과 목록을 움직인다(손을 옮기지 않게)."""
        if event.key() in (Qt.Key.Key_Down, Qt.Key.Key_Up) and self._list.count():
            row = self._list.currentRow()
            step = 1 if event.key() == Qt.Key.Key_Down else -1
            self._list.setCurrentRow(
                max(0, min(self._list.count() - 1, row + step))
            )
            return
        super().keyPressEvent(event)

    # ── 결과 ───────────────────────────────────────────────────────
    def _run_search(self) -> None:
        text = self._input.text().strip()
        try:
            hits = self._search(text)
        except Exception:
            logger.exception("빠른 이동 검색 실패")
            hits = []
        self._fill(hits)

    def _fill(self, hits: list[QuickHit]) -> None:
        self._list.clear()
        for hit in hits:
            label = f"{_GLYPH.get(hit.kind, '·')}  {hit.title}"
            if hit.subtitle:
                label += f"   —   {hit.subtitle}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, hit)
            self._list.addItem(item)
        if self._list.count():
            self._list.setCurrentRow(0)

    def _accept_current(self) -> None:
        item = self._list.currentItem()
        if item is None:
            return
        hit = item.data(Qt.ItemDataRole.UserRole)
        if hit is not None:
            self.chosen.emit(hit)
        self.accept()

    def current_hits(self) -> list[QuickHit]:
        """현재 표시 중인 결과(테스트·진단용)."""
        return [
            self._list.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self._list.count())
        ]


def build_hits(
    text: str,
    categories,
    playlists,
    videos,
    max_places: int = _MAX_PLACES,
    max_videos: int = _MAX_VIDEOS,
) -> list[QuickHit]:
    """검색어와 후보들로 결과 목록을 만든다(순수 함수 — GUI 없이 테스트한다).

    장소(카테고리·재생목록)를 먼저 두고 영상을 뒤에 붙인다. 이름 매칭은 대소문자를
    가리지 않으며, **앞에서 시작하는 이름을 앞에 둔다**(치는 대로 좁혀지는 느낌).
    """
    needle = (text or "").strip().lower()

    def rank(name: str) -> tuple[int, str]:
        low = (name or "").lower()
        return (0 if needle and low.startswith(needle) else 1, low)

    def matches(name: str) -> bool:
        return not needle or needle in (name or "").lower()

    hits: list[QuickHit] = []
    places = [
        QuickHit(KIND_CATEGORY, c.id, c.name, "카테고리")
        for c in categories if matches(getattr(c, "name", ""))
    ]
    places += [
        QuickHit(KIND_PLAYLIST, p.id, getattr(p, "title", ""), "재생목록")
        for p in playlists if matches(getattr(p, "title", ""))
    ]
    places.sort(key=lambda h: rank(h.title))
    hits.extend(places[:max_places])

    hits.extend(
        QuickHit(KIND_VIDEO, v.id, v.title, getattr(v, "channel_name", "") or "영상")
        for v in videos[:max_videos]
    )
    return hits
