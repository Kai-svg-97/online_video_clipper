"""가사 자막 — 현재 줄 판정 로직(``LyricsTrack``)과 렌더 위젯(``LyricsOverlay``).

두 책임을 한 파일에 두되 **클래스로 분리**한다. ``LyricsTrack``은 Qt에 의존하지 않는
순수 로직이라 QApplication 없이 단위 테스트할 수 있고, ``LyricsOverlay``는 그리기만
담당한다. 영상 위에 얹히므로 배경 없이 외곽선 텍스트로 그린다.
"""

from __future__ import annotations

import bisect
import logging
from dataclasses import dataclass

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont, QFontDatabase, QFontMetrics, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QWidget

# 오프셋 상한은 도메인 상수를 그대로 쓴다 — GUI도 저장 전에 같은 값으로 자르는데,
# 두 곳에 따로 적으면 어긋난다(gui → domain 방향이라 레이어 규칙에 맞다).
from domain.song.aggregates import MAX_LYRICS_OFFSET_MS

logger = logging.getLogger(__name__)

# 자막 색은 테마 토큰을 쓰지 않는다 — 영상 프레임 위에 얹히므로 앱 테마가 아니라
# '어떤 영상 위에서도 읽히는가'가 기준이다(의미·가독성 고정색, CLAUDE.md 색상 규칙 예외).
_TEXT_COLOR = QColor("#ffffff")
_TRANSLATION_COLOR = QColor("#e0e0e0")
_OUTLINE_COLOR = QColor("#000000")

# 한글 가독성이 좋은 산세리프 후보 — 설치된 첫 항목을 쓴다.
_FONT_CANDIDATES = (
    "Pretendard",
    "Pretendard Variable",
    "Malgun Gothic",
    "맑은 고딕",
    "Noto Sans KR",
    "Apple SD Gothic Neo",
)

_font_family_cache: str | None = None


def subtitle_font_family() -> str:
    """설치된 자막용 폰트 계열 이름을 고른다(첫 호출 시 1회 조회 후 캐시)."""
    global _font_family_cache
    if _font_family_cache is not None:
        return _font_family_cache
    try:
        installed = set(QFontDatabase.families())
    except Exception:
        logger.debug("폰트 목록 조회 실패 — 시스템 기본 폰트 사용")
        installed = set()
    _font_family_cache = next(
        (name for name in _FONT_CANDIDATES if name in installed), QFont().family()
    )
    return _font_family_cache


@dataclass(frozen=True, slots=True)
class LyricsCue:
    """자막 한 장 — 시각이 있는 가사 한 줄.

    ``line_index``는 원본 가사 목록(노래 탭이 그리는 줄들)에서의 인덱스로, 재생 중인
    줄을 탭에서 하이라이트할 때 쓴다.
    """

    start_ms: int
    original: str
    translation: str = ""
    line_index: int = -1


class LyricsTrack:
    """시각이 있는 가사 줄 모음 + 싱크 오프셋. **Qt 비의존 순수 로직.**

    현재 줄은 다음 줄이 시작하기 직전까지 유효하고, 마지막 줄은 끝까지 유효하다.
    첫 줄 시작 전에는 표시할 자막이 없다(None).
    """

    def __init__(self, cues: list[LyricsCue], offset_ms: int = 0) -> None:
        self._cues = sorted(cues, key=lambda c: c.start_ms)
        self._starts = [c.start_ms for c in self._cues]
        self._offset_ms = 0
        self.offset_ms = offset_ms   # 세터로 clamp 적용

    @classmethod
    def from_lines(cls, lines, offset_ms: int = 0) -> "LyricsTrack":
        """``start_ms``가 있는 줄만 골라 트랙을 만든다.

        ``lines``는 ``original``/``translation``/``start_ms`` 속성을 갖는 객체 목록
        (``LyricsLineDTO``). 구조적으로만 의존해 DTO를 import하지 않는다.
        """
        cues = [
            LyricsCue(
                start_ms=int(line.start_ms),
                original=line.original,
                translation=line.translation,
                line_index=idx,
            )
            for idx, line in enumerate(lines or [])
            if getattr(line, "start_ms", None) is not None
        ]
        return cls(cues, offset_ms=offset_ms)

    def __len__(self) -> int:
        return len(self._cues)

    @property
    def is_empty(self) -> bool:
        return not self._cues

    @property
    def offset_ms(self) -> int:
        return self._offset_ms

    @offset_ms.setter
    def offset_ms(self, value: int) -> None:
        self._offset_ms = max(
            -MAX_LYRICS_OFFSET_MS, min(MAX_LYRICS_OFFSET_MS, int(value))
        )

    def index_at(self, pos_ms: int) -> int | None:
        """재생 위치에 해당하는 줄 인덱스. 표시할 줄이 없으면 None."""
        if not self._cues:
            return None
        target = pos_ms - self._offset_ms
        # bisect_right - 1 = target 이하인 마지막 시작점
        idx = bisect.bisect_right(self._starts, target) - 1
        return idx if idx >= 0 else None

    def cue_at(self, pos_ms: int) -> LyricsCue | None:
        idx = self.index_at(pos_ms)
        return self._cues[idx] if idx is not None else None

    def cue(self, index: int) -> LyricsCue | None:
        return self._cues[index] if 0 <= index < len(self._cues) else None

    def start_of(self, index: int) -> int:
        """``index`` 줄이 실제로 뜨는 재생 위치(오프셋 적용, 음수는 0)."""
        if not (0 <= index < len(self._cues)):
            return 0
        return max(0, self._cues[index].start_ms + self._offset_ms)


