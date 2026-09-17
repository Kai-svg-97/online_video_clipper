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


# ----------------------------------------------------------------------
# 사라진 원본 탭
# ----------------------------------------------------------------------

from application.library.maintenance import MissingSourceDTO  # noqa: E402


def _missing(title="사라진 영상", status="removed", label="삭제됨"):
    return MissingSourceDTO(
        video_id=uuid4(), title=title, url="https://youtu.be/x",
        status=status, status_label=label, detail="원본이 삭제되었습니다",
    )


def _dialog_with_missing(qtbot, found=(), deleted=None):
    dlg = LibraryCleanupDialog(
        find_duplicates=lambda: [],
        find_broken=lambda: [],
        delete_videos=(deleted.extend if deleted is not None else (lambda ids: None)),
        find_missing=lambda on_progress=None, should_stop=None: list(found),
    )
    qtbot.addWidget(dlg)
    return dlg


class TestMissingSources:
    def test_열자마자_돌지_않는다(self, qtbot):
        """영상당 네트워크 요청이라 수백 건이면 몇 분이다 — 사람이 눌러야 시작한다."""
        dlg = _dialog_with_missing(qtbot, found=[_missing()])
        assert dlg._missing_tree.topLevelItemCount() == 0
        assert dlg._missing_btn.text() == "원본 확인 시작"

    def test_결과를_목록에_채운다(self, qtbot):
        dlg = _dialog_with_missing(qtbot)
        dlg._on_missing_done([_missing("A"), _missing("B", "private", "비공개")])
        assert dlg._missing_tree.topLevelItemCount() == 2
        assert dlg._missing_tree.topLevelItem(1).text(1) == "비공개"

    def test_기본은_아무것도_선택하지_않는다(self, qtbot):
        """비공개는 다시 공개될 수 있고, 삭제된 영상도 기록으로 남기고 싶을 수 있다."""
        dlg = _dialog_with_missing(qtbot)
        dlg._on_missing_done([_missing(), _missing()])
        assert dlg.checked_video_ids() == []

    def test_체크하면_삭제_대상에_들어간다(self, qtbot):
        from PyQt6.QtCore import Qt

        dlg = _dialog_with_missing(qtbot)
        item = _missing()
        dlg._on_missing_done([item])
        dlg._missing_tree.topLevelItem(0).setCheckState(0, Qt.CheckState.Checked)
        assert dlg.checked_video_ids() == [item.video_id]

    def test_찾은_수를_탭_제목에_적는다(self, qtbot):
        dlg = _dialog_with_missing(qtbot)
        dlg._on_missing_done([_missing(), _missing(), _missing()])
        assert "(3)" in dlg._tabs.tabText(2)

    def test_없으면_그렇게_알린다(self, qtbot):
        dlg = _dialog_with_missing(qtbot)
        dlg._on_missing_done([])
        assert "없습니다" in dlg._status.text()

    def test_진행률이_표시된다(self, qtbot):
        dlg = _dialog_with_missing(qtbot)
        dlg._on_missing_progress(7, 40)
        assert dlg._missing_bar.value() == 7
        assert dlg._missing_bar.maximum() == 40

    def test_기능이_없으면_안내만_한다(self, qtbot):
        """옛 조립(콜백 3종)과 맞물려도 창이 열려야 한다."""
        dlg = LibraryCleanupDialog(
            find_duplicates=lambda: [], find_broken=lambda: [],
            delete_videos=lambda ids: None,
        )
        qtbot.addWidget(dlg)
        dlg._on_missing_scan()
        assert "쓸 수 없습니다" in dlg._status.text()
