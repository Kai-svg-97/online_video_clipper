from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable
from uuid import UUID

from application.library.commands import AddVideoCommand, AddVideoHandler
from application.library.dtos import PlaylistDTO, PlaylistFolderDTO
from domain.library.entities import Playlist, PlaylistFolder
from domain.library.repositories import (
    IPlaylistFolderRepository,
    IPlaylistRepository,
    IVideoRepository,
)
from domain.shared.ports import IMediaSource

logger = logging.getLogger(__name__)


def _resolve_yt_api(yt_api, yt_api_provider: "Callable[[], object | None] | None"):
    """저장된 yt_api가 있으면 그대로, 없으면 provider로 지연 해석한다.

    composition root(main.py)가 시작 시 keyring에 접근하지 않도록 provider(예:
    ``_get_youtube_api``)를 대신 넘기면, 실제로 이 핸들러가 호출되는 시점에만
    YouTube 인증이 이뤄진다(lazy binding). yt_api를 직접 넘기는 기존 호출부·
    테스트는 그대로 동작한다.
    """
    if yt_api is not None:
        return yt_api
    if yt_api_provider is not None:
        return yt_api_provider()
    return None


# ── Command 데이터클래스 ─────────────────────────────────────────────────────

@dataclass
class CreatePlaylistCommand:
    title: str
    source: str = "local"
    folder_id: UUID | None = None


@dataclass
class DeletePlaylistCommand:
    playlist_id: UUID


@dataclass
class RenamePlaylistCommand:
    playlist_id: UUID
    new_title: str


@dataclass
class AddVideoToPlaylistCommand:
    playlist_id: UUID
    video_id: UUID
    position: int | None = None   # None = 맨 끝에 추가


@dataclass
class RemoveVideoFromPlaylistCommand:
    playlist_id: UUID
    video_id: UUID


@dataclass
class ReorderPlaylistCommand:
    playlist_id: UUID
    ordered_video_ids: list[UUID]  # 새 순서 전체


@dataclass
class ImportYouTubePlaylistCommand:
    yt_playlist_id: str
    cookie_opts: dict | None = None
    on_progress: Callable[[int, int], None] | None = None  # (current, total)


# ── 핸들러 ──────────────────────────────────────────────────────────────────

class CreatePlaylistHandler:
    def __init__(self, playlist_repo: IPlaylistRepository) -> None:
        self._repo = playlist_repo

    def handle(self, cmd: CreatePlaylistCommand) -> PlaylistDTO:
        pl = Playlist.create(title=cmd.title, source=cmd.source, folder_id=cmd.folder_id)
        self._repo.save(pl)
        return PlaylistDTO(
            id=pl.id,
            title=pl.title,
            yt_playlist_id=pl.yt_playlist_id,
            source=pl.source,
            item_count=pl.item_count,
            folder_id=pl.folder_id,
        )


class DeletePlaylistHandler:
    def __init__(self, playlist_repo: IPlaylistRepository) -> None:
        self._repo = playlist_repo

    def handle(self, cmd: DeletePlaylistCommand) -> None:
        self._repo.delete(cmd.playlist_id)


class RenamePlaylistHandler:
    def __init__(
        self,
        playlist_repo: IPlaylistRepository,
        yt_api=None,
        yt_api_provider: "Callable[[], object | None] | None" = None,
    ) -> None:
        self._repo = playlist_repo
        self._yt = yt_api  # YouTubeApiAdapter | None
        self._yt_api_provider = yt_api_provider

    def handle(self, cmd: RenamePlaylistCommand) -> None:
        pl = self._repo.get_by_id(cmd.playlist_id)
        if pl is None:
            return
        pl.title = cmd.new_title
        pl.updated_at = datetime.now(timezone.utc)
        self._repo.save(pl)
        yt = _resolve_yt_api(self._yt, self._yt_api_provider)
        if yt is not None and getattr(pl, "yt_playlist_id", None):
            try:
                yt.update_playlist_title(pl.yt_playlist_id, cmd.new_title)
            except Exception:
                logger.exception("재생목록 제목 API 동기화 실패")  # 로컬은 이미 갱신됨; 온라인 실패는 무시


