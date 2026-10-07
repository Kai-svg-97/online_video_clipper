"""화면이 영상 자막 트랙을 쓰는 창구 — `domain.shared.ports.IVideoSubtitleSource` 구현.

`gui/`는 인프라를 임포트하지 않으므로, 플레이어는 이 객체를 조립 루트에서 주입받는다.
실제 일은 `youtube_subtitles` 모듈 함수가 한다(네트워크 — QThread에서만 부른다).
그 모듈은 쓸 때 임포트한다 — 예전에도 플레이어가 함수 안에서 불러왔다(시작 성능).
"""

from __future__ import annotations


class YouTubeSubtitleSource:
    """`youtube_subtitles` 모듈 함수에 그대로 잇는다."""

    def list_tracks(self, url: str, cookie_opts: dict | None = None) -> list:
        from infrastructure.subtitle.youtube_subtitles import (  # noqa: PLC0415
            fetch_tracks_for_url,
        )

        return fetch_tracks_for_url(url, cookie_opts)

    def tracks_from_info(self, info: dict) -> list:
        from infrastructure.subtitle.youtube_subtitles import list_tracks  # noqa: PLC0415

        return list_tracks(info or {})

    def fetch_cues(self, track) -> list:
        from infrastructure.subtitle.youtube_subtitles import fetch_cues  # noqa: PLC0415

        return fetch_cues(track)

    def translated(self, track, target_lang: str):
        from infrastructure.subtitle.youtube_subtitles import translated  # noqa: PLC0415

        return translated(track, target_lang)

    def translate_targets(self) -> tuple[tuple[str, str], ...]:
        from infrastructure.subtitle.youtube_subtitles import (  # noqa: PLC0415
            TRANSLATE_TARGETS,
        )

        return TRANSLATE_TARGETS
