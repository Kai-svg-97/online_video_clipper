"""URL 묶음 → (제목, 썸네일) 일괄 조회 — `GetVideoBriefsByUrlsHandler` (성능 배치 4, A3-b).

회귀 배경: 다운로드 화면이 이력 카드마다 `find_title_by_url`/`find_thumbnail_by_url`을
불러 URL마다 `GetVideoIdByUrl` + `GetVideoDetail`(연결 6개)을 탔다(50행 → 연결 수백 회).
이제 URL 묶음을 **한 번의 연결**로 읽는다.

핸들러는 원값을 준다. 빈 제목을 라이브러리 제목으로 바꿀지·썸네일 파일이 있는지는
화면(VM)이 정한다(`test_real_graph_panels.py::TestDownloadRefreshConnections`).
"""
from __future__ import annotations

from contextlib import contextmanager

import pytest

from domain.library.aggregates import VideoAggregate
from domain.library.value_objects import VideoUrl
from infrastructure.persistence.database import Database
from infrastructure.persistence.sqlite_video_repository import SqliteVideoRepository


@pytest.fixture
def db(tmp_path):
    d = Database(path=tmp_path / "briefs.db")
    d.initialize()
    return d


@pytest.fixture
def repo(db):
    return SqliteVideoRepository(db)


@pytest.fixture
def handler(repo):
    from application.library.queries import GetVideoBriefsByUrlsHandler  # noqa: PLC0415

    return GetVideoBriefsByUrlsHandler(repo)


@pytest.fixture
def connections(monkeypatch):
    """`Database.connection` 진입 수를 센다(저장소들이 인스턴스 메서드로 부르는 지점)."""
    calls: list[int] = []
    original = Database.connection

    @contextmanager
    def counting(self):
        calls.append(1)
        with original(self) as conn:
            yield conn

    monkeypatch.setattr(Database, "connection", counting)
    return calls


def _add(repo, url: str, title: str, thumb: str | None = None) -> VideoAggregate:
    agg = VideoAggregate.create(VideoUrl(url), title)
    if thumb:
        agg.update_metadata(thumbnail_path=thumb)
    repo.save(agg)
    return agg


class TestGetVideoBriefsByUrls:
    @pytest.fixture
    def three(self, repo):
        a = _add(repo, "https://www.youtube.com/watch?v=aaaaaaaaaaa", "가", "a.jpg")
        b = _add(repo, "https://www.youtube.com/watch?v=bbbbbbbbbbb", "", None)
        c = _add(repo, "https://www.youtube.com/watch?v=ccccccccccc", "다", "c.jpg")
        return a, b, c

    def test_찾은_URL만_키로_돌려준다(self, handler, three):
        a, b, c = three
        result = handler.handle(
            [str(a.video.url), str(b.video.url), str(c.video.url),
             "https://youtu.be/missing0000"]
        )

        assert set(result) == {str(a.video.url), str(b.video.url), str(c.video.url)}
        assert "https://youtu.be/missing0000" not in result

    def test_제목과_썸네일_원값을_준다(self, handler, three):
        a, b, c = three
        result = handler.handle([str(a.video.url), str(b.video.url), str(c.video.url)])

        assert (result[str(a.video.url)].title, result[str(a.video.url)].thumbnail_path) == ("가", "a.jpg")
        # 빈 제목은 그대로 — 대체는 화면이 한다. 썸네일이 없으면 빈 문자열이 아니라 None.
        assert result[str(b.video.url)].title == ""
        assert result[str(b.video.url)].thumbnail_path is None
        assert (result[str(c.video.url)].title, result[str(c.video.url)].thumbnail_path) == ("다", "c.jpg")

    def test_중복_URL은_한_키로_합친다(self, handler, three):
        a, _b, c = three
        result = handler.handle([str(a.video.url), str(a.video.url), str(c.video.url)])

        assert set(result) == {str(a.video.url), str(c.video.url)}

    def test_빈_목록은_연결을_열지_않는다(self, handler, connections):
        assert handler.handle([]) == {}
        assert len(connections) == 0

    def test_여러_URL도_연결은_정확히_하나다(self, handler, three, connections):
        a, b, c = three
        result = handler.handle([str(a.video.url), str(b.video.url), str(c.video.url)])

        assert len(result) == 3          # 0 이 아님 — 기능이 죽어도 통과하는 단언 방지
        assert len(connections) == 1

    def test_청크_경계를_넘어도_연결은_하나다(self, repo, handler, connections):
        """`IN` 청크(400)를 넘는 401개 + 없는 1개. 청크는 한 연결 안에서 처리한다."""
        urls = [f"https://www.youtube.com/watch?v=v{i:010d}" for i in range(401)]
        for i, u in enumerate(urls):
            _add(repo, u, f"제목 {i}")
        connections.clear()              # 저장 때 센 연결은 버린다

        result = handler.handle(urls + ["https://www.youtube.com/watch?v=nothere0000"])

        assert len(result) == 401
        assert result[urls[0]].title == "제목 0"
        assert result[urls[400]].title == "제목 400"
        assert len(connections) == 1

    def test_표기만_다른_URL도_단건_조회와_같이_찾는다(self, repo, handler):
        """`GetVideoIdByUrlHandler`(→ `get_by_url`)가 같은 영상으로 보는 쌍은 일괄도 찾는다.

        결과의 키는 **호출자가 넘긴 URL 그대로**다 — 화면이 job.url 로 조회하기 때문이다.
        """
        from application.library.queries import GetVideoIdByUrlHandler  # noqa: PLC0415

        agg = _add(repo, "https://www.youtube.com/watch?v=norm0000001", "정규화")
        short = "https://youtu.be/norm0000001"

        # 전제: 단건 경로는 이 쌍을 같은 영상으로 본다.
        assert GetVideoIdByUrlHandler(repo).handle(short) == agg.id

        result = handler.handle([short])

        assert short in result
        assert result[short].title == "정규화"
