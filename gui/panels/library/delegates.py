"""목록·트리 행을 직접 그리는 델리게이트와 공용 페인팅 조각.

카드/행의 모든 픽셀이 여기서 결정된다 — 배지·태그 칩·트리 pill 행. 색은 반드시
테마 토큰에서 가져온다(하드코딩 금지, CLAUDE.md 색상 규칙).
"""

from __future__ import annotations

import logging
from uuid import UUID

from PyQt6.QtCore import (
    QModelIndex,
    QRect,
    QSize,
    Qt,
)
from PyQt6.QtGui import (
    QBrush, QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen,
)
from PyQt6.QtWidgets import (
    QStyledItemDelegate,
    QStyleOptionViewItem,
)

from gui.themes.manager import ThemeManager

from gui.panels.library.constants import MATCH_FIELD_LABELS, _BADGE_EMPTY_BG, _COLOR_ROLE, _COUNT_ROLE, _FAV_BADGE_W, _GLYPH_ROLE, _ICON_PAD, _ICON_TEXT_H, _MATCH_ROW_H, _NAME_ROLE, _STAR_ROLE, _TH_ICON, _TH_LIST, _TW_ICON, _TW_LIST
from gui.panels.library.formatting import _fmt_views, _relative_time, _t, chip_colors
from gui.panels.library.models import VideoListModel
from gui.panels.library.thumbnails import _load_thumb_async

# 이어보기 진행률 색 — 의미 색이라 테마와 무관하게 고정한다(어떤 썸네일 위에서도
# '진행'으로 읽혀야 한다).
_PROGRESS_FG = "#e0322e"

logger = logging.getLogger(__name__)


def _progress_of(index) -> float:
    """모델 항목의 이어보기 진행률(0.0~1.0). DTO가 없거나 위치가 없으면 0."""
    from gui.panels.library.models import VideoListModel  # noqa: PLC0415

    dto = index.data(VideoListModel.DtoRole)
    return getattr(dto, "progress_ratio", 0.0) if dto is not None else 0.0


def _paint_progress_bar(
    painter: QPainter, ratio: float, tx: int, ty: int, tw: int, th: int
) -> None:
    """썸네일 아래쪽에 이어보기 진행률 띠를 그린다(0이면 그리지 않는다).

    YouTube와 같은 자리(썸네일 바닥)에 같은 의미로 둔다 — 목록만 훑어도 '어디까지
    봤는지'가 보여야 이어보기가 기능한다. 색은 의미 색(진행)이라 테마와 무관하게
    빨강 계열을 쓰고, 바닥 띠는 반투명 검정으로 깔아 밝은 썸네일에서도 보이게 한다.
    """
    if ratio <= 0:
        return
    bar_h = 3
    by = ty + th - bar_h
    painter.save()
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(QColor(0, 0, 0, 120)))
    painter.drawRect(tx, by, tw, bar_h)
    painter.setBrush(QBrush(QColor(_PROGRESS_FG)))
    painter.drawRect(tx, by, int(tw * min(1.0, max(0.0, ratio))), bar_h)
    painter.restore()


def _paint_duration_badge(painter: QPainter, dur: str, tx: int, ty: int, tw: int, th: int) -> None:
    if not dur:
        return
    painter.save()
    painter.setFont(QFont("", 8))
    fm = painter.fontMetrics()
    bw = fm.horizontalAdvance(dur) + 8
    bh = fm.height() + 4
    bx = tx + tw - bw - 4
    by = ty + th - bh - 4
    painter.setBrush(QBrush(QColor(0, 0, 0, 200)))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(bx, by, bw, bh, 3, 3)
    painter.setPen(QColor("#fff"))
    painter.drawText(QRect(bx, by, bw, bh), Qt.AlignmentFlag.AlignCenter, dur)
    painter.restore()


def _paint_match_badges(painter, rect, keys: tuple[str, ...]) -> None:
    """검색 일치 속성 배지를 rect 안 좌측부터 그린다.

    keys 가 비면 아무것도 그리지 않는다(검색 중이 아닐 때).
    """
    if not keys:
        return
    tokens = ThemeManager.instance().current()
    c = chip_colors(tokens, selected=False)
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setFont(QFont("", 7))
    fm = painter.fontMetrics()
    x = rect.left()
    h = 15
    for key in keys:
        label = MATCH_FIELD_LABELS.get(key, key)
        w = fm.horizontalAdvance(label) + 12
        if x + w > rect.right():
            break
        chip = QRect(x, rect.top(), w, h)
        painter.setBrush(QBrush(QColor(c["bg"])))
        painter.setPen(QPen(QColor(tokens.accent), 1))
        painter.drawRoundedRect(chip, 7, 7)
        painter.setPen(QColor(tokens.accent))
        painter.drawText(chip, Qt.AlignmentFlag.AlignCenter, label)
        x += w + 4
    painter.restore()


