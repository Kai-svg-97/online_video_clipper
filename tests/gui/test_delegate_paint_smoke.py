"""모든 목록 델리게이트를 **실제로 그려 본다** — 죽지 않는가만 본다.

`paint()` 안에서 난 파이썬 예외는 PyQt가 프로세스 종료로 처리한다(0xC0000409).
로그도 예외 메시지도 남지 않고 앱이 사라지므로, 이 경로는 **직접 그려 보는 것** 말고
막을 방법이 없다(`CLAUDE.md` — 델리게이트 paint 규칙).

값이 맞는지는 각 기능의 테스트가 본다. 여기서는 **DTO에 필드가 늘거나 줄 때 그리는
쪽이 따라오지 못한 경우**를 잡는 게 목적이라, 극단값(None·0·빈 문자열·아주 긴 제목)을
섞어 모든 분기를 밟는다.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from PyQt6.QtCore import QRect, QSize, Qt
from PyQt6.QtGui import QFont, QPainter, QPixmap
from PyQt6.QtWidgets import QStyleOptionViewItem

from application.library.dtos import VideoDTO
from gui.panels.library.delegates import _IconDelegate, _ListDelegate
from gui.panels.library.models import VideoListModel


def _video(**over) -> VideoDTO:
    base = dict(
        id=uuid4(), url="https://youtu.be/abcdefghijk", title="영상",
        channel_name="채널", thumbnail_path="", duration_sec=600,
        favorite=False, watched=False, category_id=None,
    )
    base.update(over)
    return VideoDTO(**base)


# 그리는 쪽이 갈리는 지점들 — 하나라도 빠지면 그 분기가 검사되지 않는다.
CASES = {
    "기본": _video(),
    "길이_모름": _video(duration_sec=None),
    "길이_0": _video(duration_sec=0),
    "제목_빈값": _video(title=""),
    "제목_아주_김": _video(title="가" * 300),
    "즐겨찾기_시청함": _video(favorite=True, watched=True),
    "이어보기_중간": _video(last_position_ms=120_000, duration_sec=600),
    "이어보기_길이_모름": _video(last_position_ms=120_000, duration_sec=None),
    "태그_많음": _video(tag_names=tuple(f"태그{i}" for i in range(20))),
    "검색_일치_표시": _video(match_fields=("title", "channel_name", "subtitle")),
    "카테고리_이름_있음": _video(category_id=uuid4(), category_name="음악"),
    "조회수_없음": _video(view_count=None, published_at=None, created_at=None),
    "썸네일_경로_없는_파일": _video(thumbnail_path="Z:/없는/경로.jpg"),
}


@pytest.fixture
def model(qapp_instance):
    return VideoListModel()


def _paint(delegate, model, width=260, height=220) -> None:
    pm = QPixmap(QSize(width, height))
    pm.fill()
    painter = QPainter(pm)
    try:
        option = QStyleOptionViewItem()
        option.rect = QRect(0, 0, width, height)
        delegate.paint(painter, option, model.index(0, 0))
    finally:
        painter.end()


@pytest.mark.parametrize("case", list(CASES))
class TestLibraryDelegatesSurvive:
    def test_아이콘_카드를_그린다(self, model, case):
        model.set_videos([CASES[case]])
        _paint(_IconDelegate(), model)

    def test_리스트_줄을_그린다(self, model, case):
        model.set_videos([CASES[case]])
        _paint(_ListDelegate(), model, width=800, height=90)


class TestSelectedState:
    def test_선택된_상태로도_그린다(self, model):
        """선택 표시는 별도 분기라 기본 상태만 그려서는 밟지 않는다."""
        from PyQt6.QtWidgets import QStyle

        model.set_videos([_video()])
        pm = QPixmap(QSize(260, 220))
        pm.fill()
        painter = QPainter(pm)
        try:
            option = QStyleOptionViewItem()
            option.rect = QRect(0, 0, 260, 220)
            option.state |= QStyle.StateFlag.State_Selected
            _IconDelegate().paint(painter, option, model.index(0, 0))
        finally:
            painter.end()

    def test_빈_모델은_그릴_것이_없다(self, model):
        model.set_videos([])
        assert model.rowCount() == 0


# ── 글꼴 헬퍼(배치 3) — 나머지 글꼴 사용처를 실제로 그려 본다 ──────────────────


class _RecordingPainter(QPainter):
    """`setFont`로 들어온 글꼴을 모은다 — 델리게이트가 실제로 쓴 글꼴을 본다."""

    def __init__(self, device) -> None:
        super().__init__(device)
        self.fonts: list = []

    def setFont(self, font) -> None:  # noqa: N802
        self.fonts.append(QFont(font))
        super().setFont(font)


def _paint_recording(delegate, index, width=260, height=60):
    pm = QPixmap(QSize(width, height))
    pm.fill()
    painter = _RecordingPainter(pm)
    try:
        option = QStyleOptionViewItem()
        option.rect = QRect(0, 0, width, height)
        delegate.paint(painter, option, index)
    finally:
        painter.end()
    return painter.fonts


def _paint_via(delegate, model):
    """모델을 지역 변수로 붙든 채 그린다(모델이 먼저 죽으면 index가 허공을 본다)."""
    return _paint_recording(delegate, model.index(0, 0))


def _chip_model(name: str):
    from PyQt6.QtGui import QStandardItem, QStandardItemModel

    m = QStandardItemModel()
    it = QStandardItem(name)
    it.setData(3, Qt.ItemDataRole.UserRole + 1)
    it.setData(name, Qt.ItemDataRole.UserRole + 2)
    m.appendRow(it)
    return m


def _tree_model(name: str):
    from PyQt6.QtGui import QStandardItem, QStandardItemModel

    from gui.panels.library.constants import (
        _COUNT_ROLE, _GLYPH_ROLE, _NAME_ROLE, _STAR_ROLE,
    )

    m = QStandardItemModel()
    it = QStandardItem(name)
    it.setData(name, _NAME_ROLE)
    it.setData(7, _COUNT_ROLE)
    it.setData("playlist", _GLYPH_ROLE)
    it.setData(True, _STAR_ROLE)
    m.appendRow(it)
    return m


_NAMES = {"기본": "음악", "빈_이름": "", "아주_김": "가" * 300}


class TestOtherFontSites:
    @pytest.mark.parametrize("name", list(_NAMES.values()), ids=list(_NAMES))
    def test_즐겨찾기_칩을_그린다(self, qapp_instance, name):
        from gui.panels.library.delegates import _FavChipDelegate

        m = _chip_model(name)
        _FavChipDelegate().sizeHint(QStyleOptionViewItem(), m.index(0, 0))
        _paint_recording(_FavChipDelegate(), m.index(0, 0))

    @pytest.mark.parametrize("name", list(_NAMES.values()), ids=list(_NAMES))
    def test_태그_칩을_그린다(self, qapp_instance, name):
        from gui.panels.library.delegates import _TagChipDelegate

        _paint_via(_TagChipDelegate(), _chip_model(name))

    @pytest.mark.parametrize("name", list(_NAMES.values()), ids=list(_NAMES))
    def test_트리_행을_그린다(self, qapp_instance, name):
        from gui.panels.library.delegates import _TreeRowDelegate

        _paint_via(_TreeRowDelegate(), _tree_model(name))

    def test_숨김_태그_델리게이트를_그린다(self, qapp_instance):
        from gui.panels.settings.hidden_tags import _TagMoveDelegate

        _paint_via(_TagMoveDelegate(), _chip_model("록"))

    def test_인기_태그_버튼을_그린다(self, qtbot):
        from gui.panels.library.tag_widgets import _PopularTagButton

        btn = _PopularTagButton("록", 12, "#336699", False)
        qtbot.addWidget(btn)
        btn.resize(180, 26)
        assert not btn.grab().isNull()

    def test_플레이리스트_트리_셰브론을_그린다(self, qtbot):
        from PyQt6.QtWidgets import QTreeWidgetItem

        from gui.panels.library.tree import _PlaylistTree

        tree = _PlaylistTree()
        qtbot.addWidget(tree)
        parent = QTreeWidgetItem(tree, ["부모"])
        QTreeWidgetItem(parent, ["자식"])
        parent.setExpanded(True)
        tree.resize(240, 200)
        tree.show()
        qtbot.waitExposed(tree)
        assert not tree.grab().isNull()


class TestDelegateFontsAreAppFonts:
    """델리게이트가 실제로 쓴 글꼴이 빈 패밀리(MS Sans Serif)로 풀리지 않는다."""

    def _assert_fonts(self, fonts):
        from PyQt6.QtGui import QFontInfo

        assert fonts, "델리게이트가 글꼴을 한 번도 정하지 않았다"
        for f in fonts:
            assert QFontInfo(f).family() != "MS Sans Serif"  # Windows에서만 의미 있다

    def test_즐겨찾기_칩(self, qapp_instance):
        from gui.panels.library.delegates import _FavChipDelegate

        self._assert_fonts(_paint_via(_FavChipDelegate(), _chip_model("a")))

    def test_태그_칩(self, qapp_instance):
        from gui.panels.library.delegates import _TagChipDelegate

        self._assert_fonts(_paint_via(_TagChipDelegate(), _chip_model("a")))

    def test_트리_행(self, qapp_instance):
        from gui.panels.library.delegates import _TreeRowDelegate

        self._assert_fonts(_paint_via(_TreeRowDelegate(), _tree_model("a")))

    def test_아이콘_카드(self, model):
        model.set_videos([CASES["기본"]])
        self._assert_fonts(_paint_recording(_IconDelegate(), model.index(0, 0), 260, 220))

    def test_다운로드_카드(self, qapp_instance):
        from application.download.dtos import DownloadJobDTO, DownloadProgressDTO
        from gui.panels.download_panel import _HistoryCardDelegate, _HistoryModel

        m = _HistoryModel()
        job = DownloadJobDTO(
            id=uuid4(), url="https://youtu.be/abcdefghijk", title="영상",
            status="downloading",
            progress=DownloadProgressDTO(percent=37.0, total_bytes=4096, downloaded_bytes=1516),
        )
        m.set_all([job], [])
        self._assert_fonts(_paint_recording(_HistoryCardDelegate(), m.index(0, 0), 400, 300))


class TestAppFontFailureDoesNotKillPaint:
    """헬퍼가 터져도 paint 안에서 예외가 나가면 안 된다(프로세스 사망 경로)."""

    def test_헬퍼_실패_상황에서도_아이콘_카드를_그린다(self, model, monkeypatch):
        import gui.fonts  # noqa: F401 — 없으면 여기서 실패한다

        class _Boom:
            @staticmethod
            def font(*_a, **_k):
                raise RuntimeError("boom")

        monkeypatch.setattr("gui.fonts.QApplication", _Boom)
        model.set_videos([CASES["기본"]])
        _paint(_IconDelegate(), model)