class AddVideoToPlaylistHandler:
    """재생목록에 영상 추가. YouTube 재생목록이면 API에도 반영한다."""

    def __init__(
        self,
        playlist_repo: IPlaylistRepository,
        video_repo: IVideoRepository | None = None,
        yt_adapter=None,   # YouTubeApiAdapter | None
        yt_api_provider: "Callable[[], object | None] | None" = None,
    ) -> None:
        self._repo = playlist_repo
        self._video_repo = video_repo
        self._yt = yt_adapter
        self._yt_api_provider = yt_api_provider

    def handle(self, cmd: AddVideoToPlaylistCommand) -> None:
        self._repo.add_video(cmd.playlist_id, cmd.video_id, cmd.position)
        # YouTube 재생목록이면 API 동기화
        yt = _resolve_yt_api(self._yt, self._yt_api_provider)
        if yt is None or self._video_repo is None:
            return
        pl = self._repo.get_by_id(cmd.playlist_id)
        if pl is None or pl.source != "youtube" or not pl.yt_playlist_id:
            return
        agg = self._video_repo.get_by_id(cmd.video_id)
        if agg is None:
            return
        from domain.library.value_objects import extract_youtube_video_id as _extract_yt_video_id  # noqa: PLC0415
        yt_vid_id = _extract_yt_video_id(agg.video.url)
        if not yt_vid_id:
            return
        try:
            yt_item_id = yt.add_video(pl.yt_playlist_id, yt_vid_id)
            self._repo.set_yt_item_id(cmd.playlist_id, cmd.video_id, yt_item_id)
        except Exception:
            logger.exception("재생목록 영상 추가 API 동기화 실패")  # API 실패 시 로컬 DB만 업데이트


class RemoveVideoFromPlaylistHandler:
    """재생목록에서 영상 제거. YouTube 재생목록이면 API에도 반영한다."""

    def __init__(
        self,
        playlist_repo: IPlaylistRepository,
        yt_adapter=None,   # YouTubeApiAdapter | None
        yt_api_provider: "Callable[[], object | None] | None" = None,
    ) -> None:
        self._repo = playlist_repo
        self._yt = yt_adapter
        self._yt_api_provider = yt_api_provider

    def handle(self, cmd: RemoveVideoFromPlaylistCommand) -> None:
        # YouTube API 삭제 먼저 (item_id가 필요하므로 DB 삭제 전에)
        yt = _resolve_yt_api(self._yt, self._yt_api_provider)
        if yt is not None:
            pl = self._repo.get_by_id(cmd.playlist_id)
            if pl is not None and pl.source == "youtube":
                yt_item_id = self._repo.get_yt_item_id(cmd.playlist_id, cmd.video_id)
                if yt_item_id:
                    yt.remove_video(yt_item_id)  # 실패 시 예외 전파 (호출자에서 처리)
        self._repo.remove_video(cmd.playlist_id, cmd.video_id)