class _IconDelegate(QStyledItemDelegate):
    _TW    = _TW_ICON
    _TH    = _TH_ICON
    _PAD   = _ICON_PAD
    _ITEM_W = _TW_ICON + _ICON_PAD * 2
    # 배지 높이는 항상 확보한다 — 검색 중일 때만 늘리면 타이핑마다 그리드가 리플로우된다.
    _ITEM_H = _TH_ICON + _ICON_TEXT_H + _MATCH_ROW_H

    def __init__(self, parent=None, filter_cat_id: UUID | None = None) -> None:
        super().__init__(parent)
        self.filter_cat_id: UUID | None = filter_cat_id
        self.active_tag_names: list[str] = []

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        return QSize(self._ITEM_W, self._ITEM_H)

    def paint(self, painter, option, index) -> None:
        from PyQt6.QtWidgets import QApplication, QStyle  # noqa: PLC0415
        QApplication.style().drawPrimitive(
            QStyle.PrimitiveElement.PE_PanelItemViewItem, option, painter, option.widget
        )

        rect: QRect  = option.rect
        path: str    = index.data(VideoListModel.ThumbPathRole) or ""
        title: str   = index.data(Qt.ItemDataRole.DisplayRole) or ""
        channel: str = index.data(VideoListModel.ChannelRole) or ""
        duration: str= index.data(VideoListModel.DurationRole) or ""
        fav: bool    = bool(index.data(VideoListModel.FavoriteRole))
        watched: bool= bool(index.data(VideoListModel.WatchedRole))
        pub_at: str  = index.data(VideoListModel.PublishedAtRole) or ""
        views: int | None = index.data(VideoListModel.ViewCountRole)
        cat_name: str = index.data(VideoListModel.CategoryRole) or ""

        # ── Thumbnail (둥근 모서리) ──────────────────────────────────
        thumb = _load_thumb_async(path, self._TW, self._TH)
        tx = rect.left() + self._PAD
        ty = rect.top()
        thumb_clip = QPainterPath()
        thumb_clip.addRoundedRect(float(tx), float(ty), float(self._TW), float(self._TH), 6.0, 6.0)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setClipPath(thumb_clip)
        painter.drawPixmap(tx, ty, thumb)
        if watched:
            painter.setOpacity(0.4)
            painter.fillRect(QRect(tx, ty, self._TW, self._TH), QColor(0, 0, 0))
            painter.setOpacity(1.0)
        painter.restore()

        _paint_duration_badge(painter, duration, tx, ty, self._TW, self._TH)
        # 이어보기 진행률 — 목록만 훑어도 어디까지 봤는지 보이게 한다.
        _paint_progress_bar(painter, _progress_of(index), tx, ty, self._TW, self._TH)

        if fav:
            painter.save()
            painter.setFont(QFont("", 11))
            painter.setPen(QColor(_t().star_color))
            painter.drawText(
                QRect(tx + self._TW - 22, ty + 4, 20, 20),
                Qt.AlignmentFlag.AlignCenter, "★",
            )
            painter.restore()

        # ── Text area below thumbnail ──────────────────────────────
        text_x = rect.left() + self._PAD
        text_w = self._TW
        title_top = ty + self._TH + 6

        tok = _t()

        # Title (2 lines, 10pt, elided)
        painter.save()
        painter.setFont(QFont("", 10))
        painter.setPen(QColor(tok.text_primary))
        title_rect = QRect(text_x, title_top, text_w, 40)
        painter.drawText(title_rect, Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignTop, title)
        painter.restore()

        # Channel (8pt, secondary)
        painter.save()
        painter.setFont(QFont("", 8))
        painter.setPen(QColor(tok.text_secondary))
        ch_rect = QRect(text_x, title_top + 42, text_w, 16)
        painter.drawText(ch_rect, Qt.TextFlag.TextSingleLine, channel)
        painter.restore()

        # Views + relative time (3rd row, 8pt, muted)
        views_str = _fmt_views(views)
        time_str = _relative_time(pub_at)
        meta_parts = [p for p in (views_str, time_str) if p]
        meta_left = "  •  ".join(meta_parts) if meta_parts else ""

        show_cat = bool(cat_name)

        video_tag_names: tuple = index.data(VideoListModel.TagNamesRole) or ()
        active_set = set(self.active_tag_names)
        matching_tags = [n for n in video_tag_names if n in active_set] if active_set else []

        painter.save()
        painter.setFont(QFont("", 8))
        row3_rect = QRect(text_x, title_top + 60, text_w, 16)
        if matching_tags:
            tags_text = "  ".join(f"#{n}" for n in matching_tags[:3])
            painter.setPen(QColor(tok.accent))
            painter.drawText(row3_rect, Qt.TextFlag.TextSingleLine | Qt.AlignmentFlag.AlignLeft, tags_text)
        else:
            painter.setPen(QColor(tok.text_muted))
            if meta_left:
                painter.drawText(row3_rect, Qt.TextFlag.TextSingleLine | Qt.AlignmentFlag.AlignLeft, meta_left)
            if show_cat:
                painter.setPen(QColor(tok.accent))
                painter.drawText(row3_rect, Qt.TextFlag.TextSingleLine | Qt.AlignmentFlag.AlignRight, cat_name)
        painter.restore()

        # 검색 일치 속성 배지 — 메타 행 아래
        match_keys: tuple = index.data(VideoListModel.MatchFieldsRole) or ()
        if match_keys:
            _paint_match_badges(
                painter, QRect(text_x, title_top + 78, text_w, 15), match_keys
            )

        # Hover / Selection border (drawn last, on top of everything)
        from PyQt6.QtWidgets import QStyle  # noqa: PLC0415
        is_selected = bool(option.state & QStyle.StateFlag.State_Selected)
        is_hovered  = bool(option.state & QStyle.StateFlag.State_MouseOver)
        if is_selected:
            painter.save()
            pen = QPen(QColor(tok.selected_border))
            pen.setWidth(2)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(rect.adjusted(1, 1, -1, -1))
            painter.restore()
        elif is_hovered:
            painter.save()
            c = QColor(tok.accent)
            c.setAlpha(120)
            pen = QPen(c)
            pen.setWidth(1)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(rect.adjusted(1, 1, -1, -1))
            painter.restore()


