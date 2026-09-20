"""고화질 스트림을 **내려받지 않고** 재생하기 위한 로컬 중계 + 실시간 remux.

왜 중계가 필요한가 — 실측으로 확인한 두 가지 제약 때문이다.

1. **googlevideo는 '열린 Range'를 거부한다.** 같은 1080p URL에
   `Range: bytes=0-`(열린 범위)를 보내면 **403**, `Range: bytes=0-1000`(경계 있는
   범위)을 보내면 206을 준다. 그런데 ffmpeg는 파일을 열 때 정확히 열린 범위를
   보낸다(`gui/widgets/player/constants.py`의 `_PROBE_RANGE` 주석과 같은 현상이다).
   그래서 고화질 URL을 Qt(FFmpeg 백엔드)에 그냥 넘기면 **항상** 403이다.
2. **요청당 허용 바이트 상한이 포맷마다 다르다.** 실측: 1080p(itag 137)는 2MB
   요청에 206을 주지만, 오디오(itag 140)는 2MB에 403, 128KB에 206을 준다.
   비트레이트에 비례하는 상한으로 보인다 — 조각을 작게 끊어야 한다.

그래서 이 모듈은 재생기의 '열린 범위' 요청을 받아, 상위로는 **경계 있는 작은
조각**으로 되묻어 이어 붙인다. 재생기 입장에서는 평범한 로컬 파일처럼 보인다.

YouTube 고화질은 영상과 오디오가 분리돼 있으므로(muxed 포맷은 360p 하나뿐이다)
`/play.mp4`가 ffmpeg를 띄워 둘을 **실시간으로 remux** 해 fragmented mp4로 흘린다.
전체를 받아 두고 재생하는 기존 경로(`_run_merge`)와 달리 첫 프레임까지 1초 안쪽이다.

**seek은 재생기가 못 한다.** 파이프로 흘리는 fragmented mp4는 길이도 없고 되감기도
안 되므로, 호출측(`InlinePlayer`)이 `?ss=` 로 **새 연결을 여는 방식**으로 seek 한다.
ffmpeg의 `-ss`는 입력 앞에 두면 HTTP Range로 건너뛰므로 빠르다.
"""

from __future__ import annotations

import atexit
import logging
import re
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable
from urllib.parse import parse_qs, urlparse

logger = logging.getLogger(__name__)

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

# 상위에 처음 요청할 조각 크기. 영상은 크게, 오디오는 작게 시작한다 — 위 2번 제약
# 때문에 오디오를 크게 부르면 403을 맞고 줄여 가느라 첫 소리가 늦어진다.
_CHUNK_VIDEO = 1024 * 1024
_CHUNK_AUDIO = 128 * 1024
# 더 줄여도 소용없는 바닥. 여기서도 403이면 URL이 만료된 것으로 보고 갱신을 시도한다.
# 원본이 허용하는 상한을 모르므로 넉넉히 낮게 잡는다 — 바닥이 실제 상한보다 높으면
# 어떤 조각도 통하지 않아 그 포맷을 영영 못 받는다.
_CHUNK_MIN = 16 * 1024

_UPSTREAM_TIMEOUT = (5, 20)

# 통하던 크기가 거부됐을 때 쉬는 시간(초). 짧게 시작해 늘린다 — 재생 중이라
# 오래 멈추면 화면이 먼저 멎는다.
_RETRY_DELAYS = (0.25, 0.75, 2.0)

# 중계가 조각 하나를 못 채우면 연결을 끊는다. 이 옵션이 없으면 ffmpeg가 거기서
# 통째로 죽어 재생이 끝난 것처럼 보인다 — 끊긴 자리에서 스스로 다시 붙게 한다.
_RECONNECT = [
    "-reconnect", "1",
    "-reconnect_streamed", "1",
    "-reconnect_on_network_error", "1",
    "-reconnect_delay_max", "5",
]

_RANGE_RE = re.compile(r"bytes=(\d+)-(\d*)")


def parse_range(header: str, total: int) -> tuple[int, int]:
    """`Range` 헤더를 (start, end) 바이트 쌍으로 푼다. 없거나 깨졌으면 전체 범위.

    end는 **포함**(inclusive)이다 — HTTP Range의 의미 그대로다.
    """
    last = max(0, total - 1)
    m = _RANGE_RE.match(header or "")
    if not m:
        return 0, last
    start = int(m.group(1))
    end = int(m.group(2)) if m.group(2) else last
    return min(start, last), min(end, last)