class ReorderPlaylistHandler:
    """재생목록 영상 순서 변경. YouTube 재생목록이면 API에도 반영한다."""

    def __init__(
        self,
        playlist_repo: IPlaylistRepository,
        video_repo: IVideoRepository | None = None,
        yt_api=None,   # YouTubeApiAdapter | None
        yt_api_provider: "Callable[[], object | None] | None" = None,
    ) -> None:
        self._repo = playlist_repo
        self._video_repo = video_repo
        self._yt_api = yt_api
        self._yt_api_provider = yt_api_provider

    def handle(self, cmd: ReorderPlaylistCommand) -> None:
        self._repo.set_items(cmd.playlist_id, cmd.ordered_video_ids)

        yt_api = _resolve_yt_api(self._yt_api, self._yt_api_provider)
        if yt_api is None or self._video_repo is None:
            return
        pl = self._repo.get_by_id(cmd.playlist_id)
        if pl is None or pl.source != "youtube" or not pl.yt_playlist_id:
            return

        from domain.library.value_objects import extract_youtube_video_id as _extract_yt_video_id  # noqa: PLC0415
        for pos, video_id in enumerate(cmd.ordered_video_ids):
            yt_item_id = self._repo.get_yt_item_id(cmd.playlist_id, video_id)
            if not yt_item_id:
                continue
            agg = self._video_repo.get_by_id(video_id)
            if agg is None:
                continue
            yt_vid_id = _extract_yt_video_id(agg.video.url)
            if not yt_vid_id:
                continue
            try:
                yt_api.update_item_position(
                    yt_item_id, pl.yt_playlist_id, yt_vid_id, pos
                )
            except Exception:
                logger.exception("재생목록 순서 변경 API 동기화 실패")  # API 실패 시 로컬 순서만 변경


