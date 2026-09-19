"""자막 번역 유스케이스 — 진짜 SQLite + 가짜 번역기.

번역기는 네트워크라 가짜로 바꾸고, 대신 **번역기가 말을 안 들을 때** 무엇이 일어나는지를
본다. 그게 이 기능의 위험한 부분이다:

* 묶어 보냈는데 번역기가 줄을 합치거나 나누면 원문과 번역의 짝이 어긋난다 →
  **엉뚱한 시점에 엉뚱한 말**이 뜨는데 틀렸다는 티조차 나지 않는다.
* 번역이 실패한 자리를 비우면 그 시점에 자막이 사라져, 실패인지 원래 말이 없는
  건지 알 수 없다.
* 원본을 덮으면 원문으로 검색할 길이 사라진다.
"""

from __future__ import annotations

import pytest

from application.library.subtitle_commands import (
    TranslateSubtitlesCommand,
    TranslateSubtitlesHandler,
)
from domain.library.subtitle_repository import SubtitleLine
from domain.library.subtitle_translate import translated_lang
from infrastructure.persistence.database import Database
from infrastructure.persistence.sqlite_subtitle_repository import (
    SqliteSubtitleRepository,
)
from uuid import uuid4


@pytest.fixture
def db(tmp_path):
    d = Database(path=tmp_path / "sub.db")
    d.initialize()
    return d


@pytest.fixture
def repo(db):
    return SqliteSubtitleRepository(db)


@pytest.fixture
def video_id(db):
    """자막은 영상에 딸린 데이터라(FK) 영상이 먼저 있어야 한다."""
    from domain.library.aggregates import VideoAggregate
    from domain.library.value_objects import VideoUrl
    from infrastructure.persistence.sqlite_video_repository import (
        SqliteVideoRepository,
    )

    agg = VideoAggregate.create(
        url=VideoUrl(f"https://youtu.be/{uuid4().hex[:11]}"), title="영상"
    )
    SqliteVideoRepository(db).save(agg)
    return agg.id


def _seed(repo, video_id, texts, lang="en"):
    repo.replace_lines(
        video_id, lang, lang,
        [SubtitleLine(i * 1000, i * 1000 + 900, t) for i, t in enumerate(texts)],
    )


class _Translator:
    """줄 수를 지키는 착한 번역기."""

    def __init__(self, detected="en"):
        self.detected = detected
        self.calls: list[list[str]] = []

    def detect_language(self, text):
        return self.detected

    def translate(self, texts, target="ko", source="auto"):
        self.calls.append(list(texts))
        return [
            "\n".join(f"[번역]{ln}" for ln in t.split("\n")) if t else t
            for t in texts
        ]


class _MergingTranslator(_Translator):
    """줄을 합쳐 돌려주는 못된 번역기 — 정렬이 깨지는 경우."""

    def translate(self, texts, target="ko", source="auto"):
        self.calls.append(list(texts))
        out = []
        for t in texts:
            lines = t.split("\n")
            out.append(" ".join(f"[합침]{ln}" for ln in lines) if len(lines) > 1
                       else f"[줄]{t}")
        return out


class TestHappyPath:
    def test_번역본이_별도_언어로_저장된다(self, repo, video_id):
        _seed(repo, video_id, ["hello", "world"])

        n = TranslateSubtitlesHandler(repo, _Translator()).handle(
            TranslateSubtitlesCommand(video_id=video_id)
        )

        assert n == 2
        langs = {i.lang for i in repo.list_indexes(video_id)}
        assert translated_lang("ko") in langs

    def test_원본은_그대로_남는다(self, repo, video_id):
        """원문으로 검색하고 싶을 수도, 번역이 엉망일 수도 있다."""
        _seed(repo, video_id, ["hello"])

        TranslateSubtitlesHandler(repo, _Translator()).handle(
            TranslateSubtitlesCommand(video_id=video_id)
        )

        assert [ln.text for ln in repo.list_lines(video_id, "en")] == ["hello"]

    def test_시각이_보존된다(self, repo, video_id):
        """시각이 밀리면 자막이 엉뚱한 데서 뜬다."""
        _seed(repo, video_id, ["first", "second", "third"])

        TranslateSubtitlesHandler(repo, _Translator()).handle(
            TranslateSubtitlesCommand(video_id=video_id)
        )

        got = repo.list_lines(video_id, translated_lang("ko"))
        assert [ln.start_ms for ln in got] == [0, 1000, 2000]

    def test_묶어_보낸다(self, repo, video_id):
        """한 줄씩 보내면 500줄에 500번 왕복이다."""
        tr = _Translator()
        _seed(repo, video_id, [f"line {i}" for i in range(100)])

        TranslateSubtitlesHandler(repo, tr).handle(
            TranslateSubtitlesCommand(video_id=video_id)
        )

        # 언어 판별 1번 + 묶음 3번(40/40/20) — 100번이 아니다.
        assert len(tr.calls) <= 4