class _ListDelegate(QStyledItemDelegate):
    _TW    = _TW_LIST   # 213
    _TH    = _TH_LIST   # 120
    # 3 텍스트 행 + 검색 일치 배지 한 줄. 배지 높이는 항상 확보해 타이핑 중 리플로우를 막는다.
    _ROW_H = _TH_LIST + 40 + _MATCH_ROW_H

    def __init__(self, parent=None, filter_cat_id: UUID | None = None) -> None:
        super().__init__(parent)
        self.filter_cat_id: UUID | None = filter_cat_id
        self.active_tag_names: list[str] = []

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        return QSize(option.rect.width(), self._ROW_H)

    def paint(self, painter, option, index) -> None:
        from PyQt6.QtWidgets import QApplication, QStyle  # noqa: PLC0415
        QApplication.style().drawPrimitive(
            QStyle.PrimitiveElement.PE_PanelItemViewItem, option, painter, option.widget
        )

        rect: QRect  = option.rect
        path: str    = index.data(VideoListModel.ThumbPathRole) or ""
        title: str   = index.data(Qt.ItemDataRole.DisplayRole) or ""
        channel: str = index.data(VideoListModel.ChannelRole) or ""
        duration: str= index.data(VideoListModel.DurationRole) or ""
        fav: bool    = bool(index.data(VideoListModel.FavoriteRole))
        watched: bool= bool(index.data(VideoListModel.WatchedRole))
        pub_at: str  = index.data(VideoListModel.PublishedAtRole) or ""
        views: int | None = index.data(VideoListModel.ViewCountRole)
        cat_name: str = index.data(VideoListModel.CategoryRole) or ""

        # ── Thumbnail (둥근 모서리) ──────────────────────────────────
        thumb = _load_thumb_async(path, self._TW, self._TH)
        tx = rect.left() + 6
        ty = rect.top() + (rect.height() - self._TH) // 2
        thumb_clip = QPainterPath()
        thumb_clip.addRoundedRect(float(tx), float(ty), float(self._TW), float(self._TH), 6.0, 6.0)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setClipPath(thumb_clip)
        painter.drawPixmap(tx, ty, thumb)
        if watched:
            painter.setOpacity(0.4)
            painter.fillRect(QRect(tx, ty, self._TW, self._TH), QColor(0, 0, 0))
            painter.setOpacity(1.0)
        painter.restore()

        _paint_duration_badge(painter, duration, tx, ty, self._TW, self._TH)
        # 이어보기 진행률 — 목록만 훑어도 어디까지 봤는지 보이게 한다.
        _paint_progress_bar(painter, _progress_of(index), tx, ty, self._TW, self._TH)

        # ── Text area ──────────────────────────────────────────────
        text_x = tx + self._TW + 12
        text_w = rect.right() - text_x - (24 if fav else 8)
        text_top = rect.top() + 8

        # Title (2 lines, 10pt, word-wrap + elide)
        painter.save()
        painter.setFont(QFont("", 10))
        fg = option.palette.color(
            option.palette.ColorGroup.Normal, option.palette.ColorRole.Text
        )
        painter.setPen(fg)
        title_rect = QRect(text_x, text_top, text_w, 40)
        painter.drawText(title_rect, Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignTop, title)
        painter.restore()

        tok = _t()

        # Channel (2nd row, 8pt, secondary)
        painter.save()
        painter.setFont(QFont("", 8))
        painter.setPen(QColor(tok.text_secondary))
        ch_rect = QRect(text_x, text_top + 44, text_w, 16)
        painter.drawText(ch_rect, Qt.TextFlag.TextSingleLine, channel)
        painter.restore()

        # Views + time (3rd row) + optional category right-aligned
        views_str = _fmt_views(views)
        time_str = _relative_time(pub_at)
        meta_parts = [p for p in (views_str, time_str) if p]
        meta_left = "  •  ".join(meta_parts) if meta_parts else ""

        show_cat = bool(cat_name)

        painter.save()
        painter.setFont(QFont("", 8))
        row3_rect = QRect(text_x, text_top + 62, text_w, 16)
        painter.setPen(QColor(tok.text_muted))
        if meta_left:
            painter.drawText(row3_rect, Qt.TextFlag.TextSingleLine | Qt.AlignmentFlag.AlignLeft, meta_left)
        if show_cat:
            painter.setPen(QColor(tok.accent))
            painter.drawText(row3_rect, Qt.TextFlag.TextSingleLine | Qt.AlignmentFlag.AlignRight, cat_name)
        painter.restore()

        # 태그 필터 활성 시: 해당 영상이 가진 태그 중 선택된 것만 표시
        video_tag_names: tuple = index.data(VideoListModel.TagNamesRole) or ()
        active_set = set(self.active_tag_names)
        matching_tags = [n for n in video_tag_names if n in active_set] if active_set else []
        if matching_tags:
            tags_text = "  ".join(f"#{n}" for n in matching_tags)
            painter.save()
            painter.setFont(QFont("", 8))
            painter.setPen(QColor(tok.accent))
            tag_rect = QRect(text_x, text_top + 82, text_w, 16)
            painter.drawText(tag_rect, Qt.TextFlag.TextSingleLine | Qt.AlignmentFlag.AlignLeft, tags_text)
            painter.restore()

        # 검색 일치 속성 배지 — 태그 행 아래
        match_keys: tuple = index.data(VideoListModel.MatchFieldsRole) or ()
        if match_keys:
            _paint_match_badges(
                painter, QRect(text_x, text_top + 100, text_w, 15), match_keys
            )

        # Favourite star
        if fav:
            painter.save()
            painter.setFont(QFont("", 11))
            painter.setPen(QColor(tok.star_color))
            painter.drawText(
                QRect(rect.right() - 22, rect.top() + 6, 20, 20),
                Qt.AlignmentFlag.AlignCenter, "★",
            )
            painter.restore()

        # Hover / Selection border (drawn last, on top of everything)
        from PyQt6.QtWidgets import QStyle  # noqa: PLC0415
        is_selected = bool(option.state & QStyle.StateFlag.State_Selected)
        is_hovered  = bool(option.state & QStyle.StateFlag.State_MouseOver)
        if is_selected:
            painter.save()
            pen = QPen(QColor(tok.selected_border))
            pen.setWidth(2)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(rect.adjusted(1, 1, -2, -1))
            painter.restore()
        elif is_hovered:
            painter.save()
            c = QColor(tok.accent)
            c.setAlpha(120)
            pen = QPen(c)
            pen.setWidth(1)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(rect.adjusted(1, 1, -2, -1))
            painter.restore()


