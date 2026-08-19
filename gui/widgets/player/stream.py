"""스트림 URL 확보 — yt-dlp 조회 워커와 재생 가능 여부 사전 검증.

**실패를 전제로 설계한다**: 같은 영상이라도 기본(web) 클라이언트 URL이 간헐적으로
403을 주므로 여러 클라이언트를 순회하고, 넘기기 전에 ffmpeg와 **똑같은 방식**
(열린 Range + Lavf UA)으로 검증한다 — 검증 방식이 다르면 통과했는데 재생만 실패한다.
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import (
    QThread,
    pyqtSignal,
)


# 영상별 사용 가능한 화질 목록 캐시 — 같은 URL을 다시 조회하지 않는다.

from collections import OrderedDict
_HEIGHT_CACHE: "OrderedDict[str, list[int]]" = OrderedDict()
_HEIGHT_CACHE_MAX = 64

from gui.widgets.player.constants import _DEFAULT_QUALITY_FMT, _PROBE_RANGE, _PROBE_TIMEOUT, _PROBE_UA, _STREAM_CLIENTS

logger = logging.getLogger(__name__)


def _is_youtube(url: str) -> bool:
    """YouTube URL인지 — 클라이언트 대체 재시도는 YouTube에서만 의미가 있다."""
    return "youtube.com" in url or "youtu.be" in url

def _pick_stream_url(info: dict) -> tuple[str, dict]:
    """yt-dlp info에서 재생할 단일 URL을 고른다 → (url, format_info).

    **영상+오디오가 모두 있는(muxed) 포맷을 우선**한다. 예전에는 마지막 폴백이 `url`만
    있으면 무엇이든 집어서, 영상만 있는 포맷을 골라 소리가 없거나 재생이 실패하는
    경우가 있었다. 무음 재생보다는 다음 후보로 넘어가는 편이 낫다.
    """
    if info.get("url"):
        return info["url"], info
    formats = info.get("formats") or []

    def _muxed(f: dict) -> bool:
        return f.get("vcodec") not in (None, "none") and f.get("acodec") not in (None, "none")

    for want_mp4 in (True, False):
        for f in reversed(formats):
            if not f.get("url") or not _muxed(f):
                continue
            if want_mp4 and f.get("ext") != "mp4":
                continue
            return f["url"], f
    return "", {}

def _stream_playable(url: str) -> bool:
    """URL을 QMediaPlayer에 넘기기 전에 **재생기와 같은 방식으로** 받아지는지 확인한다.

    재생 시작 뒤에 실패하면 사용자는 깨진 화면만 보게 되므로, 넘기기 전에 걸러 다음
    클라이언트로 넘어가는 편이 낫다. 요청 형태를 ffmpeg와 맞추는 것이 핵심이다
    (`_PROBE_RANGE` 주석 참조 — 제한 범위로 확인하면 통과했는데 재생은 403인 일이 있다).
    """
    try:
        import requests  # noqa: PLC0415

        resp = requests.get(
            url,
            headers={"User-Agent": _PROBE_UA, "Accept": "*/*", "Range": _PROBE_RANGE},
            stream=True,
            timeout=_PROBE_TIMEOUT,
        )
        resp.close()   # 본문은 읽지 않는다 — 열린 범위라 그대로 두면 전체가 흘러온다
        return resp.status_code in (200, 206)
    except Exception:
        logger.warning("스트림 URL 확인 실패 — 다음 후보로", exc_info=True)
        return False

class _StreamWorker(QThread):
    # (path_or_url, quality_label e.g. "720p", is_local) — is_local=True면 임시 병합 파일
    stream_ready = pyqtSignal(str, str, bool)
    progress     = pyqtSignal(int)   # 병합 다운로드 진행률(0-100)
    failed       = pyqtSignal(str)

    def __init__(
        self,
        url: str,
        quality_fmt: str = "best[ext=mp4]/best",
        merge: bool = False,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._url = url
        self._quality_fmt = quality_fmt
        self._merge = merge           # True면 영상+오디오를 ffmpeg로 병합해 임시 파일 재생

    def run(self) -> None:
        try:
            import yt_dlp  # noqa: PLC0415
            if self._merge:
                self._run_merge(yt_dlp)
            else:
                self._run_stream(yt_dlp)
        except Exception as exc:
            self.failed.emit(str(exc))

    # ── 즉시 스트리밍: 단일 muxed URL을 그대로 QMediaPlayer에 전달 ──
    def _run_stream(self, yt_dlp) -> None:
        """URL을 확보해 **검증까지 마친 뒤** 넘긴다. 실패하면 다른 클라이언트로 재시도.

        한 번 실패했다고 곧바로 포기하지 않는 것이 핵심이다 — 기본 클라이언트의 403은
        간헐적이라 대체 클라이언트로 다시 받으면 대개 살아난다.
        """
        clients = _STREAM_CLIENTS if _is_youtube(self._url) else (None,)
        last_err = ""
        unverified: tuple[str, str] | None = None   # 검증만 실패한 첫 URL
        for client in clients:
            try:
                stream, label = self._extract_stream(yt_dlp, client)
            except Exception as exc:
                last_err = str(exc)
                logger.warning(
                    "스트림 추출 실패(client=%s): %s", client or "기본", last_err[:200]
                )
                continue
            if not stream:
                last_err = "스트림 URL을 가져올 수 없습니다."
                logger.warning("재생 가능한 포맷 없음(client=%s)", client or "기본")
                continue
            if not _stream_playable(stream):
                last_err = "스트림 URL이 거부되었습니다(재생 서버 403)."
                logger.warning(
                    "스트림 URL 거부됨(client=%s) — 다음 클라이언트로 재시도", client or "기본"
                )
                if unverified is None:
                    unverified = (stream, label)
                continue
            if client:
                logger.info("대체 클라이언트로 스트림 확보: client=%s", client)
            self.stream_ready.emit(stream, label, False)
            return
        if unverified is not None:
            # 확인 요청이 전부 막히는 환경(프록시·방화벽)일 수 있다. 검증에 실패했다는
            # 이유만으로 재생을 포기하면 그런 환경에서는 영영 못 보므로, URL을 확보한
            # 이상 플레이어에게 한 번은 맡긴다(예전 동작과 최소한 동일하다).
            logger.warning("검증은 실패했으나 URL이 있어 그대로 재생 시도: %s", self._url)
            self.stream_ready.emit(unverified[0], unverified[1], False)
            return
        logger.warning("모든 클라이언트에서 스트림 확보 실패: %s", self._url)
        self.failed.emit(last_err or "스트림 URL을 가져올 수 없습니다.")

    def _extract_stream(self, yt_dlp, client: str | None) -> tuple[str, str]:
        """지정 클라이언트로 정보를 뽑아 (재생 URL, 화질 라벨)을 돌려준다."""
        opts = {"quiet": True, "no_warnings": True,
                "format": self._quality_fmt, "noplaylist": True}
        if client:
            opts["extractor_args"] = {"youtube": {"player_client": [client]}}
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(self._url, download=False) or {}
        stream, fmt_info = _pick_stream_url(info)
        h = fmt_info.get("height") or info.get("height")
        return stream, (f"{h}p" if h else "")

    # ── 고화질: 분리된 영상+오디오를 ffmpeg로 임시 mp4에 병합해 로컬 재생 ──
    def _run_merge(self, yt_dlp) -> None:
        import os  # noqa: PLC0415
        import tempfile  # noqa: PLC0415
        try:
            from utils.resources import get_ffmpeg_path  # noqa: PLC0415
            ffmpeg = get_ffmpeg_path()
        except (FileNotFoundError, Exception):  # noqa: BLE001
            ffmpeg = None
        if not ffmpeg:
            # ffmpeg 없으면 병합 불가 → 즉시 스트리밍으로 폴백(보통 360p)
            self._run_stream(yt_dlp)
            return

        clients = _STREAM_CLIENTS if _is_youtube(self._url) else (None,)
        for client in clients:
            tmpdir = tempfile.mkdtemp(prefix="ovc_stream_")
            opts = {
                "quiet": True, "no_warnings": True, "noplaylist": True,
                "format": self._quality_fmt,
                "merge_output_format": "mp4",
                "outtmpl": os.path.join(tmpdir, "stream.%(ext)s"),
                "ffmpeg_location": ffmpeg,
                "progress_hooks": [self._merge_hook],
            }
            if client:
                opts["extractor_args"] = {"youtube": {"player_client": [client]}}
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(self._url, download=True) or {}
                rd = (info.get("requested_downloads") or [{}])[0]
                path = rd.get("filepath") or info.get("filepath") or ydl.prepare_filename(info)
                if not path or not os.path.exists(path):
                    # 병합 산출물을 못 찾으면 디렉터리에서 첫 파일을 집는다
                    files = [os.path.join(tmpdir, f) for f in os.listdir(tmpdir)]
                    path = files[0] if files else ""
            except Exception as exc:
                logger.warning(
                    "고화질 병합 실패(client=%s): %s", client or "기본", str(exc)[:200]
                )
                continue
            if path and os.path.exists(path):
                if client:
                    logger.info("대체 클라이언트로 고화질 병합 성공: client=%s", client)
                h = rd.get("height") or info.get("height")
                self.stream_ready.emit(path, f"{h}p" if h else "", True)
                return
        # 고화질을 못 만들었다고 재생 자체를 포기하지 않는다 — 낮은 화질이라도 트는 편이
        # 브라우저로 튕기는 것보다 낫다(사용자는 '앱에서 재생'을 원해서 누른 것이다).
        logger.warning("고화질 병합 전부 실패 — 일반 스트리밍으로 폴백: %s", self._url)
        self._quality_fmt = _DEFAULT_QUALITY_FMT
        self._run_stream(yt_dlp)

    def _merge_hook(self, d: dict) -> None:
        if d.get("status") != "downloading":
            return
        try:
            pct = str(d.get("_percent_str") or "0").strip().rstrip("%")
            self.progress.emit(int(float(pct or 0)))
        except (ValueError, TypeError):
            pass

class _FormatProbeWorker(QThread):
    """영상이 실제로 제공하는 화질(세로 해상도) 목록을 조회한다.

    화질 메뉴를 고정 목록으로 두면 최대 1080p인 영상에도 4K가 뜬다. 다운로드
    포맷 문자열은 `height<=N` 이라 실제 최대치를 넘는 선택지는 같은 파일을
    받으므로 무의미하다. yt-dlp 호출이라 반드시 백그라운드에서 실행한다.
    """

    heights_ready = pyqtSignal(str, list)   # (url, 내림차순 높이 목록)
    failed        = pyqtSignal(str)

    def __init__(self, url: str, parent=None) -> None:
        super().__init__(parent)
        self._url = url

    def run(self) -> None:
        try:
            import yt_dlp  # noqa: PLC0415

            opts = {"quiet": True, "no_warnings": True, "noplaylist": True}
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(self._url, download=False) or {}
            heights = sorted(
                {
                    int(f["height"])
                    for f in (info.get("formats") or [])
                    if f.get("height") and f.get("vcodec") not in (None, "none")
                },
                reverse=True,
            )
            if not heights and info.get("height"):
                heights = [int(info["height"])]
            self.heights_ready.emit(self._url, heights)
        except Exception as exc:
            # 네트워크·추출 실패는 치명적이지 않다 — 호출측이 전체 목록으로 폴백한다.
            logger.warning("사용 가능한 화질 조회 실패(%s): %s", self._url, exc)
            self.failed.emit(str(exc))

def _cache_heights(url: str, heights: list[int]) -> None:
    if not url:
        return
    _HEIGHT_CACHE[url] = heights
    _HEIGHT_CACHE.move_to_end(url)
    while len(_HEIGHT_CACHE) > _HEIGHT_CACHE_MAX:
        _HEIGHT_CACHE.popitem(last=False)



# ── 영상 자막(YouTube 캡션) 워커 ──────────────────────────────────────────────
# 목록 조회(yt-dlp)와 파일 내려받기(HTTP) 둘 다 네트워크라 QThread에서 한다.
# 실패는 조용히 빈 결과로 돌려보낸다 — 자막이 없다고 재생을 막을 이유는 없다.

# 영상별 자막 목록 캐시 — 같은 영상을 다시 열 때 yt-dlp 조회를 되풀이하지 않는다.
_VSUB_LIST_CACHE: "OrderedDict[str, list]" = OrderedDict()
_VSUB_LIST_CACHE_MAX = 32


class _SubtitleListWorker(QThread):
    """이 영상이 제공하는 자막 트랙 목록을 조회한다."""

    done = pyqtSignal(str, list)   # (video_url, tracks)

    def __init__(self, url: str, cookie_opts: dict | None = None, parent=None) -> None:
        super().__init__(parent)
        self._url = url
        self._cookie_opts = cookie_opts or {}

    def run(self) -> None:
        from infrastructure.subtitle.youtube_subtitles import (  # noqa: PLC0415
            fetch_tracks_for_url,
        )
        try:
            tracks = fetch_tracks_for_url(self._url, self._cookie_opts)
        except Exception as exc:
            logger.warning("자막 목록 조회 실패: %s", exc)
            tracks = []
        while len(_VSUB_LIST_CACHE) >= _VSUB_LIST_CACHE_MAX:
            _VSUB_LIST_CACHE.popitem(last=False)
        _VSUB_LIST_CACHE[self._url] = tracks
        self.done.emit(self._url, tracks)


class _SubtitleFetchWorker(QThread):
    """고른 트랙의 자막 파일을 내려받아 큐 목록으로 돌려준다."""

    done = pyqtSignal(int, str, list)   # (slot, track_key, cues)

    def __init__(self, slot: int, track, parent=None) -> None:
        super().__init__(parent)
        self._slot = slot
        self._track = track

    def run(self) -> None:
        from infrastructure.subtitle.youtube_subtitles import fetch_cues  # noqa: PLC0415
        try:
            cues = fetch_cues(self._track)
        except Exception as exc:
            logger.warning("자막 내려받기 실패: %s", exc)
            cues = []
        # key 는 '번역 전' 기준이어야 선택 상태와 맞는다(번역은 같은 트랙의 변형이다).
        base_key = f"{'auto' if self._track.auto else 'sub'}:{self._track.lang}:"
        self.done.emit(self._slot, base_key, cues)
