"""YtDlpAdapter.download() 의 403 클라이언트 재시도 + 부분 파일 정리 회귀 테스트.

실 네트워크·yt_dlp 없이, ``sys.modules['yt_dlp']``에 가짜 모듈을 심어 검증한다.
배경: 기본(web) 클라이언트가 돌려주는 YouTube 다운로드 URL이 간헐적으로 403을
내는 문제가 재생 경로(gui/widgets/player/stream.py)에는 이미 클라이언트 폴백이
있었지만 다운로드 경로에는 없었다. 이 테스트는 그 폴백이 다운로드에도 적용됐고,
실패 시 남은 .part 파일이 정리되는지를 고정한다.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from domain.download.value_objects import DownloadSettings, MediaFormat, Quality
from infrastructure.downloader.ytdlp_adapter import YtDlpAdapter


class _FakeYoutubeDL:
    """yt_dlp.YoutubeDL 을 흉내내는 컨텍스트 매니저.

    ``_SCRIPT``(클래스 단위로 클라이언트별 결과를 미리 정해둔 리스트)를 순서대로
    소비한다 — 몇 번째 클라이언트 시도인지는 ``extractor_args``의
    ``player_client`` 값으로 판정한다.
    """

    # {player_client_key: "raise_403" | "raise_other" | "succeed"}
    SCRIPT: dict[str, str] = {}
    tmp_written: list[str] = []  # 이번 시도에서 progress_hook에 흘린 tmpfilename들

    def __init__(self, opts: dict) -> None:
        self._opts = opts
        client_list = (opts.get("extractor_args") or {}).get("youtube", {}).get("player_client")
        self._client_key = client_list[0] if client_list else "__default__"

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def extract_info(self, url: str, download: bool = True):
        action = self.SCRIPT.get(self._client_key, "raise_other")
        hooks = self._opts.get("progress_hooks") or []
        if action in ("raise_403", "raise_other"):
            # 다운로드가 일부 진행되다 실패한 상황을 흉내낸다: tmpfilename을
            # 진행률 훅에 흘리고(=.part 파일이 실제로 존재) 예외를 던진다.
            tmp_path = str(Path(self._opts["outtmpl"]).parent / f"video.f{len(self.tmp_written)}.mp4.part")
            Path(tmp_path).write_bytes(b"partial")
            self.tmp_written.append(tmp_path)
            for hook in hooks:
                hook({"status": "downloading", "tmpfilename": tmp_path})
            if action == "raise_403":
                raise RuntimeError("HTTP Error 403: Forbidden")
            raise RuntimeError("network unreachable")
        # 성공: 완성된 파일을 실제로 만들어 반환 정보를 채운다.
        final_path = Path(self._opts["outtmpl"]).parent / "video.mp4"
        final_path.write_bytes(b"done")
        return {
            "requested_downloads": [{"filepath": str(final_path), "height": 720}],
        }

    def prepare_filename(self, info: dict) -> str:
        return str(Path(self._opts["outtmpl"]).parent / "video.mp4")


def _install_fake_yt_dlp(monkeypatch, script: dict[str, str]) -> _FakeYoutubeDL:
    _FakeYoutubeDL.SCRIPT = script
    _FakeYoutubeDL.tmp_written = []
    fake_module = types.SimpleNamespace(YoutubeDL=_FakeYoutubeDL)
    monkeypatch.setitem(sys.modules, "yt_dlp", fake_module)
    return _FakeYoutubeDL


@pytest.fixture(autouse=True)
def _no_ffmpeg(monkeypatch):
    # ffmpeg 유무는 이 테스트의 관심사가 아니다 — 있으면 postprocessor 옵션이 늘어날
    # 뿐 재시도 로직에는 영향이 없다. 환경 차이로 흔들리지 않도록 없음으로 고정한다.
    monkeypatch.setattr(
        "infrastructure.downloader.ytdlp_adapter._find_ffmpeg", lambda: None
    )


class TestDownloadClientRetry:
    def test_fallback_to_next_client_on_403(self, tmp_path, monkeypatch):
        """기본 클라이언트가 403이면 android로 재시도해 성공한다."""
        _install_fake_yt_dlp(
            monkeypatch,
            {"__default__": "raise_403", "android": "succeed"},
        )
        adapter = YtDlpAdapter()
        settings = DownloadSettings(quality=Quality.P720, fmt=MediaFormat.MP4)

        result = adapter.download(
            "https://www.youtube.com/watch?v=abc123", settings, output_dir=tmp_path
        )

        # 720p 다운로드 성공 시 기존 로직이 품질 레이블([HD])을 붙여 파일명을 바꾼다
        # — 그 동작은 이 회귀 테스트의 관심사가 아니므로 stem만 확인한다.
        assert result.exists()
        assert result.stem.startswith("video")

    def test_stray_part_from_failed_first_client_cleaned_up_after_success(
        self, tmp_path, monkeypatch
    ):
        """첫 클라이언트가 403으로 남긴 .part가, 다음 클라이언트 성공 후에도 남지 않는다.

        정리 로직을 "완전 실패했을 때만" 돌리면, 두 번째 시도가 성공하는 흔한
        경우(회귀 테스트 1)에는 첫 시도의 조각 파일이 그대로 남는다 — 이 테스트가
        그 틈을 막는다.
        """
        fake_cls = _install_fake_yt_dlp(
            monkeypatch,
            {"__default__": "raise_403", "android": "succeed"},
        )
        adapter = YtDlpAdapter()
        settings = DownloadSettings(quality=Quality.P720, fmt=MediaFormat.MP4)

        result = adapter.download(
            "https://www.youtube.com/watch?v=abc123", settings, output_dir=tmp_path
        )

        assert result.exists()
        # 첫(기본) 클라이언트 시도가 남긴 .part 파일은 정리되어야 한다.
        assert len(fake_cls.tmp_written) == 1
        assert not Path(fake_cls.tmp_written[0]).exists()

    def test_all_clients_403_raises_and_cleans_up_part_files(self, tmp_path, monkeypatch):
        """모든 클라이언트가 403이면 예외를 전파하고 .part 파일을 정리한다."""
        fake_cls = _install_fake_yt_dlp(
            monkeypatch,
            {k: "raise_403" for k in ("__default__", "android", "ios", "tv")},
        )
        adapter = YtDlpAdapter()
        settings = DownloadSettings(quality=Quality.P720, fmt=MediaFormat.MP4)

        with pytest.raises(RuntimeError, match="403"):
            adapter.download(
                "https://www.youtube.com/watch?v=abc123", settings, output_dir=tmp_path
            )

        # 4개 클라이언트 모두 시도했고, 각자 남긴 .part 파일은 전부 정리됐다.
        assert len(fake_cls.tmp_written) == 4
        for tmp_path_str in fake_cls.tmp_written:
            assert not Path(tmp_path_str).exists()

    def test_non_403_error_on_non_youtube_url_raises_immediately(self, tmp_path, monkeypatch):
        """YouTube가 아닌 URL은 클라이언트를 바꿀 이유가 없어 1회만 시도한다."""
        fake_cls = _install_fake_yt_dlp(monkeypatch, {"__default__": "raise_other"})
        adapter = YtDlpAdapter()
        settings = DownloadSettings(quality=Quality.P720, fmt=MediaFormat.MP4)

        with pytest.raises(RuntimeError, match="network unreachable"):
            adapter.download("https://example.com/video", settings, output_dir=tmp_path)

        assert len(fake_cls.tmp_written) == 1
        assert not Path(fake_cls.tmp_written[0]).exists()

    def test_non_403_error_on_youtube_url_does_not_retry(self, tmp_path, monkeypatch):
        """YouTube URL이라도 403이 아닌 오류는 클라이언트를 바꿔도 소용없으므로 재시도하지 않는다."""
        fake_cls = _install_fake_yt_dlp(monkeypatch, {"__default__": "raise_other"})
        adapter = YtDlpAdapter()
        settings = DownloadSettings(quality=Quality.P720, fmt=MediaFormat.MP4)

        with pytest.raises(RuntimeError, match="network unreachable"):
            adapter.download(
                "https://www.youtube.com/watch?v=abc123", settings, output_dir=tmp_path
            )

        assert len(fake_cls.tmp_written) == 1
