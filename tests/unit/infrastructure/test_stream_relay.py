"""재생용 스트림 중계 — 열린 Range를 거부하는 원본을 실제로 메우는지 확인한다.

이 모듈의 존재 이유가 곧 시험 대상이다: googlevideo는 `Range: bytes=0-`에 403을,
경계 있는 범위에는 206을 준다(실측). 게다가 **요청당 허용 크기가 포맷마다 다르다**
(1080p는 2MB 허용, 오디오는 2MB 거부 / 128KB 허용). 그래서 여기서는 그 성질을
그대로 흉내 내는 가짜 원본을 띄우고, 중계가 전체 바이트를 정확히 복원하는지 본다.

값만 확인하는 시험으로는 이 경로를 밟지 못한다 — 실제로 HTTP를 주고받아야 한다.
"""

from __future__ import annotations

import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

requests = pytest.importorskip("requests")

from infrastructure.streaming.relay import (  # noqa: E402
    StreamRelay,
    StreamSource,
    build_ffmpeg_cmd,
    parse_range,
    shrink_chunk,
)

# 가짜 원본이 내줄 내용 — 어디가 어긋나도 눈에 띄도록 위치마다 값이 다르게 만든다.
_PAYLOAD = bytes((i * 7 + 13) % 251 for i in range(300_000))


class _PickyUpstream(BaseHTTPRequestHandler):
    """googlevideo를 흉내 낸다: 열린 범위 거부 + 요청당 크기 상한."""

    protocol_version = "HTTP/1.1"
    max_chunk = 32 * 1024     # 이보다 큰 요청은 403
    seen: list = []

    def log_message(self, *args) -> None:
        pass

    def do_GET(self) -> None:  # noqa: N802
        if self.path != "/media":
            type(self).seen.append(("expired", self.path))
            self.send_error(403)      # 만료된 URL을 흉내 낸다
            return
        rng = self.headers.get("Range", "")
        m = re.match(r"bytes=(\d+)-(\d+)$", rng)   # 끝이 없는 '열린 범위'는 매치되지 않는다
        if not m:
            type(self).seen.append(("open", rng))
            self.send_error(403)
            return
        start, end = int(m.group(1)), int(m.group(2))
        if end - start + 1 > type(self).max_chunk:
            type(self).seen.append(("toobig", end - start + 1))
            self.send_error(403)
            return
        body = _PAYLOAD[start : end + 1]
        type(self).seen.append(("ok", start, len(body)))
        self.send_response(206)
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Range", f"bytes {start}-{end}/{len(_PAYLOAD)}")
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture()
def upstream():
    _PickyUpstream.seen = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _PickyUpstream)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}/media"
    server.shutdown()
    server.server_close()


@pytest.fixture()
def relay():
    r = StreamRelay()
    yield r
    r.shutdown()


class TestParseRange:
    def test_열린_범위는_끝까지(self):
        assert parse_range("bytes=100-", 1000) == (100, 999)

    def test_경계_있는_범위(self):
        assert parse_range("bytes=10-20", 1000) == (10, 20)

    def test_헤더가_없으면_전체(self):
        assert parse_range("", 1000) == (0, 999)

    def test_끝을_넘기면_잘린다(self):
        assert parse_range("bytes=0-99999", 1000) == (0, 999)

    def test_빈_내용도_음수를_내지_않는다(self):
        assert parse_range("", 0) == (0, 0)


class TestShrinkChunk:
    def test_절반으로_줄인다(self):
        assert shrink_chunk(1024 * 1024) == 512 * 1024

    def test_바닥_아래로는_내려가지_않는다(self):
        floor = shrink_chunk(1)
        assert shrink_chunk(floor) == floor


