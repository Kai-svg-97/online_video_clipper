"""상세화면 클립 탭의 '설명 속 챕터' 구역.

챕터가 없는 영상이 대부분이므로 **없을 때 구역이 보이지 않는 것**이 첫 번째 규칙이다
(빈 상자가 남으면 매 영상마다 쓸모없는 공간을 차지한다). 그다음이 고른 챕터만
추출로 넘어가는지다.
"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from application.clip.dtos import ChapterDTO
from gui.panels.video_detail_panel import VideoDetailWidget


@pytest.fixture
def clip_vm():
    from PyQt6.QtCore import QObject, pyqtSignal

    class _VM(QObject):
        clips_changed = pyqtSignal()
        error_occurred = pyqtSignal(str)
        chapters_loaded = pyqtSignal(object)
        chapter_progress = pyqtSignal(int, int, str)
        chapter_finished = pyqtSignal(int, int)
        skip_segments_loaded = pyqtSignal(str, object)

        def __init__(self):
            super().__init__()
            self.clips = []
            self.extracted: list = []
            self.loaded_for: list = []

        def load_clips(self, video_id):
            pass

        def load_skip_segments(self, url):
            pass

        def load_chapters(self, video_id):
            self.loaded_for.append(video_id)

        def extract_chapters(self, video_id, file_path, chapters):
            self.extracted.append((video_id, file_path, list(chapters)))

    return _VM()


def _detail_dto(video_id, description="", file_path="C:/x/영상.mp4"):
    return SimpleNamespace(
        id=video_id,
        url="https://youtu.be/local000001",
        title="로컬 영상",
        channel_name="채널",
        duration_sec=600,
        published_at="",
        view_count=None,
        favorite=False,
        watched=False,
        description=description,
        notes="",
        tags=(),
        downloads=[SimpleNamespace(file_path=file_path, quality="1080p",
                                   fmt="mp4", file_size_bytes=1)],
        failed_downloads=[],
        gemini_summary="",
        summary_status="",
        category_id=None,
        thumbnail_path="",
    )


@pytest.fixture
def local_file(tmp_path):
    """클립 탭은 **로컬 파일이 있어야** 열린다(없으면 안내만 뜬다)."""
    path = tmp_path / "영상.mp4"
    path.write_bytes(b"placeholder")
    return str(path)


def _widget(qtbot, clip_vm, local_file, description=""):
    w = VideoDetailWidget(clip_vm=clip_vm)
    qtbot.addWidget(w)
    w.load(_detail_dto(uuid4(), description, local_file), tag_ids={})
    return w


class TestVisibility:
    def test_챕터가_없으면_구역이_숨는다(self, qtbot, clip_vm, local_file):
        w = _widget(qtbot, clip_vm, local_file)
        clip_vm.chapters_loaded.emit([])
        assert w._chapter_grp.isHidden() is True

    def test_챕터가_있으면_구역이_뜬다(self, qtbot, clip_vm, local_file):
        w = _widget(qtbot, clip_vm, local_file)
        clip_vm.chapters_loaded.emit(
            [ChapterDTO("인트로", 0.0, 60.0), ChapterDTO("본론", 60.0, 600.0)]
        )
        assert w._chapter_grp.isHidden() is False
        assert len(w._chapter_checks) == 2

    def test_탭을_다시_지으면_이전_행이_남지_않는다(self, qtbot, clip_vm, local_file):
        w = _widget(qtbot, clip_vm, local_file)
        clip_vm.chapters_loaded.emit([ChapterDTO("A", 0.0, 1.0), ChapterDTO("B", 1.0, 2.0)])
        clip_vm.chapters_loaded.emit([ChapterDTO("C", 0.0, 1.0), ChapterDTO("D", 1.0, 2.0)])
        assert [c.text().split("  ", 1)[1] for c, _ in w._chapter_checks] == ["C", "D"]

    def test_상세를_열면_챕터를_조회한다(self, qtbot, clip_vm, local_file):
        vid = uuid4()
        w = VideoDetailWidget(clip_vm=clip_vm)
        qtbot.addWidget(w)
        w.load(_detail_dto(vid, file_path=local_file), tag_ids={})
        assert clip_vm.loaded_for[-1] == vid


class TestExtraction:
    def test_체크한_챕터만_넘어간다(self, qtbot, clip_vm, local_file):
        w = _widget(qtbot, clip_vm, local_file)
        a, b = ChapterDTO("A", 0.0, 60.0), ChapterDTO("B", 60.0, 600.0)
        clip_vm.chapters_loaded.emit([a, b])

        w._chapter_checks[1][0].setChecked(False)
        w._chapter_extract_btn.click()

        assert clip_vm.extracted[-1][2] == [a]

    def test_기본값은_전부_선택이다(self, qtbot, clip_vm, local_file):
        w = _widget(qtbot, clip_vm, local_file)
        clip_vm.chapters_loaded.emit([ChapterDTO("A", 0.0, 1.0), ChapterDTO("B", 1.0, 2.0)])
        assert all(check.isChecked() for check, _ in w._chapter_checks)

    def test_전체_선택_해제_토글(self, qtbot, clip_vm, local_file):
        w = _widget(qtbot, clip_vm, local_file)
        clip_vm.chapters_loaded.emit([ChapterDTO("A", 0.0, 1.0), ChapterDTO("B", 1.0, 2.0)])

        w._on_toggle_all_chapters()          # 전부 켜져 있으므로 → 전부 끈다
        assert not any(check.isChecked() for check, _ in w._chapter_checks)
        w._on_toggle_all_chapters()
        assert all(check.isChecked() for check, _ in w._chapter_checks)

    def test_아무것도_안_고르면_안내만_하고_추출하지_않는다(self, qtbot, clip_vm, local_file):
        w = _widget(qtbot, clip_vm, local_file)
        clip_vm.chapters_loaded.emit([ChapterDTO("A", 0.0, 1.0), ChapterDTO("B", 1.0, 2.0)])
        for check, _ in w._chapter_checks:
            check.setChecked(False)

        w._chapter_extract_btn.click()

        assert clip_vm.extracted == []
        assert "하나 이상" in w._chapter_status_lbl.text()

    def test_추출_중에는_버튼이_잠기고_끝나면_풀린다(self, qtbot, clip_vm, local_file):
        w = _widget(qtbot, clip_vm, local_file)
        clip_vm.chapters_loaded.emit([ChapterDTO("A", 0.0, 1.0), ChapterDTO("B", 1.0, 2.0)])

        w._chapter_extract_btn.click()
        assert w._chapter_extract_btn.isEnabled() is False

        clip_vm.chapter_finished.emit(2, 0)
        assert w._chapter_extract_btn.isEnabled() is True
        assert "2개 추출 완료" in w._chapter_status_lbl.text()

    def test_진행_상황이_상태줄에_보인다(self, qtbot, clip_vm, local_file):
        w = _widget(qtbot, clip_vm, local_file)
        clip_vm.chapters_loaded.emit([ChapterDTO("A", 0.0, 1.0), ChapterDTO("B", 1.0, 2.0)])

        clip_vm.chapter_progress.emit(1, 2, "A")

        assert "(1/2)" in w._chapter_status_lbl.text()

    def test_실패_건수도_함께_알린다(self, qtbot, clip_vm, local_file):
        w = _widget(qtbot, clip_vm, local_file)
        clip_vm.chapters_loaded.emit([ChapterDTO("A", 0.0, 1.0), ChapterDTO("B", 1.0, 2.0)])

        clip_vm.chapter_finished.emit(1, 1)

        assert "1개 실패" in w._chapter_status_lbl.text()
