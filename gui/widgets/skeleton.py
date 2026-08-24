"""로딩 중 화면 구조를 먼저 보여주는 스켈레톤 프리미티브.

조회가 끝날 때까지 화면이 아무 말도 하지 않으면 "멈췄나?" 하는 불안을 준다.
스켈레톤은 실제 콘텐츠가 놓일 자리를 블록으로 먼저 그려 구조를 보여주고, 셰이머
(shimmer) 그래디언트로 "지금 뭔가 불러오는 중"이라는 신호를 더한다.

목록·앨범 등 여러 화면의 스켈레톤이 이 모듈 하나를 공유해 모양·색·애니메이션
규칙을 일원화한다.

* `ShimmerEffect` — 블록 하나에 흐르는 가로 그래디언트 애니메이션(300ms 주기, 무한
  반복). 그 자체로 자리표시자 블록 하나로 쓸 수 있다.
* `SkeletonRow` — 높이·칸(블록) 개수를 지정해 만드는 스켈레톤 한 행. 칸마다 위젯을
  따로 만들지 않고 **한 번의 paintEvent**에서 전부 그려(저사양 PC 메모리 규칙),
  칸들이 같은 위상으로 함께 반짝이게 한다.

색은 전부 `gui/themes/colors.py`의 `tok()`에서 온다 — 하드코딩 금지
(CLAUDE.md 색상 규칙). `set_loading(False)`를 부르면 애니메이션 타이머가 완전히
멈춘다(보이지 않는 곳에서 도는 타이머 금지).
"""

from __future__ import annotations

from PyQt6.QtCore import QRectF, QTimer
from PyQt6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath
from PyQt6.QtWidgets import QWidget

from gui.themes.colors import tok
from gui.themes.manager import ThemeManager

# 밴드가 왼쪽 끝에서 오른쪽 끝까지 흐르는 데 걸리는 시간(요청 사양: 300ms 무한 반복).
SHIMMER_CYCLE_MS = 300
# 재도색 간격 — 25fps 안팎이면 육안으로 충분히 매끄러우면서 저사양 PC에도 부담이 적다.
_SHIMMER_TICK_MS = 40
_DEFAULT_RADIUS = 6.0
_DEFAULT_GAP = 8
# 밴드 폭(전체 대비 비율) — 작을수록 반짝임이 좁고 선명하다.
_BAND_WIDTH_RATIO = 0.35
# 바탕 톤에서 반짝임 톤으로 밝히는 절대 델타(0~255 채널 기준). 어두운 테마의
# 근검정 톤(예: slate bg_overlay)에서도 `.lighter()`류 곱셈 보정보다 확실히
# 밝아지도록 채널별 덧셈으로 계산한다.
_HIGHLIGHT_DELTA = 34


def _lighten(color: QColor, delta: int) -> QColor:
    """채널마다 `delta`만큼 밝힌 색(0~255 clamp). 곱셈 보정과 달리 근검정에서도 동작한다."""
    return QColor(
        min(255, color.red() + delta),
        min(255, color.green() + delta),
        min(255, color.blue() + delta),
    )


def _skeleton_tones(tokens) -> tuple[QColor, QColor]:
    """(바탕색, 반짝임색). 두 값 모두 테마 토큰에서 파생해 테마마다 달라진다."""
    base = QColor(tokens.bg_overlay)
    highlight = _lighten(base, _HIGHLIGHT_DELTA)
    return base, highlight


def _shimmer_gradient(rect: QRectF, phase: float, base: QColor, highlight: QColor) -> QLinearGradient:
    """밴드가 `phase`(0.0~1.0) 위치를 지나는 좌→우 그래디언트(어두운→밝은→어두운).

    밴드가 사각형 양 끝 밖에서 시작/끝나도록 `phase`를 여유 구간까지 스캔하되,
    Qt는 0~1 범위 밖 stop을 거부하므로 clamp한다.
    """
    band = _BAND_WIDTH_RATIO
    center = phase * (1.0 + band) - band / 2  # -band/2 ~ 1+band/2 스캔
    raw_stops = [
        (center - band, base),
        (center, highlight),
        (center + band, base),
    ]
    stops: list[tuple[float, QColor]] = []
    seen: set[float] = set()
    for pos, color in raw_stops:
        clamped = max(0.0, min(1.0, pos))
        if clamped in seen:
            continue
        seen.add(clamped)
        stops.append((clamped, color))
    stops.sort(key=lambda s: s[0])
    if stops[0][0] > 0.0:
        stops.insert(0, (0.0, base))
    if stops[-1][0] < 1.0:
        stops.append((1.0, base))

    gradient = QLinearGradient(rect.left(), 0.0, rect.right(), 0.0)
    for pos, color in stops:
        gradient.setColorAt(pos, color)
    return gradient


def _paint_shimmer_block(
    painter: QPainter, rect: QRectF, phase: float, loading: bool, tokens, radius: float
) -> None:
    """둥근 사각형 한 칸을 그린다 — 로딩 중이면 셰이머 그래디언트, 아니면 단색."""
    if rect.width() <= 0 or rect.height() <= 0:
        return
    base, highlight = _skeleton_tones(tokens)
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    if loading:
        painter.fillPath(path, _shimmer_gradient(rect, phase, base, highlight))
    else:
        painter.fillPath(path, base)


