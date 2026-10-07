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
    """메뉴 이름은 인프라가 만들지 않는다 — `gui/text/labels.py` 로 옮겼다."""

    def test_트랙은_원시_데이터만_싣는다(self):
        track = SubtitleTrackInfo("en", "English", "u", "json3", auto=True)

        assert not hasattr(track, "label")
        assert track.auto is True and track.name == "English"

    def test_자동_생성임을_표시한다(self):
        from gui.text.labels import subtitle_track_label

        track = SubtitleTrackInfo("en", "English", "u", "json3", auto=True)
        assert "자동 생성" in subtitle_track_label(track)

    def test_이름에_한글이_있는지_보지_않는다(self):
        """YouTube 가 준 이름은 사용자 계정 언어를 따라간다 — 믿을 수 없는 판정이었다."""
        from gui.text.labels import subtitle_track_label

        track = SubtitleTrackInfo("ko", "한국어 (자동 생성됨)", "u", "json3", auto=True)
        assert subtitle_track_label(track).count("자동") == 2   # 원본 이름 + 우리 표시

    def test_번역_대상을_표시한다(self):
        from gui.text.labels import subtitle_track_label

        track = translated(SubtitleTrackInfo("en", "English", "u", "json3", True), "ko")
        label = subtitle_track_label(track)
        assert "한국어" in label and "번역" in label

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


# ── 배치 6: 원본(raw) info에서 트랙 뽑기 ─────────────────────────────────
def _raw_info() -> dict:
    """`extract_info(process=False)`가 돌려주는 원본 모양 — 자막은 확장기가 채운 그대로다."""
    return {
        "_type": "video",
        "id": "abc",
        "title": "t",
        "duration": 10,
        "extractor": "youtube",
        "extractor_key": "Youtube",
        "webpage_url": "https://www.youtube.com/watch?v=abc",
        "formats": [
            {"format_id": "18", "url": "https://rr1.googlevideo.com/videoplayback?expire=9999999999&x=1",
             "ext": "mp4", "vcodec": "avc1", "acodec": "mp4a", "height": 360, "protocol": "https"},
            {"format_id": "22", "url": "https://rr1.googlevideo.com/videoplayback?expire=9999999999&x=2",
             "ext": "mp4", "vcodec": "avc1", "acodec": "mp4a", "height": 720, "protocol": "https"},
        ],
        "subtitles": {
            "ko": [_entry(ext="vtt", url="https://x/ko-vtt", name="Korean"),
                   _entry(ext="json3", url="https://x/ko", name="Korean")],
            "de": [_entry(url="https://x/de", name="German")],
        },
        "automatic_captions": {
            "en-en": [_entry(url="https://x/en", name="English")],
            "ko-en": [_entry(url="https://x/en?tlang=ko")],
            "de-de": [_entry(url="https://x/auto-de")],
        },
    }


class TestTracksFromInfo:
    def test_포트_메서드는_list_tracks와_같은_결과를_준다(self):
        from infrastructure.subtitle.gateway import YouTubeSubtitleSource

        info = _raw_info()

        assert YouTubeSubtitleSource().tracks_from_info(info) == list_tracks(info)

    def test_빈_info면_빈_목록(self):
        from infrastructure.subtitle.gateway import YouTubeSubtitleSource

        assert YouTubeSubtitleSource().tracks_from_info({}) == []

    def test_원본에서_뽑은_트랙은_기존_자막_워커_결과와_같다(self, monkeypatch):
        """기존 경로(`fetch_tracks_for_url`)는 yt-dlp가 **처리까지 마친** info를 쓴다.

        캐시는 처리 전 원본을 들고 있으므로, 두 info에서 뽑은 트랙이 달라지면 자막 목록이
        캐시를 탄 순간부터 조용히 바뀐다. 실제 yt-dlp의 `process_ie_result`를 네트워크 없이
        돌려 두 경로를 비교한다.
        """
        import copy

        import yt_dlp

        from infrastructure.subtitle.gateway import YouTubeSubtitleSource
        from infrastructure.subtitle.youtube_subtitles import fetch_tracks_for_url

        raw = _raw_info()
        extract_calls: list = []

        class _OfflineYDL(yt_dlp.YoutubeDL):
            def extract_info(self, url, download=True, *a, **k):
                extract_calls.append(url)
                # 확장기가 돌려준 원본을 yt-dlp가 평소처럼 처리한 결과
                return self.process_ie_result(copy.deepcopy(raw), download=False)

        monkeypatch.setattr(yt_dlp, "YoutubeDL", _OfflineYDL)

        old = fetch_tracks_for_url("https://www.youtube.com/watch?v=abc")
        new = YouTubeSubtitleSource().tracks_from_info(copy.deepcopy(raw))

        assert extract_calls, "기존 경로가 실제로 처리를 거쳤는지 확인한다"
        assert old, "비교 대상이 비면 시험이 공허하다"
        assert new == old
        assert [t.key for t in new] == [t.key for t in old]

    def test_원본_info를_바꾸지_않는다(self):
        import copy

        from infrastructure.subtitle.gateway import YouTubeSubtitleSource

        info = _raw_info()
        before = copy.deepcopy(info)

        YouTubeSubtitleSource().tracks_from_info(info)

        assert info == before, "캐시된 원본을 자막 추출이 오염시키면 안 된다"