class TestAlignmentFallback:
    def test_줄이_합쳐지면_한_줄씩_다시_한다(self, repo, video_id):
        """억지로 맞추면 엉뚱한 시점에 엉뚱한 말이 뜬다."""
        tr = _MergingTranslator()
        _seed(repo, video_id, ["one", "two", "three"])

        n = TranslateSubtitlesHandler(repo, tr).handle(
            TranslateSubtitlesCommand(video_id=video_id)
        )

        assert n == 3
        got = [ln.text for ln in repo.list_lines(video_id, translated_lang("ko"))]
        assert got == ["[줄]one", "[줄]two", "[줄]three"]   # 줄 단위 결과

    def test_되돌릴_때_줄마다_따로_보낸다(self, repo, video_id):
        tr = _MergingTranslator()
        _seed(repo, video_id, ["one", "two"])

        TranslateSubtitlesHandler(repo, tr).handle(
            TranslateSubtitlesCommand(video_id=video_id)
        )

        assert tr.calls[-1] == ["one", "two"]      # 묶음이 아니라 줄 목록


class TestSkips:
    def test_이미_한국어면_하지_않는다(self, repo, video_id):
        _seed(repo, video_id, ["안녕하세요"], lang="ko")

        n = TranslateSubtitlesHandler(repo, _Translator(detected="ko")).handle(
            TranslateSubtitlesCommand(video_id=video_id)
        )

        assert n == 0
        assert translated_lang("ko") not in {i.lang for i in repo.list_indexes(video_id)}

    def test_원본이_없으면_0(self, repo, video_id):
        assert TranslateSubtitlesHandler(repo, _Translator()).handle(
            TranslateSubtitlesCommand(video_id=video_id)
        ) == 0

    def test_번역기가_없으면_0(self, repo, video_id):
        _seed(repo, video_id, ["hello"])
        assert TranslateSubtitlesHandler(repo, None).handle(
            TranslateSubtitlesCommand(video_id=video_id)
        ) == 0

    def test_번역본은_원본_후보가_아니다(self, repo, video_id):
        """번역본을 또 번역하면 뜻이 뭉개진다."""
        _seed(repo, video_id, ["[번역]hello"], lang=translated_lang("ko"))

        handler = TranslateSubtitlesHandler(repo, _Translator())

        assert handler.source_candidates(video_id) == []

    def test_결과가_원문과_같으면_저장하지_않는다(self, repo, video_id):
        class _NoOp(_Translator):
            def translate(self, texts, target="ko", source="auto"):
                return list(texts)

        _seed(repo, video_id, ["hello"])

        n = TranslateSubtitlesHandler(repo, _NoOp()).handle(
            TranslateSubtitlesCommand(video_id=video_id)
        )

        assert n == 0


class TestFailureIsolation:
    def test_번역기가_터져도_원문을_남긴다(self, repo, video_id):
        class _Boom(_Translator):
            def translate(self, texts, target="ko", source="auto"):
                raise RuntimeError("백엔드 장애")

        _seed(repo, video_id, ["hello"])

        n = TranslateSubtitlesHandler(repo, _Boom()).handle(
            TranslateSubtitlesCommand(video_id=video_id)
        )

        assert n == 0          # 원문과 같으니 저장하지 않는다
        assert [ln.text for ln in repo.list_lines(video_id, "en")] == ["hello"]

    def test_빈_번역_자리는_원문으로_채운다(self, repo, video_id):
        """빈 줄로 두면 그 시점에 자막이 사라진다."""
        class _Partial(_Translator):
            def translate(self, texts, target="ko", source="auto"):
                return ["\n".join(["[번역]one", "", "[번역]three"])]

        _seed(repo, video_id, ["one", "two", "three"])

        TranslateSubtitlesHandler(repo, _Partial()).handle(
            TranslateSubtitlesCommand(video_id=video_id)
        )

        got = [ln.text for ln in repo.list_lines(video_id, translated_lang("ko"))]
        assert got == ["[번역]one", "two", "[번역]three"]


class TestProgressAndStop:
    def test_진행률을_알린다(self, repo, video_id):
        seen: list[float] = []
        _seed(repo, video_id, [f"l{i}" for i in range(100)])

        TranslateSubtitlesHandler(repo, _Translator()).handle(
            TranslateSubtitlesCommand(video_id=video_id), on_progress=seen.append
        )

        assert seen and seen[-1] == pytest.approx(1.0)

    def test_중단하면_그때까지_한_것을_남긴다(self, repo, video_id):
        """80줄을 번역하고 그만뒀는데 전부 버리면 그 시간이 날아간다."""
        _seed(repo, video_id, [f"l{i}" for i in range(100)])
        calls = {"n": 0}

        def stop():
            calls["n"] += 1
            return calls["n"] > 2      # 묶음 두 개만 하고 중단

        n = TranslateSubtitlesHandler(repo, _Translator()).handle(
            TranslateSubtitlesCommand(video_id=video_id), should_stop=stop
        )

        assert n == 100                # 나머지는 원문으로 남는다
        got = [ln.text for ln in repo.list_lines(video_id, translated_lang("ko"))]
        assert got[0].startswith("[번역]")
        assert got[-1] == "l99"        # 손대지 못한 줄은 원문
