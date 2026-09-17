"""자막 색인 수집 유스케이스.

수집은 **실패해도 화면을 멈추면 안 되는** 부가 기능이라, 트랙 조회·다운로드 어느
쪽이 터져도 0을 돌려주고 끝나야 한다. 그리고 영상 하나에 트랙이 10개 넘게 달리는
일이 흔해서(자동 번역 포함) **어느 트랙을 고르는지**가 결과를 좌우한다.
"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from application.library.subtitle_commands import (
    FetchAndIndexSubtitlesCommand,
    FetchAndIndexSubtitlesHandler,
    IndexSubtitleCuesCommand,
    IndexSubtitleCuesHandler,
    _pick_track,
)


class _Repo:
    def __init__(self):
        self.saved: list[tuple] = []

    def replace_lines(self, video_id, lang, label, lines):
        self.saved.append((video_id, lang, label, [ln.text for ln in lines]))


def _track(lang, label=""):
    return SimpleNamespace(lang=lang, label=label or lang)


class TestIndexCues:
    def test_큐를_그대로_저장한다(self):
        repo = _Repo()
        vid = uuid4()
        count = IndexSubtitleCuesHandler(repo).handle(
            IndexSubtitleCuesCommand(vid, "ko", "한국어", [(0, 1000, "첫"), (1000, 2000, "둘")])
        )
        assert count == 2
        assert repo.saved == [(vid, "ko", "한국어", ["첫", "둘"])]

    def test_빈_텍스트_줄은_버린다(self):
        """검색에도 화면에도 쓸모가 없다 — 자동 자막에 흔히 섞여 온다."""
        repo = _Repo()
        count = IndexSubtitleCuesHandler(repo).handle(
            IndexSubtitleCuesCommand(uuid4(), "ko", "", [(0, 1, "  "), (1, 2, "있다")])
        )
        assert count == 1
        assert repo.saved[0][3] == ["있다"]

    def test_전부_비면_저장하지_않는다(self):
        repo = _Repo()
        assert IndexSubtitleCuesHandler(repo).handle(
            IndexSubtitleCuesCommand(uuid4(), "ko", "", [(0, 1, "")])
        ) == 0
        assert repo.saved == []


class TestFetchAndIndex:
    def _handler(self, repo, tracks, cues, **kw):
        return FetchAndIndexSubtitlesHandler(
            repo,
            track_lister=kw.get("lister", lambda url: tracks),
            cue_fetcher=kw.get("fetcher", lambda t: cues),
        )

    def test_받아서_저장한다(self):
        repo = _Repo()
        vid = uuid4()
        count = self._handler(repo, [_track("ko", "한국어")], [(0, 1000, "안녕")]).handle(
            FetchAndIndexSubtitlesCommand(vid, "https://y/1")
        )
        assert count == 1
        assert repo.saved == [(vid, "ko", "한국어", ["안녕"])]

    def test_트랙이_없으면_0(self):
        repo = _Repo()
        assert self._handler(repo, [], []).handle(
            FetchAndIndexSubtitlesCommand(uuid4(), "https://y/1")
        ) == 0
        assert repo.saved == []

    def test_큐가_비면_저장하지_않는다(self):
        repo = _Repo()
        assert self._handler(repo, [_track("ko")], []).handle(
            FetchAndIndexSubtitlesCommand(uuid4(), "https://y/1")
        ) == 0
        assert repo.saved == []

    def test_트랙_조회가_터져도_0을_돌려준다(self):
        def boom(_url):
            raise RuntimeError("네트워크 끊김")

        repo = _Repo()
        assert self._handler(repo, [], [], lister=boom).handle(
            FetchAndIndexSubtitlesCommand(uuid4(), "https://y/1")
        ) == 0

    def test_내려받기가_터져도_0을_돌려준다(self):
        def boom(_t):
            raise RuntimeError("403")

        repo = _Repo()
        assert self._handler(repo, [_track("ko")], [], fetcher=boom).handle(
            FetchAndIndexSubtitlesCommand(uuid4(), "https://y/1")
        ) == 0

    def test_선호_언어_트랙을_고른다(self):
        repo = _Repo()
        tracks = [_track("ja"), _track("ko"), _track("en")]
        self._handler(repo, tracks, [(0, 1, "x")]).handle(
            FetchAndIndexSubtitlesCommand(uuid4(), "https://y/1", preferred_langs=("ko",))
        )
        assert repo.saved[0][1] == "ko"


class TestPickTrack:
    def test_선호_언어_순서를_지킨다(self):
        tracks = [_track("en"), _track("ko")]
        assert _pick_track(tracks, ("ko", "en")).lang == "ko"

    def test_지역_변형도_받는다(self):
        """'en'을 원하면 'en-US'도 맞는 것으로 본다."""
        assert _pick_track([_track("en-US")], ("en",)).lang == "en-US"

    def test_선호_언어가_없으면_첫_트랙(self):
        assert _pick_track([_track("ja"), _track("de")], ("ko",)).lang == "ja"

    def test_선호를_주지_않으면_첫_트랙(self):
        assert _pick_track([_track("ja")], ()).lang == "ja"
