"""부드러운 휠 스크롤 — 목록·트리·카드 그리드 어디서나 같은 감각으로 굴러가게 한다.

Qt 기본값은 두 가지 이유로 뚝뚝 끊긴다.

1. 아이템 뷰의 기본 스크롤 단위가 **항목 하나**(`ScrollPerItem`)다. 카드 한 장이
   180px가 넘는 이 앱에서는 휠 한 칸에 화면이 통째로 점프한다.
2. 픽셀 단위로 바꿔도 휠 이벤트마다 **즉시 값이 튄다** — 중간 프레임이 없다.

그래서 스크롤 모드를 픽셀로 바꾸고, 휠 입력을 목표값으로 삼아 짧게 보간한다.
연속으로 굴리면 목표만 누적되므로(애니메이션을 다시 시작하지 않는다) 빠르게 굴릴수록
자연스럽게 더 멀리 간다.

**수정키가 눌린 휠은 절대 가로채지 않는다** — Ctrl+휠은 목록 뷰 전환, Ctrl(+Shift)+휠은
자막 크기·위치 조절에 이미 쓰인다. 가로채면 그 기능들이 조용히 죽는다.
가로 전용 영역(추천 스트립처럼 세로 막대가 꺼진 곳)에서는 휠을 가로 스크롤로 돌린다 —
그러지 않으면 휠이 아무 일도 하지 않는다.
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import QEasingCurve, QEvent, QObject, QPropertyAnimation, Qt
from PyQt6.QtWidgets import QAbstractItemView, QAbstractScrollArea, QGraphicsView

logger = logging.getLogger(__name__)

# 휠 한 칸(120)이 움직이는 픽셀. 카드 한 장(≈250px)보다 작게 잡아 여러 번에 나눠 넘어가게 한다.
_STEP_PX = 110
# 보간 시간(ms) — 길면 굼뜨고 짧으면 튄다.
_DURATION_MS = 180


class _SmoothScroller(QObject):
    """뷰포트에 설치되어 휠 입력을 스크롤바 애니메이션으로 바꾸는 이벤트 필터."""

    def __init__(self, area: QAbstractScrollArea) -> None:
        super().__init__(area)
        self._area = area
        self._anim: QPropertyAnimation | None = None
        self._target: int | None = None

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if event.type() != QEvent.Type.Wheel:
            return False
        # 수정키 조합은 다른 기능(뷰 전환·자막 조절)이 쓴다 — 건드리지 않는다.
        if event.modifiers() != Qt.KeyboardModifier.NoModifier:
            return False
        bar = self._pick_bar()
        if bar is None or bar.maximum() <= bar.minimum():
            return False
        delta = event.angleDelta().y() or event.angleDelta().x()
        if not delta:
            return False
        base = self._target if self._target is not None else bar.value()
        target = base - int(delta / 120 * _STEP_PX)
        target = max(bar.minimum(), min(bar.maximum(), target))
        if target == bar.value() and self._target is None:
            return False   # 이미 끝이다 — 부모(창 스크롤 등)에 넘긴다
        self._animate(bar, target)
        return True

    # ── 내부 ───────────────────────────────────────────────────────
    def _pick_bar(self):
        """세로 막대를 쓰되, 세로가 없고 가로만 있는 영역이면 가로로 돌린다."""
        vbar = self._area.verticalScrollBar()
        if vbar is not None and vbar.maximum() > vbar.minimum():
            return vbar
        hbar = self._area.horizontalScrollBar()
        if hbar is not None and hbar.maximum() > hbar.minimum():
            return hbar
        return vbar

    def _animate(self, bar, target: int) -> None:
        self._target = target
        anim = self._anim
        if anim is None:
            anim = QPropertyAnimation(bar, b"value", self)
            anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            anim.finished.connect(self._on_finished)
            self._anim = anim
        anim.stop()
        anim.setDuration(_DURATION_MS)
        anim.setStartValue(bar.value())
        anim.setEndValue(target)
        anim.start()

    def _on_finished(self) -> None:
        self._target = None


def apply_smooth_scroll(area) -> bool:
    """스크롤 영역 하나에 픽셀 스크롤 + 휠 보간을 적용한다(적용했으면 True).

    영상 표시면(`QGraphicsView`)은 건너뛴다 — 스크롤 대상이 아니고, 그 위의 휠은
    자막 크기 조절에 쓰인다.
    """
    if not isinstance(area, QAbstractScrollArea) or isinstance(area, QGraphicsView):
        return False
    if getattr(area, "_smooth_scroller", None) is not None:
        return False
    if isinstance(area, QAbstractItemView):
        area.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        area.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
    viewport = area.viewport()
    if viewport is None:
        return False
    scroller = _SmoothScroller(area)
    viewport.installEventFilter(scroller)
    area._smooth_scroller = scroller   # 참조 보관(GC 방지) + 중복 설치 방지
    return True


def apply_smooth_scroll_tree(root) -> int:
    """위젯 아래의 모든 스크롤 영역에 한 번에 적용한다(적용 개수 반환).

    화면을 다 만든 뒤 한 번 부르면 되고, 나중에 만들어진 영역은 다시 부르면 된다
    (이미 적용된 곳은 건너뛴다).
    """
    count = 0
    for area in root.findChildren(QAbstractScrollArea):
        if apply_smooth_scroll(area):
            count += 1
    if apply_smooth_scroll(root):
        count += 1
    return count