class _FavChipDelegate(QStyledItemDelegate):
    """즐겨찾기 칩 — 아이콘+이름 왼쪽, 카운트 배지 오른쪽."""

    def sizeHint(self, option, index) -> QSize:
        text = index.data(Qt.ItemDataRole.DisplayRole) or ""
        fm = QFontMetrics(QFont("", 8))
        text_w = fm.horizontalAdvance(text)
        # 좌우 패딩(14) + 텍스트 + 간격(6) + 배지
        return QSize(text_w + _FAV_BADGE_W + 20, 26)

    def paint(self, painter, option, index) -> None:
        from PyQt6.QtWidgets import QStyle  # noqa: PLC0415

        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        count = index.data(Qt.ItemDataRole.UserRole + 1) or 0
        text = index.data(Qt.ItemDataRole.DisplayRole) or ""
        tokens = ThemeManager.instance().current()
        c = chip_colors(tokens, selected=selected)

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        chip = option.rect.adjusted(2, 2, -2, -2)

        painter.setBrush(QBrush(QColor(c["bg"])))
        painter.setPen(QPen(QColor(c["border"]), 1))
        painter.drawRoundedRect(chip, 10, 10)

        # Count badge (right side)
        badge_text = str(count)
        painter.setFont(QFont("", 7))
        fm = painter.fontMetrics()
        badge_w = max(fm.horizontalAdvance(badge_text) + 10, _FAV_BADGE_W - 4)
        badge_h = chip.height() - 6
        badge_x = chip.right() - badge_w - 3
        badge_y = chip.center().y() - badge_h // 2
        badge_rect = QRect(badge_x, badge_y, badge_w, badge_h)
        # count == 0은 "영상 없음" 경고 상태다 — 테마 색이 아닌 의미 색을 유지한다.
        if count == 0:
            badge_bg, badge_fg = QColor(_BADGE_EMPTY_BG), QColor("#ffffff")
        else:
            badge_bg, badge_fg = QColor(c["badge_bg"]), QColor(c["badge_text"])
        painter.setBrush(QBrush(badge_bg))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(badge_rect, badge_h // 2, badge_h // 2)
        painter.setFont(QFont("", 7))
        painter.setPen(badge_fg)
        painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, badge_text)

        # Name text
        painter.setFont(QFont("", 8))
        painter.setPen(QColor(c["text"]))
        name_rect = QRect(chip.left() + 6, chip.top(), badge_x - chip.left() - 8, chip.height())
        painter.drawText(name_rect, Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextSingleLine, text)

        painter.restore()


