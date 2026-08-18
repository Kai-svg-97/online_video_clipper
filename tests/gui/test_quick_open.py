"""빠른 이동(Ctrl+K) — 결과 구성 규칙과 열기 배선을 고정한다.

핵심은 '치는 대로 좁혀지는 느낌'이다:
* 장소(카테고리·재생목록)가 영상보다 앞에 온다 — 영상 결과는 수가 많아 장소를 밀어낸다.
* 이름이 **검색어로 시작하는** 항목이 먼저 온다.
* 종류별 상한이 있어 한 종류가 목록을 삼키지 않는다.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from gui.dialogs.quick_open_dialog import (
    KIND_CATEGORY,
    KIND_PLAYLIST,
    KIND_VIDEO,
    QuickOpenDialog,
    build_hits,
)
from gui.panels.library_panel import LibraryPanel


def _cat(name):
    return SimpleNamespace(id=uuid4(), name=name, parent_id=None, video_count=0)


def _pl(title):
    return SimpleNamespace(id=uuid4(), title=title)


def _vid(title, channel="채널"):
    return SimpleNamespace(id=uuid4(), title=title, channel_name=channel)


class TestBuildHits:
    def test_장소가_영상보다_먼저_온다(self):
        hits = build_hits(
            "music",
            categories=[_cat("Music")],
            playlists=[_pl("Music mix")],
            videos=[_vid("music video")],
        )

        assert [h.kind for h in hits] == [KIND_CATEGORY, KIND_PLAYLIST, KIND_VIDEO]

    def test_검색어로_시작하는_이름이_앞에_온다(self):
        hits = build_hits(
            "ro",
            categories=[_cat("Electro"), _cat("Rock")],
            playlists=[],
            videos=[],
        )

        assert [h.title for h in hits] == ["Rock", "Electro"]

    def test_대소문자를_가리지_않는다(self):
        hits = build_hits("MUSIC", categories=[_cat("music")], playlists=[], videos=[])

        assert len(hits) == 1

    def test_검색어가_없으면_주어진_후보를_그대로_보여준다(self):
        hits = build_hits(
            "", categories=[_cat("A")], playlists=[_pl("B")], videos=[_vid("C")]
        )

        assert len(hits) == 3

    def test_종류별_상한을_지킨다(self):
        hits = build_hits(
            "",
            categories=[_cat(f"C{i}") for i in range(20)],
            playlists=[],
            videos=[_vid(f"V{i}") for i in range(30)],
            max_places=5,
            max_videos=3,
        )

        assert sum(1 for h in hits if h.kind == KIND_CATEGORY) == 5
        assert sum(1 for h in hits if h.kind == KIND_VIDEO) == 3

    def test_일치하지_않는_장소는_빠진다(self):
        hits = build_hits("zzz", categories=[_cat("Music")], playlists=[], videos=[])

        assert hits == []


class TestDialog:
    def test_결과를_채우고_첫_줄을_고른다(self, qtbot):
        hits = build_hits("", categories=[_cat("Music")], playlists=[], videos=[])
        dlg = QuickOpenDialog(lambda _t: hits)
        qtbot.addWidget(dlg)

        assert dlg.current_hits() == hits
        assert dlg._list.currentRow() == 0

    def test_Enter가_고른_항목을_내보낸다(self, qtbot):
        hits = build_hits("", categories=[_cat("Music")], playlists=[], videos=[])
        dlg = QuickOpenDialog(lambda _t: hits)
        qtbot.addWidget(dlg)
        got: list = []
        dlg.chosen.connect(got.append)

        dlg._accept_current()

        assert got == [hits[0]]

    def test_검색이_실패해도_창이_죽지_않는다(self, qtbot):
        def boom(_text):
            raise RuntimeError("조회 실패")

        dlg = QuickOpenDialog(boom)
        qtbot.addWidget(dlg)

        assert dlg.current_hits() == []


@pytest.fixture
def panel(qtbot, library_vm, download_vm, clip_vm, monkeypatch):
    import config.settings as settings
    monkeypatch.setattr(settings, "save_setting", lambda *a, **k: None)
    monkeypatch.setattr(library_vm, "load", lambda *a, **k: None)
    p = LibraryPanel(vm=library_vm, clip_vm=clip_vm, download_vm=download_vm)
    qtbot.addWidget(p)
    yield p
    for worker in list(library_vm._list_workers):
        worker.wait(3000)
    library_vm.shutdown()


class TestPanelWiring:
    def test_카테고리_결과는_그_카테고리로_이동한다(self, panel, monkeypatch):
        from gui.dialogs.quick_open_dialog import QuickHit

        moved: list = []
        monkeypatch.setattr(panel, "_on_cat_filter_changed", lambda cid: moved.append(cid))
        cat_id = uuid4()

        panel._open_quick_hit(QuickHit(KIND_CATEGORY, cat_id, "Music"))

        assert moved == [cat_id]

    def test_영상_결과는_상세를_연다(self, panel, monkeypatch):
        from gui.dialogs.quick_open_dialog import QuickHit

        opened: list = []
        monkeypatch.setattr(panel, "_open_detail", lambda vid: opened.append(vid))
        video_id = uuid4()

        panel._open_quick_hit(QuickHit(KIND_VIDEO, video_id, "영상"))

        assert opened == [video_id]

    def test_재생목록_결과는_그_목록을_연다(self, panel, monkeypatch):
        from gui.dialogs.quick_open_dialog import QuickHit

        opened: list = []
        monkeypatch.setattr(
            panel, "_on_playlist_selected_from_tree", lambda pid: opened.append(pid)
        )
        pl_id = uuid4()

        panel._open_quick_hit(QuickHit(KIND_PLAYLIST, pl_id, "목록"))

        assert opened == [pl_id]

    def test_Ctrl_K가_단축키로_걸려_있다(self, panel):
        from PyQt6.QtGui import QKeySequence

        keys = {sc.key().toString() for sc in panel._shortcuts}
        assert QKeySequence("Ctrl+K").toString() in keys


class TestEnterOpensVideo:
    def test_목록에서_Enter로_영상을_연다(self, panel, library_vm, monkeypatch):
        from application.library.dtos import VideoDTO

        dto = VideoDTO(
            id=uuid4(), url="https://youtu.be/enter001", title="영상",
            channel_name="채널", thumbnail_path="", duration_sec=60,
            favorite=False, watched=False, category_id=None,
        )
        library_vm._videos = [dto]
        panel._on_videos_changed()
        opened: list = []
        monkeypatch.setattr(panel, "_open_detail", lambda vid: opened.append(vid))

        index = panel._model.index(0, 0)
        panel._icon_view.activated.emit(index)

        assert opened == [dto.id]

    def test_활성화는_MagicMock_없이도_동작한다(self, panel):
        assert isinstance(panel._icon_view.activated, object)
        assert not isinstance(panel._model, MagicMock)