class ImportYouTubePlaylistHandler:
    """YouTube 재생목록을 가져와 로컬 DB에 저장.

    영상이 라이브러리에 없으면 사전 수집 메타데이터로 자동 등록한다.
    YouTube API가 설정된 경우 yt_item_id도 저장하여 양방향 동기화를 지원한다.
    """

    def __init__(
        self,
        playlist_repo: IPlaylistRepository,
        video_repo: IVideoRepository,
        ytdlp: IMediaSource,
        add_video_handler: "AddVideoHandler | None" = None,
        yt_api=None,    # YouTubeApiAdapter | None
        yt_oauth=None,  # YouTubeOAuthAdapter | None — 런타임 fresh 자격증명용
        yt_api_factory: Callable[[object], object] | None = None,
    ) -> None:
        self._playlist_repo = playlist_repo
        self._video_repo = video_repo
        self._ytdlp = ytdlp
        self._add_video = add_video_handler
        self._yt_api = yt_api
        self._yt_oauth = yt_oauth
        # fresh 자격증명으로 API 어댑터를 만드는 팩토리 (composition root가 주입).
        # 주입되지 않으면 런타임 자격증명 갱신 경로를 건너뛴다.
        self._yt_api_factory = yt_api_factory

    def handle(self, cmd: ImportYouTubePlaylistCommand) -> PlaylistDTO:
        # 기존에 이미 가져온 재생목록이면 재사용
        pl = self._playlist_repo.get_by_yt_id(cmd.yt_playlist_id)

        # 재생목록 내용 가져오기:
        #   1차: yt-dlp (공개 재생목록은 쿠키 불필요)
        #   2차: OAuth API fallback (비공개 재생목록, 또는 쿠키 미설정 시)
        playlist_title: str
        entries: list[dict]
        _entries_have_item_ids = False  # API 경로는 yt_item_id를 entries에 포함

        try:
            playlist_title, entries = self._ytdlp.fetch_playlist_videos(
                cmd.yt_playlist_id, cmd.cookie_opts
            )
        except Exception as ytdlp_exc:
            # yt-dlp 실패 → OAuth API fallback 시도
            # (비공개 재생목록, 쿠키 미설정, Chrome 실행 중 잠금 등 모든 케이스)
            api = self._get_active_yt_api()
            if api is None:
                raise
            try:
                playlist_title, entries = self._fetch_via_yt_api(cmd.yt_playlist_id)
                _entries_have_item_ids = True
            except Exception as api_exc:
                # 두 경로 모두 실패 — API 오류가 더 구체적이면 그것을 전파
                api_msg = str(api_exc)
                if api_msg and "자격증명" not in api_msg:
                    raise RuntimeError(
                        f"재생목록을 가져올 수 없습니다.\n"
                        f"• yt-dlp: {ytdlp_exc}\n"
                        f"• YouTube API: {api_exc}"
                    ) from api_exc
                raise ytdlp_exc

        total = len(entries)

        video_ids: list[UUID] = []
        _seen_ids: set[UUID] = set()
        for i, entry in enumerate(entries):
            url = entry.get("url") or ""
            if not url:
                continue
            # 라이브러리에 없으면 flat 메타데이터로 즉시 추가 (개별 API 조회 없음)
            agg = self._video_repo.get_by_url(url)
            if agg is None and self._add_video is not None:
                try:
                    agg = self._add_video.handle(
                        AddVideoCommand(
                            url=url,
                            prefetched_title=entry.get("title") or url,
                            prefetched_channel=entry.get("channel_name") or "",
                            prefetched_duration_sec=entry.get("duration_sec"),
                            prefetched_thumbnail_url=entry.get("thumbnail_url") or "",
                            prefetched_upload_date=entry.get("upload_date") or "",
                            prefetched_view_count=entry.get("view_count"),
                        )
                    )
                except Exception:
                    logger.exception("재생목록 영상 라이브러리 추가 실패")
            if agg is not None and agg.video.id not in _seen_ids:
                _seen_ids.add(agg.video.id)
                video_ids.append(agg.video.id)
            if cmd.on_progress:
                cmd.on_progress(i + 1, total)

        if pl is None:
            pl = Playlist.create(
                title=playlist_title,
                yt_playlist_id=cmd.yt_playlist_id,
                source="youtube",
            )
            self._playlist_repo.save(pl)
        elif pl.title == pl.yt_playlist_id:
            pl.title = playlist_title
            pl.updated_at = datetime.now(timezone.utc)
            self._playlist_repo.save(pl)

        self._playlist_repo.set_items(pl.id, video_ids)

        # yt_item_id 저장 (삭제·순서변경 API 호출 시 필요)
        if self._yt_api is not None and pl.yt_playlist_id:
            if _entries_have_item_ids:
                # API 경로: entries에 yt_item_id 포함 → 직접 사용
                for entry in entries:
                    yt_vid = entry.get("yt_video_id") or ""
                    yt_item_id = entry.get("yt_item_id") or ""
                    if not yt_vid or not yt_item_id:
                        continue
                    agg = self._video_repo.get_by_url(entry.get("url") or "")
                    if agg is not None:
                        self._playlist_repo.set_yt_item_id(pl.id, agg.video.id, yt_item_id)
            else:
                # yt-dlp 경로: API에서 별도 조회
                try:
                    yt_items = self._yt_api.list_items(pl.yt_playlist_id)
                    yt_item_map = {item["yt_video_id"]: item["yt_item_id"] for item in yt_items}
                    for entry in entries:
                        yt_vid = entry.get("yt_video_id") or ""
                        yt_item_id = yt_item_map.get(yt_vid, "")
                        if not yt_vid or not yt_item_id:
                            continue
                        agg = self._video_repo.get_by_url(entry.get("url") or "")
                        if agg is not None:
                            self._playlist_repo.set_yt_item_id(pl.id, agg.video.id, yt_item_id)
                except Exception:
                    logger.exception("yt_item_id API 동기화 실패")

        # item_count 최신 반영
        pl = self._playlist_repo.get_by_id(pl.id)
        return PlaylistDTO(
            id=pl.id,
            title=pl.title,
            yt_playlist_id=pl.yt_playlist_id,
            source=pl.source,
            item_count=pl.item_count,
        )

    def _get_active_yt_api(self):
        """현재 유효한 YouTubeApiAdapter 인스턴스를 반환한다.

        핸들러 생성 시점에 OAuth가 없었거나 토큰이 갱신된 경우를 위해
        yt_oauth 어댑터에서 fresh 자격증명을 가져와 새 인스턴스를 생성한다.
        """
        if self._yt_api is not None:
            return self._yt_api
        if self._yt_oauth is not None and self._yt_api_factory is not None:
            try:
                creds = self._yt_oauth.get_credentials()
                if creds is not None:
                    return self._yt_api_factory(creds)
            except Exception:
                logger.exception("YouTube API 자격증명 로드 실패")
        return None

    def _fetch_via_yt_api(self, yt_playlist_id: str) -> tuple[str, list[dict]]:
        """OAuth API로 재생목록 내용 가져오기. entries에 yt_item_id 포함."""
        api = self._get_active_yt_api()
        if api is None:
            raise RuntimeError("YouTube API 자격증명을 가져올 수 없습니다.")
        entries = api.list_items_full(yt_playlist_id)
        title = api.get_playlist_title(yt_playlist_id) or yt_playlist_id
        return title, entries


