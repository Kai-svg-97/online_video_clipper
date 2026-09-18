"""전사 → 자막 색인 유스케이스.

**만든 자막을 기존 색인에 넣는 것**이 이 기능의 핵심이다 — 그래야 이미 만들어 둔
검색·시점 점프가 그대로 동작한다. 단, YouTube 자막과 **언어 키가 겹치면 안 된다**:
겹치면 나중에 받은 YouTube 자막이 전사 결과를 통째로 덮어쓴다.
"""

from __future__ import annotations

from uuid import uuid4

from application.library.subtitle_commands import (
    TranscribeVideoCommand,
    TranscribeVideoHandler,
)


class _Repo:
    def __init__(self):
        self.saved: list[tuple] = []

    def replace_lines(self, video_id, lang, label, lines):
        self.saved.append((video_id, lang, label, [ln.text for ln in lines]))


class _Transcriber:
    def __init__(self, cues=None, raises=None):
        self.calls: list[tuple] = []
        self._cues = cues if cues is not None else [(0, 1000, "안녕"), (1000, 2000, "하세요")]
        self._raises = raises

    def transcribe(self, media_path, model_key, language=None,
                   on_progress=None, should_stop=None):
        self.calls.append((media_path, model_key, language))
        if self._raises:
            raise self._raises
        if on_progress:
            on_progress(0.5)
        return self._cues


def _handle(repo, transcriber, **kw):
    cmd = TranscribeVideoCommand(
        video_id=kw.pop("video_id", uuid4()),
        media_path=kw.pop("media_path", "C:/m/영상.mp4"),
        **kw,
    )
    return TranscribeVideoHandler(repo, transcriber).handle(cmd)


class TestIndexing:
    def test_전사_결과를_색인에_넣는다(self):
        repo, tr = _Repo(), _Transcriber()
        count = _handle(repo, tr)
        assert count == 2
        assert repo.saved[0][3] == ["안녕", "하세요"]

    def test_YouTube_자막과_다른_언어키를_쓴다(self):
        """같은 키면 YouTube 자막을 다시 받을 때 전사 결과가 사라진다."""
        repo, tr = _Repo(), _Transcriber()
        _handle(repo, tr, language="ko")
        lang = repo.saved[0][1]
        assert lang.startswith(TranscribeVideoHandler.LANG_PREFIX)
        assert lang != "ko"

    def test_언어를_주지_않으면_auto로_남긴다(self):
        repo, tr = _Repo(), _Transcriber()
        _handle(repo, tr)
        assert repo.saved[0][1].endswith("auto")

    def test_라벨에_모델_이름이_들어간다(self):
        """어떤 모델로 만든 자막인지 화면에서 구분할 수 있어야 한다."""
        repo, tr = _Repo(), _Transcriber()
        _handle(repo, tr, model_key="tiny")
        assert "음성 인식" in repo.saved[0][2]

    def test_모르는_모델_키는_기본값으로_돈다(self):
        repo, tr = _Repo(), _Transcriber()
        assert _handle(repo, tr, model_key="없는모델") == 2
        assert tr.calls[0][1] == "base"


class TestEmptyAndFailure:
    def test_결과가_없으면_저장하지_않는다(self):
        repo, tr = _Repo(), _Transcriber(cues=[])
        assert _handle(repo, tr) == 0
        assert repo.saved == []

    def test_빈_텍스트만_나오면_저장하지_않는다(self):
        repo, tr = _Repo(), _Transcriber(cues=[(0, 1000, "   ")])
        assert _handle(repo, tr) == 0
        assert repo.saved == []

    def test_전사가_터져도_예외를_내지_않는다(self):
        """전사는 부가 기능이다 — 실패해도 화면이 멈추면 안 된다."""
        repo, tr = _Repo(), _Transcriber(raises=RuntimeError("모델 로드 실패"))
        assert _handle(repo, tr) == 0
        assert repo.saved == []


class TestCallbacks:
    def test_진행률이_전달된다(self):
        repo, tr = _Repo(), _Transcriber()
        seen: list[float] = []
        cmd = TranscribeVideoCommand(video_id=uuid4(), media_path="C:/m/a.mp4")
        TranscribeVideoHandler(repo, tr).handle(cmd, on_progress=seen.append)
        assert seen == [0.5]

    def test_중단_콜백이_전사기로_넘어간다(self):
        repo = _Repo()
        received = {}

        class _T(_Transcriber):
            def transcribe(self, media_path, model_key, language=None,
                           on_progress=None, should_stop=None):
                received["stop"] = should_stop
                return []

        cmd = TranscribeVideoCommand(video_id=uuid4(), media_path="C:/m/a.mp4")
        stop = lambda: True          # noqa: E731
        TranscribeVideoHandler(repo, _T()).handle(cmd, should_stop=stop)
        assert received["stop"] is stop
