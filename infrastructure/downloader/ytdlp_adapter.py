from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable
from uuid import UUID

import requests

from config.settings import DOWNLOAD_DIR, THUMBNAIL_DIR
from domain.download.value_objects import DownloadProgress, DownloadSettings, MediaFormat, Quality
from utils.resources import get_ffmpeg_path

logger = logging.getLogger(__name__)

_DPAPI_USER_MSG = (
    "Chrome 쿠키를 복호화할 수 없습니다 (DPAPI 오류).\n"
    "다음 중 하나를 시도해 주세요:\n"
    "• Chrome을 완전히 종료한 후 다시 시도\n"
    "• 설정 > YouTube 계정에서 Firefox를 선택\n"
    "• 설정 > YouTube 계정에서 재로그인(Playwright 방식)"
)


def _is_dpapi_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "dpapi" in msg or "failed to decrypt" in msg


def _height_to_quality_label(height: int | None) -> str:
    """픽셀 높이를 사람이 읽기 쉬운 품질 레이블로 변환한다.

    예: 1080 → "FHD", 2160 → "UHD (4K)", None → ""
    """
    if height is None:
        return ""
    if height >= 2160:
        return "UHD (4K)"
    if height >= 1440:
        return "QHD (2K)"
    if height >= 1080:
        return "FHD"
    if height >= 720:
        return "HD"
    if height >= 480:
        return "SD"
    return f"{height}p"


def _find_ffmpeg() -> str | None:
    """Return path to ffmpeg executable, or None if not found."""
    try:
        return get_ffmpeg_path()
    except FileNotFoundError:
        return None


