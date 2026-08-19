"""자막 트랙 목록·내려받기 규칙.

가장 중요한 계약은 **자동 자막 목록에서 번역본을 걸러 내는 것**이다. YouTube는
자동 자막 목록에 번역 가능한 모든 언어(수백 개)를 넣어 주는데, 그대로 나열하면
메뉴를 쓸 수 없고 원래 언어가 무엇인지도 알 수 없다.
"""
from __future__ import annotations

from infrastructure.subtitle.youtube_subtitles import (
    SubtitleTrackInfo,
    _with_tlang,
    fetch_cues,
    list_tracks,
    translated,
)


def _entry(ext="json3", url="https://x/caption?v=1", name="") -> dict:
    return {"ext": ext, "url": url, "name": name}


class TestListTracks:
    def test_수동_자막을_먼저_준다(self):
        info = {
            "subtitles": {"ko": [_entry(name="한국어")]},
            "automatic_captions": {"en": [_entry(name="English")]},
        }

        tracks = list_tracks(info)

        assert [t.lang for t in tracks] == ["ko", "en"]
        assert tracks[0].auto is False and tracks[1].auto is True

    def test_같은_언어가_양쪽에_있으면_수동만_남긴다(self):
        info = {
            "subtitles": {"ko": [_entry()]},
            "automatic_captions": {"ko": [_entry()]},
        }

        tracks = list_tracks(info)

        assert len(tracks) == 1 and tracks[0].auto is False

    def test_번역본은_목록에_넣지_않는다(self):
        """이 걸러내기가 없으면 자동 자막 목록이 수백 줄이 된다."""
        info = {
            "automatic_captions": {
                "en": [_entry(url="https://x/c?v=1")],
                "ko": [_entry(url="https://x/c?v=1&tlang=ko")],
                "ja": [_entry(url="https://x/c?v=1&tlang=ja")],
            }
        }

        tracks = list_tracks(info)

        assert [t.lang for t in tracks] == ["en"]

    def test_다룰_수_있는_형식을_고른다(self):
        info = {"subtitles": {"ko": [
            _entry(ext="ttml", url="https://x/a"),
            _entry(ext="json3", url="https://x/b"),
        ]}}

        assert list_tracks(info)[0].ext == "json3"

    def test_자막이_없으면_빈_목록(self):
        assert list_tracks({}) == []

    def test_실제_형태의_자동_자막_키를_줄여_준다(self):
        """실측: 번역이 아닌 자동 자막의 키는 `en-en`처럼 `<대상>-<출처>` 꼴이다.
        그대로 두면 수동 자막 `de`와 다른 언어로 보여 목록에 두 번 뜬다."""
        info = {
            "subtitles": {"de": [_entry(url="https://x/de")],
                          "en": [_entry(url="https://x/en")]},
            "automatic_captions": {
                "de-de": [_entry(url="https://x/auto-de")],
                "en-en": [_entry(url="https://x/auto-en")],
                "ko-en": [_entry(url="https://x/auto?tlang=ko")],
            },
        }

        tracks = list_tracks(info)

        assert [(t.lang, t.auto) for t in tracks] == [("de", False), ("en", False)]


class TestLabels:
    def test_자동_생성임을_표시한다(self):
        track = SubtitleTrackInfo("en", "English", "u", "json3", auto=True)

        assert "자동 생성" in track.label

    def test_번역_대상을_표시한다(self):
        track = translated(SubtitleTrackInfo("en", "English", "u", "json3", True), "ko")

        assert "한국어" in track.label and "번역" in track.label

    def test_원본과_번역본은_다른_트랙으로_구분된다(self):
        base = SubtitleTrackInfo("en", "English", "u", "json3", True)

        assert base.key != translated(base, "ko").key


class TestTlang:
    def test_번역_대상을_쿼리에_붙인다(self):
        assert "tlang=ko" in _with_tlang("https://x/c?v=1", "ko")

    def test_이미_있으면_갈아_끼운다(self):
        out = _with_tlang("https://x/c?v=1&tlang=ja", "ko")

        assert "tlang=ko" in out and "tlang=ja" not in out

    def test_기존_쿼리는_보존한다(self):
        assert "v=1" in _with_tlang("https://x/c?v=1", "ko")


class _FakeResponse:
    def __init__(self, text: str, ok: bool = True) -> None:
        self.text = text
        self._ok = ok

    def raise_for_status(self) -> None:
        if not self._ok:
            raise RuntimeError("404")


class _FakeSession:
    def __init__(self, *responses) -> None:
        self._responses = list(responses)
        self.urls: list[str] = []

    def get(self, url, timeout=None):
        self.urls.append(url)
        return self._responses.pop(0)


_VTT = "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\n본문\n"


class TestFetchCues:
    def test_내려받아_파싱한다(self):
        session = _FakeSession(_FakeResponse(_VTT))
        track = SubtitleTrackInfo("ko", "한국어", "https://x/c", "vtt", False)

        assert fetch_cues(track, session=session) == [(1000, 2000, "본문")]

    def test_번역본을_먼저_시도한다(self):
        session = _FakeSession(_FakeResponse(_VTT))
        track = translated(SubtitleTrackInfo("en", "en", "https://x/c", "vtt", True), "ko")

        fetch_cues(track, session=session)

        assert "tlang=ko" in session.urls[0]

    def test_번역이_실패하면_원본으로_돌아간다(self):
        """번역을 못 받았다고 자막 자체를 잃을 이유는 없다."""
        session = _FakeSession(_FakeResponse("", ok=False), _FakeResponse(_VTT))
        track = translated(SubtitleTrackInfo("en", "en", "https://x/c", "vtt", True), "ko")

        cues = fetch_cues(track, session=session)

        assert cues == [(1000, 2000, "본문")]
        assert len(session.urls) == 2

    def test_모두_실패하면_빈_목록(self):
        session = _FakeSession(_FakeResponse("", ok=False))
        track = SubtitleTrackInfo("ko", "한국어", "https://x/c", "vtt", False)

        assert fetch_cues(track, session=session) == []