class ShimmerEffect(QWidget):
    """블록 하나에 흐르는 셰이머 그래디언트 애니메이션.

    `set_loading(True)`로 시작하면 300ms 주기로 무한 반복하는 좌→우 그래디언트를
    그리고, `set_loading(False)`면 타이머를 멈추고 단색 바탕으로 정지한다. 위젯이
    숨겨지면(`hideEvent`) 보이지 않는 곳에서 타이머가 도는 것을 막기 위해 자동으로
    멈추고, 다시 보이면(`showEvent`) 로딩 중이었을 때만 재개한다.
    """

    def __init__(self, parent: QWidget | None = None, radius: float = _DEFAULT_RADIUS) -> None:
        super().__init__(parent)
        self._radius = radius
        self._phase = 0.0
        self._loading = False
        self._timer = QTimer(self)
        self._timer.setInterval(_SHIMMER_TICK_MS)
        self._timer.timeout.connect(self._advance)
        ThemeManager.instance().theme_changed.connect(self._on_theme_changed)

    def set_loading(self, loading: bool) -> None:
        """애니메이션 시작/중단. 값이 같으면 아무 일도 하지 않는다."""
        loading = bool(loading)
        if loading == self._loading:
            return
        self._loading = loading
        if loading and self.isVisible():
            self._phase = 0.0
            self._timer.start()
        else:
            self._timer.stop()
        self.update()

    @property
    def is_loading(self) -> bool:
        return self._loading

    def _advance(self) -> None:
        self._phase = (self._phase + _SHIMMER_TICK_MS / SHIMMER_CYCLE_MS) % 1.0
        self.update()

    def _on_theme_changed(self, _tokens) -> None:
        self.update()

    def hideEvent(self, event) -> None:  # noqa: N802 (Qt 시그니처)
        self._timer.stop()
        super().hideEvent(event)

    def showEvent(self, event) -> None:  # noqa: N802 (Qt 시그니처)
        if self._loading:
            self._timer.start()
        super().showEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt 시그니처)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        _paint_shimmer_block(
            painter, QRectF(self.rect()), self._phase, self._loading, tok(), self._radius
        )
        painter.end()


class SkeletonRow(QWidget):
    """스켈레톤 한 행 — 높이·칸(블록) 개수를 자유롭게 지정한다.

    칸마다 별도 위젯을 만들지 않고 한 번의 `paintEvent`에서 전부 그린다(카드/행마다
    위젯을 만들지 않는 저사양 PC 메모리 규칙). 칸 폭은 `cell_ratios`로 상대 비율을
    주어 나눈다(기본은 칸 수만큼 균등 분할) — 예: 썸네일보다 좁은 메타 줄처럼
    칸마다 폭이 달라야 하는 행을 표현할 수 있다.
    """

    def __init__(
        self,
        cell_count: int = 1,
        height: int = 16,
        parent: QWidget | None = None,
        *,
        cell_ratios: list[float] | None = None,
        gap: int = _DEFAULT_GAP,
        radius: float = _DEFAULT_RADIUS,
    ) -> None:
        super().__init__(parent)
        self.setFixedHeight(height)
        self._ratios = list(cell_ratios) if cell_ratios else [1.0] * max(1, cell_count)
        self._gap = gap
        self._radius = radius
        self._phase = 0.0
        self._loading = False
        self._timer = QTimer(self)
        self._timer.setInterval(_SHIMMER_TICK_MS)
        self._timer.timeout.connect(self._advance)
        ThemeManager.instance().theme_changed.connect(self._on_theme_changed)

    def set_loading(self, loading: bool) -> None:
        """행 전체 애니메이션을 시작/중단한다(칸마다 같은 위상을 공유)."""
        loading = bool(loading)
        if loading == self._loading:
            return
        self._loading = loading
        if loading and self.isVisible():
            self._phase = 0.0
            self._timer.start()
        else:
            self._timer.stop()
        self.update()

    @property
    def is_loading(self) -> bool:
        return self._loading

    def _advance(self) -> None:
        self._phase = (self._phase + _SHIMMER_TICK_MS / SHIMMER_CYCLE_MS) % 1.0
        self.update()

    def _on_theme_changed(self, _tokens) -> None:
        self.update()

    def hideEvent(self, event) -> None:  # noqa: N802 (Qt 시그니처)
        self._timer.stop()
        super().hideEvent(event)

    def showEvent(self, event) -> None:  # noqa: N802 (Qt 시그니처)
        if self._loading:
            self._timer.start()
        super().showEvent(event)

    def _cell_rects(self) -> list[QRectF]:
        n = len(self._ratios)
        total_ratio = sum(self._ratios) or 1.0
        available = max(0.0, self.width() - self._gap * max(0, n - 1))
        rects: list[QRectF] = []
        x = 0.0
        h = float(self.height())
        for ratio in self._ratios:
            w = available * (ratio / total_ratio)
            rects.append(QRectF(x, 0.0, w, h))
            x += w + self._gap
        return rects

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt 시그니처)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        tokens = tok()
        for rect in self._cell_rects():
            _paint_shimmer_block(painter, rect, self._phase, self._loading, tokens, self._radius)
        painter.end()