class YtDlpAdapter:
    """Thin wrapper around yt-dlp for single-video downloads.

    All network I/O runs in a background QThread — never call from the GUI thread.
    """

    def __init__(
        self,
        on_progress: Callable[[DownloadProgress], None] | None = None,
    ) -> None:
        self._on_progress = on_progress

    def fetch_metadata(self, url: str) -> dict:
        """Return video metadata without downloading."""
        import yt_dlp  # noqa: PLC0415
        opts = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "socket_timeout": 30,
            "retries": 0,
            "extractor_retries": 0,
            "noplaylist": True,   # treat list= params as single video, not playlist
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            return ydl.extract_info(url, download=False) or {}

    def download_thumbnail(
        self,
        video_id: UUID,
        thumbnail_url: str,
        force: bool = False,
        max_age_days: int | None = None,
    ) -> str | None:
        """Download thumbnail image; return relative filename or None on failure.

        Args:
            video_id: UUID of the video, used as the filename stem.
            thumbnail_url: Remote URL of the thumbnail image.
            force: When True, delete any existing cached file before downloading.
            max_age_days: 파일이 이 일수보다 오래됐으면 강제 재다운로드.
        """
        if not thumbnail_url:
            return None
        raw_ext = thumbnail_url.split("?")[0].rsplit(".", 1)
        ext = raw_ext[-1].lower() if len(raw_ext) > 1 and raw_ext[-1].lower() in ("jpg", "jpeg", "png", "webp") else "jpg"
        filename = f"{video_id}.{ext}"
        dest = THUMBNAIL_DIR / filename
        if force:
            dest.unlink(missing_ok=True)
        if not force and max_age_days is not None and dest.exists():
            import time
            age_days = (time.time() - dest.stat().st_mtime) / 86400
            if age_days > max_age_days:
                dest.unlink(missing_ok=True)
        if dest.exists():
            return filename
        try:
            THUMBNAIL_DIR.mkdir(parents=True, exist_ok=True)
            resp = requests.get(thumbnail_url, timeout=15)
            resp.raise_for_status()
            dest.write_bytes(resp.content)
            return filename
        except Exception:
            logger.exception("썸네일 다운로드 실패")
            return None

    def download(
        self,
        url: str,
        settings: DownloadSettings,
        output_dir: Path | None = None,
    ) -> Path:
        """Download *url* with *settings*; return the final file path.

        If ffmpeg is not available, falls back to a single-stream format that
        requires no post-processing merging.
        """
        import yt_dlp  # noqa: PLC0415
        out_dir = output_dir or DOWNLOAD_DIR
        out_dir.mkdir(parents=True, exist_ok=True)

        ffmpeg = _find_ffmpeg()
        has_ffmpeg = ffmpeg is not None

        format_spec = (
            self._build_format_spec(settings)
            if has_ffmpeg
            else self._build_format_spec_no_ffmpeg(settings)
        )

        opts: dict = {
            "format": format_spec,
            "outtmpl": str(out_dir / "%(title)s.%(ext)s"),
            "quiet": True,
            "no_warnings": True,
            "progress_hooks": [self._progress_hook],
            "noplaylist": True,
        }

        if has_ffmpeg:
            opts["ffmpeg_location"] = ffmpeg
            opts["merge_output_format"] = "mp4"  # 병합 출력을 항상 mp4로 고정

            if settings.subtitle_langs:
                opts["writesubtitles"] = True
                opts["subtitleslangs"] = list(settings.subtitle_langs)

            if settings.include_metadata:
                opts.setdefault("postprocessors", [])
                opts["postprocessors"].append({"key": "FFmpegMetadata"})

            if settings.format in (MediaFormat.MP3, MediaFormat.M4A):
                opts.setdefault("postprocessors", [])
                opts["postprocessors"].append(
                    {
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": settings.format.value,
                    }
                )

        self._last_filepath: str = ""
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if info:
                # requested_downloads contains the actual post-processed filepath
                rd = (info.get("requested_downloads") or [{}])[0]
                self._last_filepath = (
                    rd.get("filepath")
                    or info.get("filepath")
                    or ydl.prepare_filename(info)
                )
                # 오디오 포맷이 아닐 때만 실제 다운로드 품질 레이블을 파일명에 삽입
                if settings.format not in (MediaFormat.MP3, MediaFormat.M4A):
                    actual_height = rd.get("height") or info.get("height")
                    label = _height_to_quality_label(actual_height)
                    if label:
                        p = Path(self._last_filepath)
                        new_path = p.with_name(f"{p.stem} [{label}]{p.suffix}")
                        try:
                            if p.exists() and not new_path.exists():
                                p.rename(new_path)
                                self._last_filepath = str(new_path)
                        except OSError:
                            pass  # 이름 변경 실패 시 원본 경로 유지

        return Path(self._last_filepath)

    # ------------------------------------------------------------------
    # YouTube 계정 연동 (브라우저 쿠키 인증)
    # ------------------------------------------------------------------

    def fetch_user_playlists(self, cookie_opts: dict | None = None) -> list[dict]:
        """인증된 YouTube 계정의 재생목록 목록 반환.

        Watch Later(WL) 플레이리스트에서 채널 URL을 얻은 뒤,
        채널 /playlists 탭을 조회한다.

        반환: [{"id": "PLxxx", "title": "...", "count": N}, ...]
        """
        import yt_dlp  # noqa: PLC0415
        opts = cookie_opts or {}
        if not opts:
            return []

        base_opts = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "extract_flat": True,
            "extractor_args": {"youtubetab": {"skip": ["authcheck"]}},
            **opts,
        }

        # 1단계: Watch Later에서 사용자 채널 URL 추출
        channel_url = ""
        try:
            with yt_dlp.YoutubeDL({**base_opts, "playlistend": 1}) as ydl:
                wl_info = ydl.extract_info(
                    "https://www.youtube.com/playlist?list=WL", download=False
                ) or {}
            channel_url = (
                wl_info.get("uploader_url")
                or wl_info.get("channel_url")
                or ""
            )
        except Exception:
            logger.exception("Watch Later에서 사용자 채널 URL 추출 실패")
            return []

        if not channel_url:
            return []

        # 2단계: 채널 /playlists 탭에서 재생목록 목록 가져오기
        pl_url = channel_url.rstrip("/") + "/playlists"
        try:
            with yt_dlp.YoutubeDL(base_opts) as ydl:
                info = ydl.extract_info(pl_url, download=False) or {}
        except Exception:
            logger.exception("채널 재생목록 탭 조회 실패")
            return []

        return [
            {
                "id": e.get("id") or "",
                "title": e.get("title") or "",
                "count": e.get("playlist_count") or 0,
            }
            for e in (info.get("entries") or [])
            if e.get("id")
        ]

    def fetch_playlist_videos(
        self,
        playlist_id: str,
        cookie_opts: dict | None = None,
    ) -> tuple[str, list[dict]]:
        """재생목록 제목과 영상 목록 반환 (순서 보장).

        반환: (playlist_title, [{"url": "...", "title": "...", "position": N, "yt_video_id": "..."}, ...])
        """
        import yt_dlp  # noqa: PLC0415
        url = f"https://www.youtube.com/playlist?list={playlist_id}"
        base_opts = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "extract_flat": True,
        }

        # 공개 재생목록은 쿠키 없이 가져올 수 있으므로 먼저 시도한다.
        info: dict = {}
        try:
            with yt_dlp.YoutubeDL(base_opts) as ydl:
                info = ydl.extract_info(url, download=False) or {}
        except Exception as first_exc:
            # 인증이 필요한 오류 패턴 (비공개 재생목록 포함)
            first_msg = str(first_exc).lower()
            needs_auth = any(p in first_msg for p in (
                "sign in", "login", "private",
                "does not exist", "not exist",
                "unavailable", "403",
            ))

            if not needs_auth:
                # 인증과 무관한 오류는 그대로 전파
                raise

            if not cookie_opts:
                raise RuntimeError(
                    "비공개 재생목록을 가져오려면 YouTube 계정 인증이 필요합니다.\n"
                    "설정 > YouTube 계정에서 브라우저 프로필을 선택하거나\n"
                    "쿠키 파일(.txt)을 등록해 주세요."
                ) from first_exc

            # 쿠키 포함 재시도
            try:
                with yt_dlp.YoutubeDL({**base_opts, **cookie_opts}) as ydl:
                    info = ydl.extract_info(url, download=False) or {}
            except Exception as cookie_exc:
                err_str = str(cookie_exc)
                if "could not copy" in err_str.lower() and "cookie" in err_str.lower():
                    raise RuntimeError(
                        "브라우저 쿠키를 읽을 수 없습니다.\n"
                        "Chrome이 실행 중이면 종료 후 재시도하거나,\n"
                        "설정 > YouTube 계정에서 쿠키 파일을 직접 등록하세요."
                    ) from cookie_exc
                raise
        # info.get("title") = 재생목록 제목 (e.g. "AI-Agent")
        playlist_title = info.get("title") or playlist_id
        entries = []
        for i, e in enumerate(info.get("entries") or []):
            url = e.get("url") or e.get("webpage_url") or ""
            if not url:
                continue
            yt_vid = e.get("id") or ""
            # extract_flat 모드에서 thumbnail이 없으면 YouTube CDN fallback
            thumb = e.get("thumbnail") or (
                f"https://i.ytimg.com/vi/{yt_vid}/mqdefault.jpg" if yt_vid else ""
            )
            entries.append({
                "url": url,
                "title": e.get("title") or "",
                "position": i,
                "yt_video_id": yt_vid,
                "channel_name": e.get("uploader") or e.get("channel") or "",
                "duration_sec": e.get("duration"),
                "thumbnail_url": thumb,
                "upload_date": e.get("upload_date") or "",
                "view_count": e.get("view_count"),
            })
        return playlist_title, entries

    def fetch_subscription_feed(
        self,
        limit: int = 100,
        cookie_opts: dict | None = None,
    ) -> list[dict]:
        """구독 채널 최신 영상 목록 반환.

        반환: [{"url", "title", "channel_name", "thumbnail",
                "published_at", "view_count", "duration_sec"}, ...]
        """
        import yt_dlp  # noqa: PLC0415
        opts = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "extract_flat": True,
            "playlistend": limit,
            **(cookie_opts or {}),
        }
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(
                    "https://www.youtube.com/feed/subscriptions", download=False
                ) or {}
        except Exception as exc:
            if _is_dpapi_error(exc):
                raise RuntimeError(_DPAPI_USER_MSG) from exc
            raise
        result = []
        for e in (info.get("entries") or [])[:limit]:
            yt_id = e.get("id") or ""
            url_val = e.get("url") or e.get("webpage_url") or (
                f"https://www.youtube.com/watch?v={yt_id}" if yt_id else ""
            )
            if not url_val:
                continue
            # extract_flat에서 thumbnail이 없을 때 YouTube 표준 URL fallback
            thumb = e.get("thumbnail") or (
                f"https://i.ytimg.com/vi/{yt_id}/mqdefault.jpg" if yt_id else ""
            )
            result.append(
                {
                    "url": url_val,
                    "yt_video_id": yt_id,
                    "title": e.get("title") or "",
                    "channel_name": e.get("uploader") or e.get("channel") or "",
                    "channel_id": e.get("channel_id") or "",
                    "thumbnail": thumb,
                    "published_at": e.get("upload_date") or "",
                    "view_count": e.get("view_count"),
                    "duration_sec": e.get("duration"),
                }
            )
        return result

    def fetch_subscribed_channels(self, cookie_opts: dict | None = None) -> list[dict]:
        """YouTube 구독 채널 목록 반환.

        반환: [{"id": "UCxxx", "name": "...", "url": "..."}, ...]

        ``youtube.com/feed/channels``는 지연 로딩(continuation) 페이지로 구성되므로,
        큰 ``playlistend``를 지정하고 ``entries`` 제너레이터를 끝까지 소진해
        전체 구독 채널을 가져온다. (이전에는 첫 페이지만 반환되는 버그가 있었다.)
        """
        import yt_dlp  # noqa: PLC0415
        opts = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "extract_flat": True,
            "playlistend": 1000,
            **(cookie_opts or {}),
        }
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(
                    "https://www.youtube.com/feed/channels", download=False
                ) or {}
        except Exception as exc:
            if _is_dpapi_error(exc):
                raise RuntimeError(_DPAPI_USER_MSG) from exc
            raise
        result = []
        # 지연 제너레이터를 list로 완전히 소진해 continuation을 끝까지 따라간다.
        for e in list(info.get("entries") or []):
            ch_id = e.get("id") or e.get("channel_id") or ""
            ch_name = e.get("title") or e.get("uploader") or e.get("channel") or ""
            ch_url = e.get("url") or e.get("webpage_url") or ""
            if not ch_url and ch_id:
                ch_url = f"https://www.youtube.com/channel/{ch_id}"
            if ch_url:
                result.append({"id": ch_id, "name": ch_name, "url": ch_url})
        return result

    def fetch_channel_videos(
        self,
        channel_url: str,
        limit: int = 30,
        cookie_opts: dict | None = None,
    ) -> list[dict]:
        """특정 채널의 최신 영상 목록 반환.

        반환 키 집합은 ``fetch_subscription_feed``와 동일해 DTO 매핑을 공유한다.
        """
        import yt_dlp  # noqa: PLC0415
        url = channel_url.rstrip("/")
        if not url.endswith("/videos"):
            url = f"{url}/videos"
        opts = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "extract_flat": True,
            "playlistend": limit,
            **(cookie_opts or {}),
        }
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False) or {}
        except Exception as exc:
            if _is_dpapi_error(exc):
                raise RuntimeError(_DPAPI_USER_MSG) from exc
            raise
        channel_name = info.get("channel") or info.get("uploader") or info.get("title") or ""
        result = []
        for e in (info.get("entries") or [])[:limit]:
            yt_id = e.get("id") or ""
            url_val = e.get("url") or e.get("webpage_url") or (
                f"https://www.youtube.com/watch?v={yt_id}" if yt_id else ""
            )
            if not url_val:
                continue
            thumb = e.get("thumbnail") or (
                f"https://i.ytimg.com/vi/{yt_id}/mqdefault.jpg" if yt_id else ""
            )
            result.append(
                {
                    "url": url_val,
                    "yt_video_id": yt_id,
                    "title": e.get("title") or "",
                    "channel_name": e.get("uploader") or e.get("channel") or channel_name,
                    "channel_id": e.get("channel_id") or info.get("channel_id") or "",
                    "thumbnail": thumb,
                    "published_at": e.get("upload_date") or "",
                    "view_count": e.get("view_count"),
                    "duration_sec": e.get("duration"),
                }
            )
        return result

    def fetch_search_videos(
        self,
        query: str,
        limit: int = 12,
        cookie_opts: dict | None = None,
    ) -> list[dict]:
        """YouTube 검색 결과 상위 ``limit``건 반환 (추천 영상 후보).

        반환 키 집합은 ``fetch_subscription_feed``·``fetch_channel_videos``와
        동일해 DTO 매핑을 공유한다.

        ``ytsearch{N}:{query}`` 의사 URL을 쓰기 때문에 **인증이 필요 없다** —
        YouTube Data API 키/OAuth가 없는 사용자도 추천을 받을 수 있다.
        (쿠키가 주어지면 개인화된 결과를 위해 그대로 넘긴다.)
        """
        import yt_dlp  # noqa: PLC0415
        query = (query or "").strip()
        if not query or limit <= 0:
            return []
        opts = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "extract_flat": True,
            "playlistend": limit,
            **(cookie_opts or {}),
        }
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(f"ytsearch{limit}:{query}", download=False) or {}
        except Exception as exc:
            if _is_dpapi_error(exc):
                raise RuntimeError(_DPAPI_USER_MSG) from exc
            raise
        result = []
        for e in (info.get("entries") or [])[:limit]:
            yt_id = e.get("id") or ""
            url_val = e.get("url") or e.get("webpage_url") or (
                f"https://www.youtube.com/watch?v={yt_id}" if yt_id else ""
            )
            if not url_val:
                continue
            thumb = e.get("thumbnail") or (
                f"https://i.ytimg.com/vi/{yt_id}/mqdefault.jpg" if yt_id else ""
            )
            result.append(
                {
                    "url": url_val,
                    "yt_video_id": yt_id,
                    "title": e.get("title") or "",
                    "channel_name": e.get("uploader") or e.get("channel") or "",
                    "channel_id": e.get("channel_id") or "",
                    "thumbnail": thumb,
                    "published_at": e.get("upload_date") or "",
                    "view_count": e.get("view_count"),
                    "duration_sec": e.get("duration"),
                }
            )
        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_format_spec(self, settings: DownloadSettings) -> str:
        """Format spec when ffmpeg IS available (allows merging video+audio).

        H.264(avc1)+AAC(mp4a)를 우선 선택해 mp4 병합 호환성을 높인다.
        해당 코덱이 없으면 임의 포맷으로 폴백.
        """
        if settings.quality == Quality.AUDIO:
            return "bestaudio[acodec^=mp4a]/bestaudio/best"
        if settings.quality == Quality.BEST:
            return (
                "bestvideo[vcodec^=avc1]+bestaudio[acodec^=mp4a]"
                "/bestvideo+bestaudio/best"
            )
        if settings.quality == Quality.WORST:
            return "worstvideo+worstaudio/worst"
        h = settings.quality.value.rstrip("p")
        return (
            f"bestvideo[height<={h}][vcodec^=avc1]+bestaudio[acodec^=mp4a]"
            f"/bestvideo[height<={h}]+bestaudio"
            f"/best[height<={h}]/best"
        )

    def _build_format_spec_no_ffmpeg(self, settings: DownloadSettings) -> str:
        """Format spec when ffmpeg is NOT available (single-stream, no merging)."""
        if settings.quality == Quality.AUDIO:
            return "bestaudio[ext=m4a]/bestaudio[ext=mp4]/bestaudio"
        if settings.quality == Quality.BEST:
            return "best[ext=mp4]/best"
        if settings.quality == Quality.WORST:
            return "worst[ext=mp4]/worst"
        h = settings.quality.value.rstrip("p")
        return f"best[height<={h}][ext=mp4]/best[height<={h}]/best"

    def _progress_hook(self, info: dict) -> None:
        if self._on_progress is None:
            return
        if info.get("status") != "downloading":
            return
        try:
            pct_str = str(info.get("_percent_str") or "0").strip().rstrip("%")
            percent = float(pct_str or 0)
        except (ValueError, TypeError):
            percent = 0.0
        progress = DownloadProgress(
            percent=percent,
            speed_bps=float(info.get("speed") or 0),
            eta_sec=int(info.get("eta") or 0),
            downloaded_bytes=int(info.get("downloaded_bytes") or 0),
        )
        self._on_progress(progress)
