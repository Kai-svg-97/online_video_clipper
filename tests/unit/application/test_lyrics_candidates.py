"""가사 후보 목록 검색·적용 단위 테스트.

체인 검색(`FetchSongInfoHandler`)이 첫 성공 출처를 곧바로 채택하는 것과 달리,
후보 검색은 **모든 활성 출처**를 훑고 결과를 도착 순서대로 통지해야 한다. 목록에
'조회중…' 행이 영원히 남지 않으려면 미리 알려준 출처 목록과 실제 순회 목록이
정확히 일치해야 하므로, 그 계약도 함께 고정한다.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

from application.song.commands import (
    ApplyLyricsCandidateCommand,
    ApplyLyricsCandidateHandler,
    SearchLyricsCandidatesCommand,
    SearchLyricsCandidatesHandler,
)
from application.song.dtos import LyricsCandidateDTO
from domain.song.aggregates import SongInfoAggregate
from domain.song.ports import LyricsResult
from domain.song.value_objects import LyricsLine


class _StubProvider:
    """``fetch``만 있는 구식 제공자 — 후보 검색은 1건으로 폴백해야 한다."""

    def __init__(self, key: str, result: LyricsResult | None, boom: bool = False) -> None:
        self.key = key
        self._result = result
        self._boom = boom
        self.calls: list[tuple[str, str]] = []

    def fetch(self, artist, title, duration_sec=None):
        self.calls.append((artist, title))
        if self._boom:
            raise RuntimeError("provider down")
        return self._result


class _MultiProvider:
    """``search``로 여러 후보를 돌려주는 제공자(같은 제목·다른 가수)."""

    def __init__(self, key: str, results: list[LyricsResult]) -> None:
        self.key = key
        self._results = results
        self.calls: list[tuple[str, str, int]] = []

    def search(self, artist, title, duration_sec=None, limit=10):
        self.calls.append((artist, title, limit))
        return list(self._results)[:limit] if limit > 0 else list(self._results)


def _video(title="Artist - Song", channel="Chan"):
    return SimpleNamespace(
        video=SimpleNamespace(
            title=title,
            channel=SimpleNamespace(name=channel),
            duration=SimpleNamespace(seconds=200),
        )
    )


def _handler(providers: dict, sources: list[SimpleNamespace], song_agg=None):
    song_repo = MagicMock()
    song_repo.list_lyrics_sources.return_value = sources
    song_repo.get.return_value = song_agg
    video_repo = MagicMock()
    video_repo.get_by_id.return_value = _video()
    return SearchLyricsCandidatesHandler(song_repo, video_repo, lyrics_providers=providers)


def _synced_result():
    return LyricsResult(
        lines=["첫 줄", "둘째 줄"],
        timings=[0, 3000],
        language="ko",
        source_url="http://a",
        artist="가수A",
        title="제목A",
    )


def _plain_result():
    return LyricsResult(
        lines=["", "plain first", "plain second"],
        language="en",
        source_url="http://b",
    )


class TestSourceListing:
    def test_제공자가_없는_출처는_목록에서_빠진다(self):
        """행만 만들어 놓고 영영 채우지 않는 '조회중…'을 막는 계약."""
        h = _handler(
            {"a": _StubProvider("a", _synced_result())},
            [
                SimpleNamespace(provider_key="a", enabled=True, name="A"),
                SimpleNamespace(provider_key="없음", enabled=True, name="B"),
                SimpleNamespace(provider_key="a", enabled=False, name="C(꺼짐)"),
            ],
        )
        assert h.list_source_names() == ["A"]

    def test_출처_조회_실패는_빈_목록으로_격리된다(self):
        song_repo = MagicMock()
        song_repo.list_lyrics_sources.side_effect = RuntimeError("db down")
        h = SearchLyricsCandidatesHandler(song_repo, MagicMock(), lyrics_providers={})
        assert h.list_source_names() == []


class TestSearchCandidates:
    def test_모든_출처를_훑고_결과를_도착순으로_통지한다(self):
        h = _handler(
            {
                "a": _StubProvider("a", _synced_result()),
                "b": _StubProvider("b", None),
                "c": _StubProvider("c", _plain_result()),
            },
            [
                SimpleNamespace(provider_key="a", enabled=True, name="A"),
                SimpleNamespace(provider_key="b", enabled=True, name="B"),
                SimpleNamespace(provider_key="c", enabled=True, name="C"),
            ],
        )
        started: list[str] = []
        results: list[tuple[str, object]] = []
        done: list[tuple[str, int]] = []
        found = h.handle(
            SearchLyricsCandidatesCommand(uuid4()),
            on_start=started.append,
            on_result=lambda name, dto: results.append((name, dto)),
            on_source_done=lambda name, count: done.append((name, count)),
        )

        # 첫 출처에서 멈추지 않는다(체인 검색과의 결정적 차이).
        assert started == ["A", "B", "C"]
        # 후보가 없는 출처는 on_result가 아니라 on_source_done(0)으로 알린다.
        assert [name for name, _ in results] == ["A", "C"]
        assert done == [("A", 1), ("B", 0), ("C", 1)]
        assert [c.source_name for c in found] == ["A", "C"]

    def test_한_출처가_여러_후보를_돌려줄_수_있다(self):
        """같은 제목·다른 가수 — 출처당 1건으로 잘리면 엉뚱한 곡이 걸린다."""
        others = [
            LyricsResult(lines=[f"{name}의 가사"], language="ko", artist=name, title="같은제목")
            for name in ("가수1", "가수2", "가수3")
        ]
        h = _handler(
            {"m": _MultiProvider("m", others)},
            [SimpleNamespace(provider_key="m", enabled=True, name="멀티")],
        )
        results: list[tuple[str, object]] = []
        done: list[tuple[str, int]] = []
        found = h.handle(
            SearchLyricsCandidatesCommand(uuid4()),
            on_result=lambda name, dto: results.append((name, dto)),
            on_source_done=lambda name, count: done.append((name, count)),
        )

        assert [c.artist for c in found] == ["가수1", "가수2", "가수3"]
        assert [name for name, _ in results] == ["멀티"] * 3
        assert done == [("멀티", 3)]

    def test_출처당_상한을_넘겨_전달한다(self):
        provider = _MultiProvider(
            "m", [LyricsResult(lines=["a"], artist=f"가수{i}") for i in range(5)]
        )
        h = _handler(
            {"m": provider},
            [SimpleNamespace(provider_key="m", enabled=True, name="멀티")],
        )
        found = h.handle(SearchLyricsCandidatesCommand(uuid4(), per_source_limit=2))

        assert provider.calls[0][2] == 2
        assert len(found) == 2

    def test_상한_0은_무제한으로_넘어간다(self):
        provider = _MultiProvider(
            "m", [LyricsResult(lines=["a"], artist=f"가수{i}") for i in range(5)]
        )
        h = _handler(
            {"m": provider},
            [SimpleNamespace(provider_key="m", enabled=True, name="멀티")],
        )
        found = h.handle(SearchLyricsCandidatesCommand(uuid4(), per_source_limit=0))

        assert provider.calls[0][2] == 0
        assert len(found) == 5

    def test_후보_필드를_목록_표시용으로_채운다(self):
        h = _handler(
            {"a": _StubProvider("a", _synced_result()), "c": _StubProvider("c", _plain_result())},
            [
                SimpleNamespace(provider_key="a", enabled=True, name="A"),
                SimpleNamespace(provider_key="c", enabled=True, name="C"),
            ],
        )
        synced, plain = h.handle(SearchLyricsCandidatesCommand(uuid4()))

        assert (synced.source_name, synced.artist, synced.title) == ("A", "가수A", "제목A")
        assert synced.first_line == "첫 줄"
        assert synced.is_synced is True
        assert synced.line_count == 2
        # 제공자가 메타데이터를 안 주면 검색 기준값(영상 제목 파싱)으로 채운다.
        assert (plain.artist, plain.title) == ("Artist", "Song")
        assert plain.first_line == "plain first"   # 빈 줄은 건너뛴다
        assert plain.is_synced is False
        assert plain.line_count == 2               # 빈 줄은 세지 않는다

    def test_한_출처가_예외를_던져도_나머지는_계속한다(self):
        h = _handler(
            {"boom": _StubProvider("boom", None, boom=True),
             "ok": _StubProvider("ok", _synced_result())},
            [
                SimpleNamespace(provider_key="boom", enabled=True, name="터짐"),
                SimpleNamespace(provider_key="ok", enabled=True, name="정상"),
            ],
        )
        found = h.handle(SearchLyricsCandidatesCommand(uuid4()))
        assert [c.source_name for c in found] == ["정상"]

    def test_취소되면_남은_출처를_조회하지_않는다(self):
        late = _StubProvider("late", _synced_result())
        h = _handler(
            {"first": _StubProvider("first", _synced_result()), "late": late},
            [
                SimpleNamespace(provider_key="first", enabled=True, name="1"),
                SimpleNamespace(provider_key="late", enabled=True, name="2"),
            ],
        )
        seen: list[str] = []
        h.handle(
            SearchLyricsCandidatesCommand(uuid4()),
            on_start=seen.append,
            should_cancel=lambda: bool(seen),   # 첫 출처를 마치면 취소
        )
        assert seen == ["1"]
        assert late.calls == []

    def test_다중_아티스트는_주_아티스트로_재시도한다(self):
        class _Picky(_StubProvider):
            def fetch(self, artist, title, duration_sec=None):
                self.calls.append((artist, title))
                return _synced_result() if artist == "NIKI" else None

        picky = _Picky("p", None)
        song_repo = MagicMock()
        song_repo.list_lyrics_sources.return_value = [
            SimpleNamespace(provider_key="p", enabled=True, name="P")
        ]
        agg = SongInfoAggregate.create(uuid4(), is_song=True)
        agg.apply_fetched(artist="NIKI, Phil Collins", song_title="곡")
        song_repo.get.return_value = agg
        video_repo = MagicMock()
        video_repo.get_by_id.return_value = _video()

        h = SearchLyricsCandidatesHandler(song_repo, video_repo, lyrics_providers={"p": picky})
        found = h.handle(SearchLyricsCandidatesCommand(uuid4()))

        assert [a for a, _ in picky.calls] == ["NIKI, Phil Collins", "NIKI"]
        assert len(found) == 1


class TestApplyCandidate:
    def _apply(self, candidate, agg=None, translator=None):
        song_repo = MagicMock()
        song_repo.get.return_value = agg
        handler = ApplyLyricsCandidateHandler(song_repo, MagicMock(), translator)
        video_id = agg.id if agg is not None else uuid4()
        out = handler.handle(ApplyLyricsCandidateCommand(video_id, candidate))
        return out, song_repo

    def test_고른_가사와_시각을_그대로_반영한다(self):
        cand = LyricsCandidateDTO(
            source_name="LRCLIB", artist="가수", title="제목",
            lines=("a", "b"), timings=(0, 1500), language="ko", source_url="http://x",
            first_line="a", is_synced=True, line_count=2,
        )
        out, song_repo = self._apply(cand)

        assert out is not None
        info = out.info
        assert [ln.original for ln in info.lyrics_lines] == ["a", "b"]
        assert [ln.start_ms for ln in info.lyrics_lines] == [0, 1500]
        assert info.is_song is True
        assert info.source.name == "LRCLIB"
        song_repo.save.assert_called_once()

    def test_수동편집된_가사도_교체한다(self):
        """사용자가 목록에서 직접 고른 것이므로 수동 가드를 넘어 교체한다."""
        agg = SongInfoAggregate.create(uuid4(), is_song=True)
        agg.edit_lyrics([LyricsLine(original="옛 가사")])
        cand = LyricsCandidateDTO(source_name="새출처", lines=("새 가사",), language="ko")
        out, _ = self._apply(cand, agg=agg)

        assert [ln.original for ln in out.info.lyrics_lines] == ["새 가사"]

    def test_수동편집된_가수는_보존한다(self):
        agg = SongInfoAggregate.create(uuid4(), is_song=True)
        agg.edit_field("artist", "내가 고친 가수")
        cand = LyricsCandidateDTO(
            source_name="S", artist="출처가 준 가수", lines=("x",), language="ko"
        )
        out, _ = self._apply(cand, agg=agg)

        assert out.info.artist == "내가 고친 가수"

    def test_빈_후보는_아무것도_하지_않는다(self):
        out, song_repo = self._apply(LyricsCandidateDTO(source_name="S"))
        assert out is None
        song_repo.save.assert_not_called()
