"""화면이 중계를 쓰는 창구 — `domain.shared.ports.IStreamRelay` 구현.

`gui/`는 인프라를 임포트하지 않으므로, 플레이어는 이 객체를 조립 루트에서 주입받는다.
중계 서버(`get_relay()`)는 **처음 재생할 때** 만들어진다 — 조립 시점에 이 객체를
만들어도 포트를 열지 않는다. 같은 이유로 `relay` 모듈도 쓸 때 임포트한다.
"""

from __future__ import annotations

from collections.abc import Callable


class StreamRelayGateway:
    """앱 전역 중계(`get_relay()`)에 그대로 잇는다."""

    def source(self, url: str, headers: dict[str, str], size: int):
        from infrastructure.streaming.relay import StreamSource  # noqa: PLC0415

        return StreamSource(url=url, headers=headers, size=size)

    def open_session(
        self,
        video,
        audio,
        duration_ms: int,
        ffmpeg: str,
        refresh: Callable | None = None,
    ) -> str:
        from infrastructure.streaming.relay import get_relay  # noqa: PLC0415

        return get_relay().open_session(
            video, audio, duration_ms=duration_ms, ffmpeg=ffmpeg, refresh=refresh
        )

    def close_session(self, play_url: str) -> None:
        from infrastructure.streaming.relay import get_relay  # noqa: PLC0415

        get_relay().close_session(play_url)