class _TagChipDelegate(QStyledItemDelegate):
    """Renders each tag as a rounded chip; right side shows count badge (click = delete)."""

    def sizeHint(self, option, index) -> QSize:
        return QSize(option.rect.width() if option.rect.width() > 0 else 180, 28)

    def paint(self, painter, option, index) -> None:
        from PyQt6.QtWidgets import QStyle  # noqa: PLC0415

        text  = index.data(Qt.ItemDataRole.DisplayRole) or ""
        count = index.data(Qt.ItemDataRole.UserRole + 1) or 0
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        tokens = ThemeManager.instance().current()
        c = chip_colors(tokens, selected=selected)

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        chip = option.rect.adjusted(3, 3, -3, -3)

        # Chip background
        painter.setBrush(QBrush(QColor(c["bg"])))
        painter.setPen(QPen(QColor(c["border"]), 1))
        painter.drawRoundedRect(chip, 10, 10)

        # Count badge (right side) — also acts as the delete hit area
        badge_w = max(20, len(str(count)) * 7 + 10)
        badge_h = chip.height() - 6
        badge_x = chip.right() - badge_w - 4
        badge_y = chip.center().y() - badge_h // 2
        badge_rect = QRect(badge_x, badge_y, badge_w, badge_h)
        painter.setBrush(QBrush(QColor(c["badge_bg"])))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(badge_rect, badge_h // 2, badge_h // 2)

        painter.setFont(QFont("", 7))
        painter.setPen(QColor(c["badge_text"]))
        painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, str(count))

        # Tag text
        painter.setFont(QFont("", 8))
        painter.setPen(QColor(c["text"]))
        painter.drawText(
            QRect(chip.left() + 8, chip.top(), badge_x - chip.left() - 10, chip.height()),
            Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextSingleLine,
            text,
        )

        painter.restore()


