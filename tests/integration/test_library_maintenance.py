"""라이브러리 정리 — 중복 판정과 깨진 파일 점검을 고정한다.

URL 문자열만 비교하는 기존 중복 방지(`get_by_url`)로는 **주소 형태만 다른 같은 영상**을
못 잡는다(`youtu.be/ID` vs `watch?v=ID&list=…`). 그래서 영상 ID로 먼저 묶고, ID를 모르는
것만 제목·채널로 '비슷함'으로 묶는다 — 비슷함은 자동 삭제 대상이 아니라 사람이 고른다.
"""
from __future__ import annotations

import pytest

from application.library.maintenance import (
    FindBrokenDownloadsHandler,
    FindDuplicatesQuery,
    FindDuplicateVideosHandler,
)
from domain.library.aggregates import VideoAggregate
from domain.library.duplicates import (
    DUPLICATE_EXACT,
    DUPLICATE_SIMILAR,
    group_duplicates,
    normalize_title,
    youtube_video_id,
)
from domain.library.value_objects import VideoUrl
from infrastructure.persistence.database import Database
from infrastructure.persistence.sqlite_video_repository import SqliteVideoRepository


class _Fake:
    """중복 판정 입력 대역 — 도메인 함수는 url·title·channel_name만 본다."""

    def __init__(self, url="", title="", channel_name=""):
        self.url = url
        self.title = title
        self.channel_name = channel_name


class TestVideoIdExtraction:
    def test_여러_주소_형태에서_같은_id를_뽑는다(self):
        ids = {
            youtube_video_id("https://youtu.be/dQw4w9WgXcQ"),
            youtube_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
            youtube_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PL1&t=30"),
            youtube_video_id("https://www.youtube.com/shorts/dQw4w9WgXcQ"),
            youtube_video_id("https://www.youtube.com/embed/dQw4w9WgXcQ"),
        }

        assert ids == {"dQw4w9WgXcQ"}

    def test_유튜브가_아니면_빈_값이다(self):
        assert youtube_video_id("https://vimeo.com/12345") == ""
        assert youtube_video_id("") == ""


class TestGrouping:
    def test_주소_형태만_다른_같은_영상은_확실한_중복이다(self):
        items = [
            _Fake("https://youtu.be/dQw4w9WgXcQ", "A"),
            _Fake("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=10", "A 다른 제목"),
        ]

        groups = group_duplicates(items)

        assert len(groups) == 1
        assert groups[0].kind == DUPLICATE_EXACT
        assert groups[0].extra_count == 1

    def test_제목_채널이_같으면_비슷함으로만_묶는다(self):
        items = [
            _Fake("https://vimeo.com/1", "같은 제목", "채널"),
            _Fake("https://vimeo.com/2", "같은  제목!!", "채널"),
        ]

        groups = group_duplicates(items)

        assert [g.kind for g in groups] == [DUPLICATE_SIMILAR]

    def test_같은_제목이라도_채널이_다르면_묶지_않는다(self):
        items = [
            _Fake("https://vimeo.com/1", "커버곡", "채널A"),
            _Fake("https://vimeo.com/2", "커버곡", "채널B"),
        ]

        assert group_duplicates(items) == []

    def test_id로_묶인_것을_제목으로_다시_묶지_않는다(self):
        items = [
            _Fake("https://youtu.be/aaaaaaaaaaa", "같은 제목", "채널"),
            _Fake("https://www.youtube.com/watch?v=aaaaaaaaaaa", "같은 제목", "채널"),
        ]

        groups = group_duplicates(items)

        assert len(groups) == 1     # 한 묶음만 — 두 번 세면 정리 화면이 헷갈린다

    def test_혼자면_중복이_아니다(self):
        assert group_duplicates([_Fake("https://youtu.be/aaaaaaaaaaa", "혼자")]) == []

    def test_확실한_중복이_비슷함보다_먼저_온다(self):
        items = [
            _Fake("https://vimeo.com/1", "제목", "채널"),
            _Fake("https://vimeo.com/2", "제목", "채널"),
            _Fake("https://youtu.be/bbbbbbbbbbb", "다른"),
            _Fake("https://www.youtube.com/watch?v=bbbbbbbbbbb", "다른"),
        ]

        kinds = [g.kind for g in group_duplicates(items)]

        assert kinds == [DUPLICATE_EXACT, DUPLICATE_SIMILAR]

    def test_제목_정규화는_기호와_대소문자를_지운다(self):
        assert normalize_title("  Hello,  World!! ") == normalize_title("hello world")


@pytest.fixture
def repo(tmp_path):
    db = Database(path=tmp_path / "clean.db")
    db.initialize()
    return SqliteVideoRepository(db)


class TestFindDuplicatesHandler:
    def test_쇼츠와_일반_주소가_같은_영상이면_중복으로_잡는다(self, repo):
        """URL 정규화는 youtu.be/watch만 합치고 **/shorts/는 그대로 둔다** —
        그래서 같은 영상이 두 행으로 들어온다(등록 단계에서 못 막는 실제 경로)."""
        for url in ("https://www.youtube.com/watch?v=ccccccccccc",
                    "https://www.youtube.com/shorts/ccccccccccc"):
            repo.save(VideoAggregate.create(VideoUrl(url), "같은 영상"))
        repo.save(VideoAggregate.create(VideoUrl("https://youtu.be/ddddddddddd"), "혼자"))

        groups = FindDuplicateVideosHandler(repo).handle(FindDuplicatesQuery())

        assert len(groups) == 1
        assert groups[0].extra_count == 1
        assert {v.url for v in groups[0].videos} == {
            "https://www.youtube.com/watch?v=ccccccccccc",
            "https://www.youtube.com/shorts/ccccccccccc",
        }

    def test_중복이_없으면_빈_목록이다(self, repo):
        repo.save(VideoAggregate.create(VideoUrl("https://youtu.be/eeeeeeeeeee"), "하나"))

        assert FindDuplicateVideosHandler(repo).handle(FindDuplicatesQuery()) == []


class _FakeJob:
    def __init__(self, path, title="영상", url="https://youtu.be/x"):
        self.file_path = path
        self.title = title
        self.url = url
        self.video_id = None


class _FakeDownloads:
    def __init__(self, jobs):
        self._jobs = jobs

    def get_history(self, limit=50, offset=0):
        return self._jobs[offset:offset + limit]


class TestBrokenDownloads:
    def test_사라진_파일만_보고한다(self, tmp_path):
        alive = tmp_path / "alive.mp4"
        alive.write_bytes(b"x")
        repo = _FakeDownloads([
            _FakeJob(str(alive)),
            _FakeJob(str(tmp_path / "gone.mp4"), title="사라진 영상"),
            _FakeJob(""),          # 아직 완료되지 않은 기록은 대상이 아니다
        ])

        broken = FindBrokenDownloadsHandler(repo).handle()

        assert [b.title for b in broken] == ["사라진 영상"]

    def test_전부_멀쩡하면_빈_목록이다(self, tmp_path):
        alive = tmp_path / "ok.mp4"
        alive.write_bytes(b"x")

        assert FindBrokenDownloadsHandler(_FakeDownloads([_FakeJob(str(alive))])).handle() == []