class TestBuildFfmpegCmd:
    def test_ss는_입력_앞에_온다(self):
        """출력 seek이 되면 앞부분을 통째로 읽어 seek이 느려진다."""
        cmd = build_ffmpeg_cmd("ffmpeg", "http://v", "http://a", 12.5)
        assert cmd.index("-ss") < cmd.index("-i")
        assert cmd[cmd.index("-ss") + 1] == "12.500"

    def test_끊긴_입력에_다시_붙는다(self):
        """중계가 조각을 놓치면 연결이 끊긴다 — 여기서 ffmpeg가 죽으면 재생이 끝난다."""
        cmd = build_ffmpeg_cmd("ffmpeg", "http://v", "http://a", 0)
        assert cmd.count("-reconnect") == 2       # 영상·오디오 둘 다
        assert "-reconnect_on_network_error" in cmd

    def test_처음부터면_ss가_없다(self):
        assert "-ss" not in build_ffmpeg_cmd("ffmpeg", "http://v", "http://a", 0)

    def test_오디오가_있으면_양쪽을_map_한다(self):
        cmd = build_ffmpeg_cmd("ffmpeg", "http://v", "http://a", 0)
        assert "0:v:0" in cmd and "1:a:0" in cmd

    def test_muxed_단일_입력이면_map을_걸지_않는다(self):
        """map을 걸면 muxed 입력에서 오디오가 떨어져 나가 무음이 된다."""
        cmd = build_ffmpeg_cmd("ffmpeg", "http://v", None, 0)
        assert "-map" not in cmd

    def test_재인코딩하지_않는다(self):
        """저사양 PC가 목표다 — 트랜스코딩이 끼면 CPU가 버티지 못한다."""
        cmd = build_ffmpeg_cmd("ffmpeg", "http://v", None, 0)
        assert cmd[cmd.index("-c") + 1] == "copy"


class TestRelayFillsBoundedChunks:
    """중계의 존재 이유 — 열린 범위 요청을 경계 있는 조각들로 메운다."""

    def _play_base(self, relay: StreamRelay, upstream: str) -> str:
        play_url = relay.open_session(
            StreamSource(url=upstream, size=len(_PAYLOAD)), None,
            duration_ms=1000, ffmpeg="",
        )
        return play_url.rsplit("/", 1)[0]

    def test_열린_범위_요청을_전부_채운다(self, relay, upstream):
        base = self._play_base(relay, upstream)
        resp = requests.get(f"{base}/v", headers={"Range": "bytes=0-"}, timeout=30)
        assert resp.status_code == 206
        assert resp.content == _PAYLOAD

    def test_상한을_넘으면_조각을_줄여_다시_묻는다(self, relay, upstream):
        """처음엔 1MB로 묻는다 — 403을 맞고 줄여 가며 통하는 크기를 찾아야 한다."""
        base = self._play_base(relay, upstream)
        requests.get(f"{base}/v", headers={"Range": "bytes=0-"}, timeout=30)
        assert any(kind == "toobig" for kind, *_ in _PickyUpstream.seen)
        # 한 번 찾은 크기는 기억한다 — 조각마다 다시 더듬으면 재생이 끊긴다.
        assert sum(1 for kind, *_ in _PickyUpstream.seen if kind == "toobig") <= 6

    def test_중간부터_요청해도_어긋나지_않는다(self, relay, upstream):
        base = self._play_base(relay, upstream)
        resp = requests.get(
            f"{base}/v", headers={"Range": "bytes=100000-150000"}, timeout=30
        )
        assert resp.status_code == 206
        assert resp.content == _PAYLOAD[100_000:150_001]
        assert resp.headers["Content-Range"] == f"bytes 100000-150000/{len(_PAYLOAD)}"

    def test_원본_응답은_연결을_닫는다(self, relay, upstream):
        """keep-alive면 ffmpeg가 seek마다 남은 응답을 전부 읽어 비운다(실측 20초+)."""
        base = self._play_base(relay, upstream)
        # 가짜 원본이 큰 요청을 403하므로 둘 다 작은 범위로 묻는다(206 경로 확인).
        for rng in ("bytes=0-1000", "bytes=2000-3000"):
            resp = requests.get(f"{base}/v", headers={"Range": rng}, timeout=30)
            assert resp.headers.get("Connection", "").lower() == "close"

    def test_세션을_닫으면_더는_흘리지_않는다(self, relay, upstream):
        play_url = relay.open_session(
            StreamSource(url=upstream, size=len(_PAYLOAD)), None,
            duration_ms=1000, ffmpeg="",
        )
        relay.close_session(play_url)
        base = play_url.rsplit("/", 1)[0]
        assert requests.get(f"{base}/v", timeout=10).status_code == 404


class _FakeProc:
    """Popen 흉내 — poll()/kill()/wait() 호출만 기록한다."""

    def __init__(self, finished: bool = False) -> None:
        self.finished = finished
        self.killed = False

    def poll(self):
        return 0 if (self.finished or self.killed) else None

    def kill(self) -> None:
        self.killed = True

    def wait(self, timeout=None) -> int:
        return 0


