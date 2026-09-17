"""자막 색인 유스케이스 — 받아서 저장하고, 저장한 것을 찾는다.

**수집 경로가 두 가지다.**

1. *공짜 경로* — 재생 중 사용자가 자막을 켜면 이미 큐를 받아 온 상태다. 그걸 그대로
   넘기면 네트워크 왕복 없이 색인이 채워진다(`IndexSubtitleCuesHandler`).
2. *명시 경로* — 상세화면에서 "자막 가져오기"를 누르거나 일괄 색인을 돌리면 그때
   받아 온다(`FetchAndIndexSubtitlesHandler`). 영상당 네트워크 왕복이 있어 자동으로
   돌리지 않는다.

자동 수집을 두지 않는 이유는 CLAUDE.md의 대량 임포트 규칙과 같다 — 영상당 수 초가
걸리는 일을 등록 경로에 걸면 수백 건 가져오기가 끝나지 않는다.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from domain.library.subtitle_repository import ISubtitleRepository, SubtitleLine

logger = logging.getLogger(__name__)


@dataclass
class IndexSubtitleCuesCommand:
    """이미 받아 둔 자막 큐를 색인한다. `cues`는 (시작ms, 끝ms, 텍스트) 목록."""

    video_id: UUID
    lang: str
    label: str
    cues: list[tuple[int, int, str]]


@dataclass
class FetchAndIndexSubtitlesCommand:
    """자막을 받아 와 색인한다. 배경 QThread에서만 호출한다(네트워크)."""

    video_id: UUID
    url: str
    preferred_langs: tuple[str, ...] = ()


def _to_lines(cues) -> list[SubtitleLine]:
    """빈 텍스트 줄은 버린다 — 검색에도 화면에도 쓸모가 없다."""
    lines = []
    for start, end, text in cues or []:
        clean = (text or "").strip()
        if clean:
            lines.append(SubtitleLine(int(start), int(end), clean))
    return lines


class IndexSubtitleCuesHandler:
    def __init__(self, repo: ISubtitleRepository) -> None:
        self._repo = repo

    def handle(self, cmd: IndexSubtitleCuesCommand) -> int:
        """색인한 줄 수."""
        lines = _to_lines(cmd.cues)
        if not lines:
            return 0
        self._repo.replace_lines(cmd.video_id, cmd.lang, cmd.label, lines)
        return len(lines)


class FetchAndIndexSubtitlesHandler:
    """자막 트랙을 조회·다운로드해 색인한다.

    `track_lister`/`cue_fetcher`를 주입받는 이유는 이 핸들러가
    `infrastructure/subtitle/`를 직접 import 하면 application → infrastructure 의존이
    생기기 때문이다(DDD 의존 규칙). 조립 루트가 실제 함수를 꽂는다.
    """

    def __init__(
        self,
        repo: ISubtitleRepository,
        track_lister: Callable[[str], list],
        cue_fetcher: Callable[[object], list],
    ) -> None:
        self._repo = repo
        self._list_tracks = track_lister
        self._fetch_cues = cue_fetcher

    def handle(self, cmd: FetchAndIndexSubtitlesCommand) -> int:
        """색인한 줄 수(자막이 없으면 0). **예외를 밖으로 내지 않는다** —
        색인은 부가 기능이라 실패해도 화면이 멈추면 안 된다."""
        try:
            tracks = self._list_tracks(cmd.url) or []
        except Exception:
            logger.exception("자막 트랙 조회 실패: %s", cmd.url)
            return 0
        if not tracks:
            return 0

        track = _pick_track(tracks, cmd.preferred_langs)
        try:
            cues = self._fetch_cues(track) or []
        except Exception:
            logger.exception("자막 내려받기 실패: %s", cmd.url)
            return 0

        lines = _to_lines(cues)
        if not lines:
            return 0
        lang = getattr(track, "lang", "") or ""
        label = getattr(track, "label", "") or lang
        self._repo.replace_lines(cmd.video_id, lang, label, lines)
        return len(lines)


def _pick_track(tracks: list, preferred_langs: tuple[str, ...]):
    """선호 언어 순으로 고르고, 없으면 첫 트랙.

    선호 언어를 두는 이유는 영상 하나에 트랙이 10개 넘게 달리는 일이 흔해서다
    (자동 번역까지 포함된다). 아무거나 고르면 읽지 못하는 언어가 색인된다.
    """
    for want in preferred_langs:
        for track in tracks:
            if (getattr(track, "lang", "") or "").lower().startswith(want.lower()):
                return track
    return tracks[0]