class _TreeRowDelegate(QStyledItemDelegate):
    """트리 행을 직접 그린다 — 둥근 pill 행 + 색상 점 + 우측 개수 뱃지 + ★.

    셰브론과 들여쓰기 가이드는 여기서 그리지 않는다. 아이템 영역에 그리면
    클릭이 확장으로 처리되지 않으므로 _PlaylistTree.drawBranches()가 담당한다.
    """

    _ROW_H = 30
    _EMOJI = {"folder": "📂", "playlist": "≡", "channel": "📺", "feed": "📡"}

    def sizeHint(self, option, index) -> QSize:  # noqa: N802
        size = super().sizeHint(option, index)
        return QSize(size.width(), self._ROW_H)

    def paint(self, painter, option, index) -> None:
        from PyQt6.QtWidgets import QStyle  # noqa: PLC0415

        tokens = ThemeManager.instance().current()
        name = index.data(_NAME_ROLE) or index.data(Qt.ItemDataRole.DisplayRole) or ""
        count = index.data(_COUNT_ROLE)
        glyph = index.data(_GLYPH_ROLE) or ""
        color = index.data(_COLOR_ROLE)

        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        is_group = glyph == "group"

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        row = option.rect.adjusted(3, 2, -3, -2)

        # 배경 — 그룹 행은 배경 없이 라벨처럼 보이게 한다
        if not is_group and (selected or hovered):
            if selected:
                bg = QColor(tokens.accent)
                bg.setAlpha(36)            # accent 약 14%
            else:
                bg = QColor(tokens.bg_overlay)
            painter.setBrush(QBrush(bg))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(row, 6, 6)

        x = row.left() + 8

        # 카테고리는 색상 점, 나머지는 작은 글리프
        if glyph == "category" and color:
            dot = QRect(x, row.center().y() - 4, 8, 8)
            painter.setBrush(QBrush(QColor(color)))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(dot)
            x += 16
        elif glyph and self._EMOJI.get(glyph):
            painter.setPen(QColor(tokens.text_muted))
            painter.setFont(QFont("", 8))
            painter.drawText(
                QRect(x, row.top(), 16, row.height()),
                Qt.AlignmentFlag.AlignVCenter,
                self._EMOJI[glyph],
            )
            x += 20

        # 개수 뱃지 (최우측) — ★ 유무와 무관하게 항상 오른쪽 끝에 고정한다.
        # (예전엔 ★이 최우측이라 즐겨찾기 행만 뱃지가 왼쪽으로 밀려 숫자 열이 들쑥날쑥했다.)
        right = row.right() - 6
        if count:
            painter.setFont(QFont("", 7))
            fm = painter.fontMetrics()
            txt = str(count)
            bw = fm.horizontalAdvance(txt) + 12
            bh = 16
            badge = QRect(right - bw, row.center().y() - bh // 2, bw, bh)
            painter.setBrush(QBrush(QColor(tokens.bg_overlay)))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(badge, bh // 2, bh // 2)
            painter.setPen(QColor(tokens.text_secondary))
            painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, txt)
            right = badge.left() - 4

        # 즐겨찾기 ★ — 뱃지 왼쪽
        if index.data(_STAR_ROLE):
            painter.setPen(QColor(tokens.star_color))
            painter.setFont(QFont("", 8))
            star_rect = QRect(right - 14, row.top(), 14, row.height())
            painter.drawText(star_rect, Qt.AlignmentFlag.AlignCenter, "★")
            right = star_rect.left() - 4

        # 이름 — 그룹 행은 자간을 넓힌 muted 라벨
        font = QFont(option.font)
        if is_group:
            font.setPointSize(9)
            font.setWeight(QFont.Weight.Bold)
            font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 108)
            painter.setPen(QColor(tokens.text_muted))
        else:
            painter.setPen(QColor(tokens.accent if selected else tokens.text_primary))
        painter.setFont(font)

        name_rect = QRect(x, row.top(), max(10, right - x), row.height())
        elided = painter.fontMetrics().elidedText(
            name, Qt.TextElideMode.ElideRight, name_rect.width()
        )
        painter.drawText(
            name_rect,
            Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextSingleLine,
            elided,
        )

        painter.restore()