# ── 폴더 커맨드 ────────────────────────────────────────────────────────────

@dataclass
class CreatePlaylistFolderCommand:
    name: str
    source: str = "local"


@dataclass
class RenamePlaylistFolderCommand:
    folder_id: UUID
    new_name: str


@dataclass
class DeletePlaylistFolderCommand:
    folder_id: UUID


@dataclass
class MovePlaylistToFolderCommand:
    playlist_id: UUID
    folder_id: UUID | None   # None = 미분류(최상위)


@dataclass
class CopyYouTubePlaylistToLocalCommand:
    """YouTube 재생목록을 로컬로 복사 (원본 YouTube 재생목록은 유지)."""
    yt_playlist_id: str
    folder_id: UUID | None = None
    cookie_opts: dict | None = None


@dataclass
class MoveVideoToPlaylistCommand:
    """영상을 현재 재생목록에서 다른 재생목록으로 이전한다."""
    video_id: UUID
    source_playlist_id: UUID | None   # None = 이전이 아닌 단순 추가
    target_playlist_id: UUID


@dataclass
class PushPlaylistToYouTubeCommand:
    """로컬 재생목록을 YouTube에 생성한다.

    move=True: 로컬 재생목록을 YouTube 재생목록으로 전환 (source 변경)
    move=False: 로컬은 유지하고 YouTube에 새 재생목록 생성
    """
    playlist_id: UUID
    move: bool = False
    privacy_status: str = "private"  # "private" | "unlisted" | "public"


# ── 폴더 핸들러 ─────────────────────────────────────────────────────────────

class CreatePlaylistFolderHandler:
    def __init__(self, folder_repo: IPlaylistFolderRepository) -> None:
        self._repo = folder_repo

    def handle(self, cmd: CreatePlaylistFolderCommand) -> PlaylistFolderDTO:
        folder = PlaylistFolder.create(name=cmd.name, source=cmd.source)
        self._repo.save(folder)
        return PlaylistFolderDTO(id=folder.id, name=folder.name, source=folder.source)


class RenamePlaylistFolderHandler:
    def __init__(self, folder_repo: IPlaylistFolderRepository) -> None:
        self._repo = folder_repo

    def handle(self, cmd: RenamePlaylistFolderCommand) -> None:
        from datetime import datetime, timezone  # noqa: PLC0415
        folder = self._repo.get_by_id(cmd.folder_id)
        if folder is None:
            return
        folder.name = cmd.new_name
        folder.updated_at = datetime.now(timezone.utc)
        self._repo.save(folder)


class DeletePlaylistFolderHandler:
    def __init__(self, folder_repo: IPlaylistFolderRepository) -> None:
        self._repo = folder_repo

    def handle(self, cmd: DeletePlaylistFolderCommand) -> None:
        self._repo.delete(cmd.folder_id)


class MovePlaylistToFolderHandler:
    def __init__(self, playlist_repo: IPlaylistRepository) -> None:
        self._repo = playlist_repo

    def handle(self, cmd: MovePlaylistToFolderCommand) -> None:
        self._repo.update_folder(cmd.playlist_id, cmd.folder_id)


