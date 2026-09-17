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

# 라이브러리 정리(`maintenance.py`)와 같은 페이지네이션 규칙을 쓴다.
_PAGE = 50
_MAX_SCAN = 5000


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


@dataclass
class BulkIndexResult:
    """일괄 색인 결과 요약 — 화면이 한 줄로 알리기 위한 최소 정보."""

    indexed: int = 0        # 자막을 찾아 색인한 영상 수
    no_subtitle: int = 0    # 가져올 자막이 없던 영상 수
    skipped: int = 0        # 이미 색인돼 있어 건너뛴 영상 수
    scanned: int = 0        # 실제로 확인한 영상 수(중단 시 전체보다 작다)
    stopped: bool = False   # 사용자가 도중에 그만뒀는가


class BulkIndexSubtitlesHandler:
    """라이브러리 전체를 훑어 자막을 색인한다.

    **영상당 네트워크 왕복이 1초 안팎**이라 수백 건이면 10분을 넘긴다. 그래서
    자동으로 돌지 않고, 진행률과 중단을 반드시 제공한다.

    이미 색인된 영상은 **건너뛴다** — 다시 받아도 같은 자막이고, 중단했다가 다시
    시작했을 때 처음부터 되풀이하면 끝나지 않는다. 다시 받고 싶으면 상세화면
    자막 탭의 ⟳를 쓴다(영상 단위 재색인).
    """

    def __init__(self, video_repo, subtitle_repo: ISubtitleRepository, fetch_handler) -> None:
        self._videos = video_repo
        self._subtitles = subtitle_repo
        self._fetch = fetch_handler

    def handle(
        self,
        on_progress: Callable[[int, int, str], None] | None = None,
        should_stop: Callable[[], bool] | None = None,
        preferred_langs: tuple[str, ...] = ("ko", "en"),
    ) -> BulkIndexResult:
        from domain.library.repositories import SearchQuery  # noqa: PLC0415

        try:
            already = self._subtitles.indexed_video_ids()
        except Exception:
            logger.exception("색인 현황 조회 실패 — 전부 다시 확인한다")
            already = set()

        targets = [v for v in self._scan_videos(SearchQuery) if v[0] not in already]
        result = BulkIndexResult(skipped=len(already))
        total = len(targets)

        for index, (video_id, title, url) in enumerate(targets, start=1):
            if should_stop is not None and should_stop():
                result.stopped = True
                logger.info("자막 일괄 색인 중단: %d/%d", index - 1, total)
                break
            if on_progress is not None:
                on_progress(index, total, title)
            result.scanned += 1
            count = self._fetch.handle(
                FetchAndIndexSubtitlesCommand(
                    video_id=video_id, url=url, preferred_langs=preferred_langs
                )
            )
            if count:
                result.indexed += 1
            else:
                result.no_subtitle += 1

        logger.info(
            "자막 일괄 색인: 색인 %d · 자막없음 %d · 건너뜀 %d (확인 %d건%s)",
            result.indexed, result.no_subtitle, result.skipped, result.scanned,
            ", 중단됨" if result.stopped else "",
        )
        return result

    def _scan_videos(self, search_query_cls) -> list[tuple]:
        """(video_id, 제목, url) 목록. 메모리 규칙대로 50건씩 끊어 읽는다."""
        out: list[tuple] = []
        offset = 0
        while offset < _MAX_SCAN:
            page = self._videos.search(search_query_cls(limit=_PAGE, offset=offset))
            if not page:
                break
            for agg in page:
                video = agg.video
                out.append((agg.id, video.title, str(video.url)))
            if len(page) < _PAGE:
                break
            offset += _PAGE
        return out