class TestPeerConnected:
    """ffmpeg→중계 연결이 아직 살아 있는지 — abort 여부를 가르는 판정."""

    def test_열린_소켓쌍은_살아_있다(self):
        import socket

        from infrastructure.streaming.relay import is_peer_connected

        a, b = socket.socketpair()
        try:
            assert is_peer_connected(a) is True
        finally:
            a.close()
            b.close()

    def test_상대가_닫으면_죽었다(self):
        import socket

        from infrastructure.streaming.relay import is_peer_connected

        a, b = socket.socketpair()
        b.close()
        try:
            assert is_peer_connected(a) is False
        finally:
            a.close()

    def test_판단_불가면_살아_있다고_보지_않는다(self):
        """닫힌 소켓 객체처럼 검사 자체가 실패하면 abort 하지 않는 쪽이 안전하다."""
        import socket

        from infrastructure.streaming.relay import is_peer_connected

        a, b = socket.socketpair()
        a.close()
        b.close()
        assert is_peer_connected(a) is False


class TestAbortRemux:
    def test_등록된_프로세스를_죽인다(self):
        from infrastructure.streaming.relay import RelaySession

        s = RelaySession(sid="x", video=StreamSource(url="http://v"))
        running, done = _FakeProc(), _FakeProc(finished=True)
        s.register_proc(running)
        s.register_proc(done)
        s.abort_remux()
        assert running.killed is True
        assert done.killed is False

    def test_해제한_프로세스는_건드리지_않는다(self):
        from infrastructure.streaming.relay import RelaySession

        s = RelaySession(sid="x", video=StreamSource(url="http://v"))
        p = _FakeProc()
        s.register_proc(p)
        s.unregister_proc(p)
        s.abort_remux()
        assert p.killed is False


class TestRelayAbortsRemuxOnRejection:
    """원본이 영구 거부하면 반쪽 스트림이 남지 않도록 remux를 끝낸다."""

    def test_영구_거부되면_세션의_ffmpeg를_죽인다(self, relay, upstream, monkeypatch):
        import infrastructure.streaming.relay as relay_mod

        monkeypatch.setattr(relay_mod, "_RETRY_DELAYS", (0.0, 0.0))
        dead = upstream.replace("/media", "/dead")   # 항상 403
        play_url = relay.open_session(
            StreamSource(url=dead, size=len(_PAYLOAD)), None,
            duration_ms=1000, ffmpeg="",
        )
        sid = relay.sid_of(play_url)
        proc = _FakeProc()
        relay.session(sid).register_proc(proc)
        base = play_url.rsplit("/", 1)[0]
        try:
            requests.get(f"{base}/v", headers={"Range": "bytes=0-1000"}, timeout=30)
        except requests.RequestException:
            pass    # 약속한 길이를 못 채우고 끊긴다 — 정상
        assert proc.killed is True

    def test_클라이언트가_이미_끊겼으면_죽이지_않는다(self, relay, upstream, monkeypatch):
        """seek으로 끊긴 옛 연결의 펌프가 새 ffmpeg를 죽이면 안 된다."""
        import infrastructure.streaming.relay as relay_mod

        monkeypatch.setattr(relay_mod, "_RETRY_DELAYS", (0.0, 0.0))
        monkeypatch.setattr(relay_mod, "is_peer_connected", lambda sock: False)
        dead = upstream.replace("/media", "/dead")
        play_url = relay.open_session(
            StreamSource(url=dead, size=len(_PAYLOAD)), None,
            duration_ms=1000, ffmpeg="",
        )
        proc = _FakeProc()
        relay.session(relay.sid_of(play_url)).register_proc(proc)
        base = play_url.rsplit("/", 1)[0]
        try:
            requests.get(f"{base}/v", headers={"Range": "bytes=0-1000"}, timeout=30)
        except requests.RequestException:
            pass
        assert proc.killed is False


class TestRelayRefresh:
    """URL 만료 — 바닥 조각 크기에서도 거부되면 새 URL을 받아 이어 간다."""

    def test_만료된_URL을_갱신해_이어받는다(self, relay, upstream):
        dead = upstream.replace("/media", "/dead")
        calls = {"n": 0}

        def refresh():
            calls["n"] += 1
            return StreamSource(url=upstream, size=len(_PAYLOAD)), None

        # 항상 403을 주는 원본으로 시작한다(경로가 달라 가짜 서버가 404/403을 낸다).
        play_url = relay.open_session(
            StreamSource(url=dead, size=len(_PAYLOAD)), None,
            duration_ms=1000, ffmpeg="", refresh=refresh,
        )
        base = play_url.rsplit("/", 1)[0]
        resp = requests.get(f"{base}/v", headers={"Range": "bytes=0-1000"}, timeout=30)
        assert calls["n"] == 1, "갱신 콜백이 불리지 않았다"
        assert resp.content == _PAYLOAD[:1001]