class CopyYouTubePlaylistToLocalHandler:
    """YouTube 재생목록을 로컬 재생목록으로 복사 (yt-dlp 사용, YouTube 원본 유지)."""

    def __init__(
        self,
        playlist_repo: IPlaylistRepository,
        video_repo: IVideoRepository,
        ytdlp: IMediaSource,
    ) -> None:
        self._playlist_repo = playlist_repo
        self._video_repo = video_repo
        self._ytdlp = ytdlp

    def handle(self, cmd: CopyYouTubePlaylistToLocalCommand) -> PlaylistDTO:
        # fetch_playlist_videos가 (제목, 영상목록) 튜플을 반환
        playlist_title, entries = self._ytdlp.fetch_playlist_videos(
            cmd.yt_playlist_id, cmd.cookie_opts
        )

        pl = Playlist.create(
            title=f"{playlist_title} (로컬 복사)",
            yt_playlist_id=None,   # 로컬 복사본이므로 YouTube 연동 없음
            source="local",
            folder_id=cmd.folder_id,
        )
        self._playlist_repo.save(pl)

        video_ids: list[UUID] = []
        for entry in entries:
            url = entry.get("url") or ""
            if url:
                agg = self._video_repo.get_by_url(url)
                if agg is not None:
                    video_ids.append(agg.video.id)

        if video_ids:
            self._playlist_repo.set_items(pl.id, video_ids)

        pl = self._playlist_repo.get_by_id(pl.id)
        return PlaylistDTO(
            id=pl.id,
            title=pl.title,
            yt_playlist_id=pl.yt_playlist_id,
            source=pl.source,
            item_count=pl.item_count,
            folder_id=pl.folder_id,
        )


class MoveVideoToPlaylistHandler:
    """영상을 소스 재생목록에서 제거하고 대상 재생목록에 추가한다.

    YouTube 재생목록이면 API에도 즉시 반영한다.
    """

    def __init__(
        self,
        playlist_repo: IPlaylistRepository,
        video_repo: IVideoRepository | None = None,
        yt_api=None,
        yt_api_provider: "Callable[[], object | None] | None" = None,
    ) -> None:
        self._repo = playlist_repo
        self._video_repo = video_repo
        self._yt_api = yt_api
        self._yt_api_provider = yt_api_provider

    def handle(self, cmd: MoveVideoToPlaylistCommand) -> None:
        src = cmd.source_playlist_id
        tgt = cmd.target_playlist_id
        if src == tgt:
            return

        yt_api = _resolve_yt_api(self._yt_api, self._yt_api_provider)

        # ── 소스에서 제거 ──────────────────────────────────────────────
        if src is not None:
            if yt_api:
                src_pl = self._repo.get_by_id(src)
                if src_pl and src_pl.source == "youtube":
                    yt_item_id = self._repo.get_yt_item_id(src, cmd.video_id)
                    if yt_item_id:
                        try:
                            yt_api.remove_video(yt_item_id)
                        except Exception:
                            logger.exception("재생목록 영상 제거 API 동기화 실패")
            self._repo.remove_video(src, cmd.video_id)

        # ── 대상에 추가 ────────────────────────────────────────────────
        self._repo.add_video(tgt, cmd.video_id)
        if yt_api and self._video_repo:
            tgt_pl = self._repo.get_by_id(tgt)
            if tgt_pl and tgt_pl.source == "youtube" and tgt_pl.yt_playlist_id:
                from domain.library.value_objects import extract_youtube_video_id as _extract_yt_video_id  # noqa: PLC0415
                agg = self._video_repo.get_by_id(cmd.video_id)
                if agg:
                    yt_vid_id = _extract_yt_video_id(agg.video.url)
                    if yt_vid_id:
                        try:
                            yt_item_id = yt_api.add_video(tgt_pl.yt_playlist_id, yt_vid_id)
                            self._repo.set_yt_item_id(tgt, cmd.video_id, yt_item_id)
                        except Exception:
                            logger.exception("재생목록 영상 이동 API 동기화 실패")


