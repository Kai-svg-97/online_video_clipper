"""업데이트 인스톨러 다운로드의 이어받기·재시도를 검증한다.

회귀 배경: 인스톨러가 130MB를 넘는데 API 조회용 타임아웃(10초)을 그대로 써서
네트워크가 잠깐만 정체돼도 `Read timed out` 으로 끊겼다. 재시도가 없어 한 번
실패하면 그 세션에서는 업데이트가 영영 진행되지 않았다(실제 로그로 확인).
"""
from __future__ import annotations

import hashlib

import pytest
import requests

from domain.shared.ports import UpdateInfo
from infrastructure.updater import update_checker as uc
from infrastructure.updater.update_checker import GithubUpdateChecker

# 64KB 청크가 여러 번 나오도록 충분히 크게 — 중간에 끊기는 상황을 재현해야 한다.
PAYLOAD = b"installer-bytes" * 20_480        # 320 KB
SHA = hashlib.sha256(PAYLOAD).hexdigest()
URL = "https://objects.githubusercontent.com/YouTubeContentManager-setup.exe"


def _info(sha: str = SHA) -> UpdateInfo:
    return UpdateInfo(
        version="9.9.9",
        asset_name="YouTubeContentManager-setup.exe",
        download_url=URL,
        size_bytes=len(PAYLOAD),
        sha256=sha,
        release_notes="",
    )


class _Resp:
    """iter_content 도중 끊길 수 있는 가짜 응답."""

    def __init__(self, body: bytes, *, status: int = 200, cut_after: int | None = None):
        self._body = body
        self.status_code = status
        self._cut_after = cut_after
        self.headers = {"content-length": str(len(body))}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"status {self.status_code}")

    def iter_content(self, chunk_size: int = 1024):
        sent = 0
        for i in range(0, len(self._body), chunk_size):
            chunk = self._body[i : i + chunk_size]
            if self._cut_after is not None and sent >= self._cut_after:
                raise requests.ConnectionError("Read timed out.")
            yield chunk
            sent += len(chunk)


class _Session:
    """요청을 기록하고 미리 정해둔 응답을 돌려주는 가짜 세션."""

    def __init__(self, responses: list):
        self._responses = list(responses)
        self.calls: list[dict] = []

    def get(self, url, **kwargs):  # noqa: ANN001
        self.calls.append({"url": url, "headers": kwargs.get("headers") or {},
                           "timeout": kwargs.get("timeout")})
        resp = self._responses.pop(0)
        if isinstance(resp, Exception):
            raise resp
        return resp


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """재시도 백오프로 테스트가 느려지지 않도록."""
    monkeypatch.setattr(uc.time, "sleep", lambda _s: None)


class TestResume:
    def test_resumes_after_timeout(self, tmp_path):
        cut = 65_536 * 2
        first = _Resp(PAYLOAD, cut_after=cut)
        # 이어받기 응답은 206 + 남은 바이트
        rest = _Resp(PAYLOAD[cut:], status=206)
        sess = _Session([first, rest])
        checker = GithubUpdateChecker("1.0.0", session=sess)

        path = checker.download_asset(_info(), tmp_path)

        assert path.read_bytes() == PAYLOAD
        assert len(sess.calls) == 2
        assert sess.calls[0]["headers"] == {}
        assert sess.calls[1]["headers"] == {"Range": f"bytes={cut}-"}

    def test_uses_generous_read_timeout(self, tmp_path):
        sess = _Session([_Resp(PAYLOAD)])
        GithubUpdateChecker("1.0.0", session=sess).download_asset(_info(), tmp_path)
        connect, read = sess.calls[0]["timeout"]
        assert read >= 60, "인스톨러 다운로드에 API 조회용 짧은 타임아웃을 쓰면 안 된다"
        assert connect <= 15

    def test_server_ignoring_range_restarts_cleanly(self, tmp_path):
        cut = 65_536 * 2
        first = _Resp(PAYLOAD, cut_after=cut)
        # Range 를 무시하고 200 + 전체 본문을 준다
        full_again = _Resp(PAYLOAD, status=200)
        sess = _Session([first, full_again])
        checker = GithubUpdateChecker("1.0.0", session=sess)

        path = checker.download_asset(_info(), tmp_path)
        assert path.read_bytes() == PAYLOAD

    def test_gives_up_after_max_attempts(self, tmp_path):
        sess = _Session([requests.ConnectionError("boom")] * uc._DL_MAX_ATTEMPTS)
        checker = GithubUpdateChecker("1.0.0", session=sess)

        with pytest.raises(requests.RequestException):
            checker.download_asset(_info(), tmp_path)

        assert len(sess.calls) == uc._DL_MAX_ATTEMPTS
        assert list(tmp_path.iterdir()) == [], "실패 후 .part 가 남았다"

    def test_truncated_body_is_retried(self, tmp_path):
        """끊김 예외 없이 본문이 짧게 끝나도 완료로 처리하면 안 된다."""
        short = _Resp(PAYLOAD[:65_536])
        short.headers = {"content-length": str(len(PAYLOAD))}   # 서버는 전체 길이를 알림
        sess = _Session([short, _Resp(PAYLOAD[65_536:], status=206)])

        path = GithubUpdateChecker("1.0.0", session=sess).download_asset(_info(), tmp_path)
        assert path.read_bytes() == PAYLOAD


class TestIntegrity:
    def test_sha_mismatch_raises_and_cleans_up(self, tmp_path):
        sess = _Session([_Resp(PAYLOAD)])
        checker = GithubUpdateChecker("1.0.0", session=sess)

        with pytest.raises(RuntimeError, match="SHA-256"):
            checker.download_asset(_info(sha="0" * 64), tmp_path)
        assert list(tmp_path.iterdir()) == []

    def test_missing_sha_is_fail_closed(self, tmp_path):
        sess = _Session([_Resp(PAYLOAD)])
        checker = GithubUpdateChecker("1.0.0", session=sess)

        with pytest.raises(RuntimeError):
            checker.download_asset(_info(sha=""), tmp_path)
        assert list(tmp_path.iterdir()) == []

    def test_hash_is_computed_over_resumed_file(self, tmp_path):
        """이어받기로 여러 응답에 걸쳐 받아도 해시가 맞아야 한다."""
        cut = 65_536
        sess = _Session([
            _Resp(PAYLOAD, cut_after=cut),
            _Resp(PAYLOAD[cut:], status=206),
        ])
        path = GithubUpdateChecker("1.0.0", session=sess).download_asset(_info(), tmp_path)
        assert hashlib.sha256(path.read_bytes()).hexdigest() == SHA


class TestProgress:
    def test_progress_continues_across_resume(self, tmp_path):
        cut = 65_536 * 2
        sess = _Session([
            _Resp(PAYLOAD, cut_after=cut),
            _Resp(PAYLOAD[cut:], status=206),
        ])
        seen: list[tuple[int, int]] = []
        GithubUpdateChecker("1.0.0", session=sess).download_asset(
            _info(), tmp_path, on_progress=lambda d, t: seen.append((d, t))
        )
        received = [d for d, _ in seen]
        assert received == sorted(received), "진행률이 되돌아갔다"
        assert received[-1] == len(PAYLOAD)