def shrink_chunk(current: int) -> int:
    """403을 맞았을 때 다음에 시도할 조각 크기. 바닥에 닿으면 그대로 돌려준다."""
    return max(_CHUNK_MIN, current // 2)


def build_ffmpeg_cmd(
    ffmpeg: str, video_url: str, audio_url: str | None, start_sec: float
) -> list[str]:
    """영상(+오디오)을 fragmented mp4로 실시간 remux 하는 ffmpeg 명령.

    `-ss`를 **입력 앞**에 둔다(입력 seek) — 출력 seek과 달리 HTTP Range로 건너뛰므로
    앞부분을 통째로 읽지 않는다. `-copyts`는 쓰지 않는다: 출력 타임스탬프가 0부터
    시작해야 재생기의 위치에 호출측이 오프셋을 더하는 계산이 성립한다.

    `-c copy`라 재인코딩이 없다(저사양 PC 제약 — CPU를 쓰지 않는다).
    """
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error"]
    cmd += _RECONNECT + (["-ss", f"{start_sec:.3f}"] if start_sec > 0 else [])
    cmd += ["-i", video_url]
    if audio_url:
        cmd += _RECONNECT + (["-ss", f"{start_sec:.3f}"] if start_sec > 0 else [])
        cmd += ["-i", audio_url, "-map", "0:v:0", "-map", "1:a:0"]
    cmd += [
        "-c", "copy",
        # empty_moov + frag_keyframe: 길이를 모르는 상태로 첫 프레임부터 흘릴 수 있다.
        # default_base_moof 가 없으면 일부 디먹서가 조각 오프셋을 잘못 읽는다.
        "-movflags", "frag_keyframe+empty_moov+default_base_moof",
        "-f", "mp4", "pipe:1",
    ]
    return cmd


@dataclass
class StreamSource:
    """중계할 원본 하나(영상 또는 오디오)."""

    url: str
    headers: dict[str, str] = field(default_factory=dict)
    size: int = 0
    chunk: int = _CHUNK_VIDEO
    # 한 번이라도 통한 크기인가. 이 구분이 없으면 **일시적 거부를 크기 문제로
    # 오해해** 조각을 계속 줄이고, 조각이 작아질수록 요청이 잦아져 거부가 더 심해진다
    # (실측: seek 첫 바이트가 1초대에서 22초로 나빠졌다).
    proven: bool = False

    def clone_from(self, other: "StreamSource") -> None:
        """URL 갱신 — 조각 크기는 이미 학습한 값을 유지한다(다시 더듬지 않는다)."""
        self.url = other.url
        self.headers = other.headers
        if other.size:
            self.size = other.size


@dataclass
class RelaySession:
    """한 편의 영상 재생에 필요한 원본들과 길이."""

    sid: str
    video: StreamSource
    audio: StreamSource | None = None
    duration_ms: int = 0
    ffmpeg: str = ""
    # 상위 URL이 만료돼 바닥 조각 크기에서도 403일 때 새 URL을 받아오는 콜백.
    # yt-dlp 호출이라 인프라 계층에 두지 않고 호출측(gui 워커)이 주입한다.
    refresh: Callable[[], tuple[StreamSource, StreamSource | None]] | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def source(self, kind: str) -> StreamSource | None:
        return self.video if kind == "v" else self.audio

    def try_refresh(self) -> bool:
        """URL을 새로 받아온다. 동시에 여러 연결이 부르므로 잠금으로 한 번만."""
        if self.refresh is None:
            return False
        with self._lock:
            try:
                video, audio = self.refresh()
            except Exception:
                logger.exception("스트림 URL 갱신 실패")
                return False
            self.video.clone_from(video)
            if self.audio is not None and audio is not None:
                self.audio.clone_from(audio)
            logger.info("스트림 URL 갱신 성공(sid=%s)", self.sid)
            return True


class _Handler(BaseHTTPRequestHandler):
    """재생기 ↔ 원본 사이의 중계. 서버 인스턴스가 `relay`를 들고 있다."""

    protocol_version = "HTTP/1.1"
    server_version = "OVCRelay/1.0"

    def log_message(self, *args) -> None:  # noqa: D102 - 기본 stderr 로깅을 끈다
        pass

    # ── 라우팅 ────────────────────────────────────────────────────
    def do_GET(self) -> None:  # noqa: N802 (BaseHTTPRequestHandler 규약)
        self._dispatch(body=True)

    def do_HEAD(self) -> None:  # noqa: N802
        self._dispatch(body=False)

    def _dispatch(self, body: bool) -> None:
        parsed = urlparse(self.path)
        parts = [p for p in parsed.path.split("/") if p]
        # /s/<sid>/v | /s/<sid>/a | /s/<sid>/play.mp4
        if len(parts) != 3 or parts[0] != "s":
            self.send_error(404)
            return
        session = self.server.relay.session(parts[1])  # type: ignore[attr-defined]
        if session is None:
            self.send_error(404)
            return
        if parts[2] in ("v", "a"):
            self._serve_source(session, parts[2], body)
        elif parts[2] == "play.mp4":
            self._serve_remux(session, parsed.query, body)
        else:
            self.send_error(404)

    # ── 원본 중계: 열린 Range 요청을 경계 있는 조각들로 바꿔 채운다 ──
    def _serve_source(self, session: RelaySession, kind: str, body: bool) -> None:
        src = session.source(kind)
        if src is None or not src.size:
            self.send_error(404)
            return
        rng = self.headers.get("Range", "")
        start, end = parse_range(rng, src.size)
        self.send_response(206 if rng else 200)
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        if rng:
            self.send_header("Content-Range", f"bytes {start}-{end}/{src.size}")
        self.end_headers()
        if body:
            self._pump_source(session, src, start, end)

    def _pump_source(
        self, session: RelaySession, src: StreamSource, start: int, end: int
    ) -> None:
        import requests  # noqa: PLC0415 (시작 성능 — 재생할 때만 끌어온다)

        pos = start
        refreshed = False
        backoff = 0
        with requests.Session() as http:
            while pos <= end:
                stop = min(pos + src.chunk - 1, end)
                try:
                    resp = http.get(
                        src.url,
                        headers={**src.headers, "Range": f"bytes={pos}-{stop}"},
                        stream=True,
                        timeout=_UPSTREAM_TIMEOUT,
                    )
                except Exception:
                    logger.warning("원본 조각 요청 실패(pos=%d)", pos, exc_info=True)
                    return
                if resp.status_code not in (200, 206):
                    resp.close()
                    smaller = shrink_chunk(src.chunk)
                    if not src.proven and smaller < src.chunk:
                        # 이 크기로 아직 한 번도 성공하지 못했다 = 상한을 모른다.
                        # 줄여서 다시 묻는다. 성공하면 그 값이 남아 다시 더듬지 않는다.
                        src.chunk = smaller
                        continue
                    if backoff < len(_RETRY_DELAYS):
                        # 통하던 크기인데 거부됐다 = 일시적 거부(속도 제한)다.
                        # 줄이면 요청이 더 잦아져 악화된다 — 잠깐 쉬었다 같은 크기로.
                        time.sleep(_RETRY_DELAYS[backoff])
                        backoff += 1
                        continue
                    if not refreshed and session.try_refresh():
                        # 쉬어도 안 되면 크기 문제가 아니다(URL 만료).
                        refreshed = True
                        backoff = 0
                        continue
                    logger.warning(
                        "원본이 조각을 거부함(status=%s, pos=%d) — 중계 중단",
                        resp.status_code, pos,
                    )
                    # Content-Length 를 이미 약속했으므로 조용히 돌아가면 재생기가
                    # 남은 바이트를 **영원히 기다린다**(실측: 요청이 타임아웃까지 멈춤).
                    # 연결을 끊어 "끊겼다"를 즉시 알린다 — 그래야 상위가 재시도한다.
                    self.close_connection = True
                    return
                try:
                    for block in resp.iter_content(64 * 1024):
                        self.wfile.write(block)
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
                    # 재생기가 연결을 끊었다(seek·정지). 정상 종료 경로다.
                    return
                finally:
                    resp.close()
                src.proven = True
                backoff = 0
                pos = stop + 1

    # ── 실시간 remux: 두 중계 URL을 ffmpeg로 합쳐 그대로 흘린다 ──
    def _serve_remux(self, session: RelaySession, query: str, body: bool) -> None:
        if not session.ffmpeg:
            self.send_error(503, "ffmpeg not available")
            return
        try:
            start_sec = float((parse_qs(query).get("ss") or ["0"])[0])
        except ValueError:
            start_sec = 0.0
        base = f"http://127.0.0.1:{self.server.server_address[1]}/s/{session.sid}"
        audio_url = f"{base}/a" if session.audio else None
        cmd = build_ffmpeg_cmd(session.ffmpeg, f"{base}/v", audio_url, start_sec)

        # 길이를 모르는 스트림이다 — Content-Length 없이 연결을 닫아 끝을 알린다.
        # (재생기는 이 소스를 seek 불가로 보고, seek은 호출측이 ?ss= 로 처리한다.)
        self.send_response(200)
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Accept-Ranges", "none")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.close_connection = True
        self.end_headers()
        if not body:
            return

        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=_NO_WINDOW
        )
        relay: StreamRelay = self.server.relay  # type: ignore[attr-defined]
        relay.track_process(proc)
        # stderr를 읽어 주지 않으면 ffmpeg가 파이프를 채우고 멈춘다.
        errbuf: list[bytes] = []
        threading.Thread(
            target=lambda: errbuf.append(proc.stderr.read() or b""), daemon=True
        ).start()
        try:
            while True:
                block = proc.stdout.read(64 * 1024)
                if not block:
                    break
                self.wfile.write(block)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            pass    # 재생기가 끊었다 — seek이나 정지. 아래에서 ffmpeg를 정리한다.
        finally:
            relay.kill_process(proc)
            err = (errbuf[0] if errbuf else b"").decode("utf-8", "replace").strip()
            if err:
                logger.warning("remux ffmpeg: %s", err[:500])