class LyricsOverlay(QWidget):
    """영상 위에 얹는 자막 렌더 위젯.

    배경을 칠하지 않고 외곽선 텍스트만 그려 화면을 가리지 않는다. 마우스 이벤트는
    통과시켜 아래의 영상·컨트롤바 조작을 방해하지 않는다. 글자 크기는 위젯 높이에
    비례해 전체화면에서 자동으로 커진다.
    """

    _MIN_FONT_PX = 13
    # 영역(비디오 전체) 높이 대비 원문 글자 크기. 예전 0.055 는 높이 28% 띠에
    # 적용돼 실질 1.5% 였다 — 오버레이가 영역 전체를 덮게 되면서 기준이 바뀌었다.
    _BASE_FONT_RATIO = 0.045
    _TRANSLATION_RATIO = 0.85    # 원문 대비 번역 글자 크기
    _OUTLINE_RATIO = 0.14        # 글자 크기 대비 외곽선 두께
    _LINE_GAP = 4                # 원문/번역 줄 간격(px)
    _SIDE_MARGIN = 24            # 좌우 여백(px)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._original = ""
        self._translation = ""
        self._visible_text = True
        # 사용자 조절값(Task 4에서 setter 로 노출). 비율이라 창 크기와 무관하게 일정.
        self._font_scale: float = 1.0
        self._bottom_ratio: float = 0.10

    # ── 상태 ──────────────────────────────────────────────────────
    def set_cue(self, cue: LyricsCue | None) -> None:
        """표시할 자막을 바꾼다. 내용이 같으면 다시 그리지 않는다."""
        original = cue.original if cue else ""
        translation = cue.translation if cue else ""
        if original == self._original and translation == self._translation:
            return
        self._original = original
        self._translation = translation
        self.update()

    def set_text_visible(self, on: bool) -> None:
        """자막 on/off. ``QWidget.setVisible``과 구분하기 위해 이름을 분리했다."""
        if self._visible_text == on:
            return
        self._visible_text = on
        self.update()

    @property
    def current_text(self) -> tuple[str, str]:
        """(원문, 번역) — 테스트가 렌더 결과 대신 상태를 확인할 때 쓴다."""
        return self._original, self._translation

    # ── 렌더 ──────────────────────────────────────────────────────
    def _bottom_px(self) -> int:
        """아래에서 띄울 픽셀 수 — 비율이라 창 크기가 변해도 비중이 같다."""
        return int(self.height() * self._bottom_ratio)

    def _fonts(self) -> tuple[QFont, QFont]:
        px = max(
            self._MIN_FONT_PX,
            int(self.height() * self._BASE_FONT_RATIO * self._font_scale),
        )
        family = subtitle_font_family()
        main = QFont(family, weight=QFont.Weight.Bold)
        main.setPixelSize(px)
        sub = QFont(family)
        sub.setPixelSize(max(self._MIN_FONT_PX - 2, int(px * self._TRANSLATION_RATIO)))
        return main, sub

    def _wrap(self, text: str, metrics: QFontMetrics, max_w: int) -> list[str]:
        """폭에 맞춰 공백 단위로 줄바꿈한다(한 단어가 넘치면 그대로 둔다)."""
        if not text:
            return []
        if metrics.horizontalAdvance(text) <= max_w:
            return [text]
        out: list[str] = []
        line = ""
        for word in text.split(" "):
            candidate = f"{line} {word}".strip()
            if line and metrics.horizontalAdvance(candidate) > max_w:
                out.append(line)
                line = word
            else:
                line = candidate
        if line:
            out.append(line)
        return out

    def _draw_line(self, painter: QPainter, text: str, font: QFont,
                   color: QColor, center_y: int) -> None:
        metrics = QFontMetrics(font)
        x = (self.width() - metrics.horizontalAdvance(text)) / 2
        path = QPainterPath()
        path.addText(x, center_y, font, text)
        pen = QPen(_OUTLINE_COLOR)
        pen.setWidthF(max(2.0, font.pixelSize() * self._OUTLINE_RATIO))
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)          # 외곽선 먼저
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawPath(path)          # 그 위에 글자 채움

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt 시그니처)
        if not self._visible_text or not (self._original or self._translation):
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        main_font, sub_font = self._fonts()
        max_w = max(50, self.width() - self._SIDE_MARGIN * 2)
        main_metrics, sub_metrics = QFontMetrics(main_font), QFontMetrics(sub_font)

        rows: list[tuple[str, QFont, QColor, int]] = [
            (line, main_font, _TEXT_COLOR, main_metrics.height())
            for line in self._wrap(self._original, main_metrics, max_w)
        ]
        rows += [
            (line, sub_font, _TRANSLATION_COLOR, sub_metrics.height())
            for line in self._wrap(self._translation, sub_metrics, max_w)
        ]
        if not rows:
            painter.end()
            return

        total_h = sum(h for *_, h in rows) + self._LINE_GAP * (len(rows) - 1)
        # 아래에서부터 쌓아 올린다 — 자막은 하단 정렬이 자연스럽다.
        y = self.height() - self._bottom_px() - total_h
        y = max(0, y)   # 글자가 커도 위로 잘려 나가지 않게
        for text, font, color, height in rows:
            baseline = int(y + QFontMetrics(font).ascent())
            self._draw_line(painter, text, font, color, baseline)
            y += height + self._LINE_GAP
        painter.end()