class PushPlaylistToYouTubeHandler:
    """로컬 재생목록을 YouTube에 생성하고 영상을 업로드한다.

    move=True: 로컬 플레이리스트를 YouTube 플레이리스트로 전환
    move=False: 로컬은 유지하고 YouTube에 복사본 생성
    """

    def __init__(
        self,
        playlist_repo: IPlaylistRepository,
        video_repo: IVideoRepository,
        yt_adapter=None,   # YouTubeApiAdapter | None
        yt_api_provider: "Callable[[], object | None] | None" = None,
    ) -> None:
        self._repo = playlist_repo
        self._video_repo = video_repo
        self._yt = yt_adapter
        self._yt_api_provider = yt_api_provider

    def handle(self, cmd: PushPlaylistToYouTubeCommand) -> PlaylistDTO:
        from domain.library.value_objects import extract_youtube_video_id as _extract_yt_video_id  # noqa: PLC0415

        yt = _resolve_yt_api(self._yt, self._yt_api_provider)
        if yt is None:
            raise RuntimeError(
                "YouTube API가 연결되지 않았습니다.\n설정 > YouTube API 연동에서 인증하세요."
            )

        pl = self._repo.get_by_id(cmd.playlist_id)
        if pl is None:
            raise ValueError(f"Playlist {cmd.playlist_id} not found")

        # YouTube 재생목록 생성
        yt_pl_id = yt.create_playlist(pl.title, privacy_status=cmd.privacy_status)

        # 영상 추가
        items = self._repo.get_items(pl.id)
        pushed: list[tuple] = []  # (video_id, yt_item_id)
        for video_id, _pos in items:
            agg = self._video_repo.get_by_id(video_id)
            if agg is None:
                continue
            yt_vid_id = _extract_yt_video_id(agg.video.url)
            if not yt_vid_id:
                continue
            try:
                yt_item_id = yt.add_video(yt_pl_id, yt_vid_id)
                pushed.append((video_id, yt_item_id))
            except Exception:
                logger.exception("YouTube 재생목록 영상 업로드 실패")

        if cmd.move:
            # 기존 재생목록을 YouTube 재생목록으로 전환
            pl.source = "youtube"
            pl.yt_playlist_id = yt_pl_id
            pl.updated_at = datetime.now(timezone.utc)
            self._repo.save(pl)
            for vid_id, yt_item_id in pushed:
                self._repo.set_yt_item_id(pl.id, vid_id, yt_item_id)
            target_pl = pl
        else:
            # 새 YouTube 재생목록 생성 (로컬 원본 유지)
            target_pl = Playlist.create(
                title=pl.title,
                yt_playlist_id=yt_pl_id,
                source="youtube",
                folder_id=pl.folder_id,
            )
            self._repo.save(target_pl)
            for i, (vid_id, yt_item_id) in enumerate(pushed):
                self._repo.add_video(target_pl.id, vid_id, i)
                self._repo.set_yt_item_id(target_pl.id, vid_id, yt_item_id)
            # item_count 갱신
            target_pl = self._repo.get_by_id(target_pl.id)

        return PlaylistDTO(
            id=target_pl.id,
            title=target_pl.title,
            yt_playlist_id=target_pl.yt_playlist_id,
            source=target_pl.source,
            item_count=target_pl.item_count,
            folder_id=target_pl.folder_id,
        )


# ── 피드 → 재생목록 직접 추가 ───────────────────────────────────────────────

@dataclass
class AddUrlToPlaylistCommand:
    """URL로 영상을 식별하여 재생목록에 추가. 라이브러리 미등록 시 먼저 추가한다."""
    url: str
    playlist_id: UUID


class AddUrlToPlaylistHandler:
    def __init__(
        self,
        add_video_handler: AddVideoHandler,
        playlist_repo: IPlaylistRepository,
    ) -> None:
        self._add_video = add_video_handler
        self._pl_repo = playlist_repo

    def handle(self, cmd: AddUrlToPlaylistCommand) -> UUID:
        """영상을 라이브러리에 추가(upsert)한 뒤 재생목록에 연결한다. 영상 ID 반환."""
        agg = self._add_video.handle(AddVideoCommand(url=cmd.url))
        self._pl_repo.add_video(cmd.playlist_id, agg.video.id)
        return agg.video.id