class StreamRelay:
    """127.0.0.1에 뜬 중계 서버 한 개. 앱 수명 동안 하나면 된다."""

    def __init__(self) -> None:
        self._server: ThreadingHTTPServer | None = None
        self._sessions: dict[str, RelaySession] = {}
        self._procs: set[subprocess.Popen] = set()
        self._lock = threading.Lock()

    # ── 수명 ────────────────────────────────────────────────────
    def start(self) -> int:
        """서버를 띄우고 포트를 돌려준다. 이미 떠 있으면 그 포트."""
        with self._lock:
            if self._server is not None:
                return self._server.server_address[1]
            ThreadingHTTPServer.allow_reuse_address = True
            server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
            server.daemon_threads = True
            server.relay = self         # type: ignore[attr-defined]
            self._server = server
            threading.Thread(
                target=server.serve_forever, name="stream-relay", daemon=True
            ).start()
            port = server.server_address[1]
        logger.info("스트림 중계 서버 시작 — 127.0.0.1:%d", port)
        return port

    def shutdown(self) -> None:
        """서버와 남은 ffmpeg를 모두 정리한다(앱 종료 시)."""
        with self._lock:
            server, self._server = self._server, None
            procs, self._procs = set(self._procs), set()
            self._sessions.clear()
        for proc in procs:
            self._terminate(proc)
        if server is not None:
            server.shutdown()
            server.server_close()

    # ── 세션 ────────────────────────────────────────────────────
    def open_session(
        self,
        video: StreamSource,
        audio: StreamSource | None,
        duration_ms: int,
        ffmpeg: str,
        refresh: Callable[[], tuple[StreamSource, StreamSource | None]] | None = None,
    ) -> str:
        """재생 URL을 만들 세션을 등록하고 재생 URL을 돌려준다."""
        port = self.start()
        sid = uuid.uuid4().hex[:12]
        video.chunk = _CHUNK_VIDEO
        if audio is not None:
            audio.chunk = _CHUNK_AUDIO
        with self._lock:
            self._sessions[sid] = RelaySession(
                sid=sid, video=video, audio=audio,
                duration_ms=duration_ms, ffmpeg=ffmpeg, refresh=refresh,
            )
        return f"http://127.0.0.1:{port}/s/{sid}/play.mp4"

    def close_session(self, play_url: str) -> None:
        """세션을 지운다 — 이후 요청은 404가 되어 남은 ffmpeg가 스스로 끝난다."""
        sid = self.sid_of(play_url)
        if not sid:
            return
        with self._lock:
            self._sessions.pop(sid, None)

    @staticmethod
    def sid_of(play_url: str) -> str:
        parts = [p for p in urlparse(play_url).path.split("/") if p]
        return parts[1] if len(parts) >= 2 and parts[0] == "s" else ""

    def session(self, sid: str) -> RelaySession | None:
        with self._lock:
            return self._sessions.get(sid)

    # ── ffmpeg 프로세스 ──────────────────────────────────────────
    def track_process(self, proc: subprocess.Popen) -> None:
        with self._lock:
            self._procs.add(proc)

    def kill_process(self, proc: subprocess.Popen) -> None:
        with self._lock:
            self._procs.discard(proc)
        self._terminate(proc)

    @staticmethod
    def _terminate(proc: subprocess.Popen) -> None:
        """`-c copy`라도 네트워크를 물고 있으므로 확실히 죽인다.

        `terminate()`만 보내고 기다리지 않으면 ffmpeg가 좀비로 남아 상위 대역폭을
        계속 먹는다(seek을 반복하면 금세 여러 개가 쌓인다).
        """
        if proc.poll() is not None:
            return
        try:
            proc.kill()
            proc.wait(timeout=3)
        except Exception:
            logger.debug("remux ffmpeg 종료 실패", exc_info=True)


_RELAY: StreamRelay | None = None
_RELAY_LOCK = threading.Lock()


def get_relay() -> StreamRelay:
    """앱 전역 중계 서버. 처음 재생할 때 만들어진다(시작 성능을 건드리지 않는다)."""
    global _RELAY
    with _RELAY_LOCK:
        if _RELAY is None:
            _RELAY = StreamRelay()
            atexit.register(_RELAY.shutdown)
        return _RELAY
