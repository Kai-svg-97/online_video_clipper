"""YouTube API 채널/영상 메타데이터 배치 조회 — 왕복 수 감소 검증.

channels.list·videos.list는 한 번에 최대 50개 id까지 받으므로, 어댑터가 N개를
ceil(N/50)회로 묶어 호출하는지 확인한다(네트워크 없이 가짜 세션으로 검증).
GetSubscribedChannelInfosHandler가 채널마다 개별 호출하지 않고 이 배치 메서드
(``list_channels``) 한 번만 호출하는지도 함께 고정한다 — 예전에는 이 회귀를
잡을 테스트가 전혀 없었다.
"""
from __future__ import annotations

from application.library.playlist_queries import (
    GetSubscribedChannelInfosHandler,
    GetSubscribedChannelInfosQuery,
)
from infrastructure.youtube.youtube_api_adapter import YouTubeApiAdapter


class _FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return self._payload


class _FakeSession:
    """실제 HTTP 없이 요청을 기록하고, id 목록 크기만큼 가짜 항목을 돌려준다."""

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.headers: dict = {}

    def get(self, url, headers=None, params=None, timeout=None):
        params = dict(params or {})
        self.calls.append({"url": url, "params": params})
        ids = [i for i in params.get("id", "").split(",") if i]
        resource = url.rsplit("/", 1)[-1]
        if resource == "channels":
            items = [
                {
                    "id": cid,
                    "snippet": {"title": f"채널{cid}", "thumbnails": {}},
                    "statistics": {"subscriberCount": "10", "videoCount": "5"},
                    # relatedPlaylists를 비워 get_latest_upload_dates가 추가로
                    # playlistItems를 호출하지 않게 한다(이 테스트의 관심사가 아님).
                    "contentDetails": {},
                }
                for cid in ids
            ]
        elif resource == "videos":
            items = [
                {
                    "id": vid,
                    "snippet": {
                        "channelId": "UCx",
                        "channelTitle": "채널",
                        "publishedAt": "2024-01-01T00:00:00Z",
                    },
                    "statistics": {"viewCount": "1"},
                    "contentDetails": {"duration": "PT1M"},
                }
                for vid in ids
            ]
        else:
            items = []
        return _FakeResponse({"items": items})


class _FakeCreds:
    valid = True
    token = "fake-token"  # noqa: S105


def _make_adapter() -> tuple[YouTubeApiAdapter, _FakeSession]:
    adapter = YouTubeApiAdapter(_FakeCreds())
    session = _FakeSession()
    adapter._session = session  # _get_session()이 None일 때만 새로 만드므로 직접 주입
    return adapter, session


def _batch_sizes(session: _FakeSession) -> list[int]:
    return [len(c["params"]["id"].split(",")) for c in session.calls]


class TestListChannelsBatching:
    def test_batches_by_50(self) -> None:
        adapter, session = _make_adapter()
        ids = [f"UC{i:03d}" for i in range(120)]

        result = adapter.list_channels(ids)

        assert len(session.calls) == 3  # ceil(120/50)
        assert _batch_sizes(session) == [50, 50, 20]
        assert len(result) == 120
        assert result["UC000"]["title"] == "채널UC000"

    def test_exact_multiple_of_50_does_not_add_empty_batch(self) -> None:
        adapter, session = _make_adapter()
        ids = [f"UC{i:03d}" for i in range(100)]

        adapter.list_channels(ids)

        assert len(session.calls) == 2
        assert _batch_sizes(session) == [50, 50]

    def test_small_list_uses_single_call(self) -> None:
        adapter, session = _make_adapter()
        adapter.list_channels(["UC1", "UC2", "UC3"])

        assert len(session.calls) == 1
        assert _batch_sizes(session) == [3]


class TestGetVideosChannelsBatching:
    def test_batches_by_50(self) -> None:
        adapter, session = _make_adapter()
        vids = [f"v{i:03d}" for i in range(120)]

        result = adapter.get_videos_channels(vids)

        assert len(session.calls) == 3  # ceil(120/50)
        assert _batch_sizes(session) == [50, 50, 20]
        assert len(result) == 120


class TestGetSubscribedChannelInfosHandlerBatching:
    """구독 채널 카드 정보 조회 — 채널 수와 무관하게 channels.list는 배치로 묶여야 한다."""

    def test_does_not_call_channels_api_per_channel(self) -> None:
        adapter, session = _make_adapter()
        channels = [
            (f"UC{i:03d}", f"채널{i}", f"https://youtube.com/channel/UC{i:03d}")
            for i in range(75)
        ]

        handler = GetSubscribedChannelInfosHandler(yt_api=adapter)
        result = handler.handle(GetSubscribedChannelInfosQuery(channels=channels))

        channels_calls = [c for c in session.calls if c["url"].endswith("/channels")]
        assert len(channels_calls) == 2  # ceil(75/50) — 75회가 아님
        assert len(result) == 75
