"""라이브러리 정리 화면 — 무엇을 기본 선택하고 무엇을 사람에게 맡기는지 고정한다.

되돌릴 수 없는 작업이라 규칙이 곧 안전장치다:
* 확실한 중복(영상 ID 일치)만 **첫 항목을 남기고 나머지를 기본 선택**한다.
* '비슷함'(제목·채널만 같음)은 실제로 다른 영상일 수 있어 **아무것도 선택하지 않는다**.
* 조회가 실패해도 창은 살아 있어야 한다(정리하러 들어왔다가 앱이 죽으면 안 된다).
"""
from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from application.library.maintenance import BrokenDownloadDTO, DuplicateGroupDTO
from domain.library.duplicates import DUPLICATE_EXACT, DUPLICATE_SIMILAR
from gui.dialogs.library_cleanup_dialog import LibraryCleanupDialog


def _vid(title="영상", url="https://youtu.be/x"):
    return SimpleNamespace(id=uuid4(), title=title, channel_name="채널", url=url)


def _dialog(qtbot, groups=(), broken=(), deleted=None):
    dlg = LibraryCleanupDialog(
        find_duplicates=lambda: list(groups),
        find_broken=lambda: list(broken),
        delete_videos=(deleted.extend if deleted is not None else (lambda ids: None)),
    )
    qtbot.addWidget(dlg)
    return dlg


class TestDefaultSelection:
    def test_확실한_중복은_첫_항목만_남기고_선택한다(self, qtbot):
        videos = [_vid("A"), _vid("A 사본"), _vid("A 사본2")]
        group = DuplicateGroupDTO(kind=DUPLICATE_EXACT, key="vid", videos=videos)

        dlg = _dialog(qtbot, groups=[group])

        checked = dlg.checked_video_ids()
        assert checked == [videos[1].id, videos[2].id]   # 첫 번째는 남긴다

    def test_비슷함은_아무것도_선택하지_않는다(self, qtbot):
        """제목·채널만 같은 것은 다른 영상일 수 있다 — 사람이 직접 고르게 한다."""
        group = DuplicateGroupDTO(
            kind=DUPLICATE_SIMILAR, key="제목", videos=[_vid("A"), _vid("A")]
        )

        dlg = _dialog(qtbot, groups=[group])

        assert dlg.checked_video_ids() == []

    def test_중복이_없으면_그렇게_알려준다(self, qtbot):
        dlg = _dialog(qtbot)

        assert "없습니다" in dlg._status.text()


class TestBrokenTab:
    def test_사라진_파일을_나열하고_개수를_탭에_적는다(self, qtbot):
        broken = [
            BrokenDownloadDTO(video_id=None, title="사라진 영상",
                              url="https://youtu.be/x", file_path="D:/gone.mp4"),
        ]

        dlg = _dialog(qtbot, broken=broken)

        assert dlg._broken_tree.topLevelItemCount() == 1
        assert "1" in dlg._tabs.tabText(1)


class TestDeletion:
    def test_선택한_것만_삭제로_넘긴다(self, qtbot):
        videos = [_vid("A"), _vid("A 사본")]
        deleted: list = []
        dlg = _dialog(
            qtbot,
            groups=[DuplicateGroupDTO(DUPLICATE_EXACT, "vid", videos)],
            deleted=deleted,
        )

        ids = dlg.checked_video_ids()
        dlg._delete_videos(ids)

        assert deleted == [videos[1].id]

    def test_선택이_없으면_안내만_한다(self, qtbot):
        dlg = _dialog(qtbot)

        dlg._on_delete()

        assert "선택된 영상이 없습니다" in dlg._status.text()


class TestFailureIsolation:
    def test_조회가_실패해도_창은_살아_있다(self, qtbot):
        def boom():
            raise RuntimeError("조회 실패")

        dlg = LibraryCleanupDialog(boom, boom, lambda ids: None)
        qtbot.addWidget(dlg)

        assert dlg._dup_tree.topLevelItemCount() == 0
        assert dlg._broken_tree.topLevelItemCount() == 0
