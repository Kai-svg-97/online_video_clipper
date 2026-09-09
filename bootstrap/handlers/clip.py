"""클립 추출 유스케이스 조립."""

from __future__ import annotations

from application.clip.commands import DeleteClipHandler, ExtractClipHandler
from application.clip.queries import GetClipsHandler

from bootstrap.context import ClipHandlers, Repositories, Services


def build(repos: Repositories, services: Services) -> ClipHandlers:
    return ClipHandlers(
        extract=ExtractClipHandler(repos.clip, services.clip_extractor, services.event_bus),
        delete=DeleteClipHandler(repos.clip, services.event_bus),
        get_clips=GetClipsHandler(repos.clip),
    )
