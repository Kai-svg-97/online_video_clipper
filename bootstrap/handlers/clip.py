"""클립 추출 유스케이스 조립.

`get_chapters`는 클립이 아니라 **영상 설명**을 읽으므로 라이브러리 저장소를 쓴다
(챕터는 설명 속 타임스탬프에서 나온다).
"""

from __future__ import annotations

from application.clip.commands import (
    DeleteClipHandler,
    ExtractClipHandler,
    ExtractClipsHandler,
)
from application.clip.queries import GetChaptersHandler, GetClipsHandler
from application.clip.sponsor_queries import GetSkipSegmentsHandler

from bootstrap.context import ClipHandlers, Repositories, Services


def build(repos: Repositories, services: Services) -> ClipHandlers:
    extract = ExtractClipHandler(repos.clip, services.clip_extractor, services.event_bus)
    return ClipHandlers(
        extract=extract,
        extract_many=ExtractClipsHandler(extract),
        delete=DeleteClipHandler(repos.clip, services.event_bus),
        get_clips=GetClipsHandler(repos.clip),
        get_chapters=GetChaptersHandler(repos.video),
        get_skip_segments=GetSkipSegmentsHandler(services.skip_source),
    )
