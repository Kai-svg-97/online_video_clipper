"""ffmpeg 변환 어댑터 — 진짜 ffmpeg로 짧은 영상을 만들어 바꿔 본다.

명령줄 조합은 눈으로 검사해도 틀린 것을 못 잡는다(잘못된 필터는 실행해야 터진다).
그래서 ffmpeg가 있는 환경에서는 실제로 돌린다.
"""

from __future__ import annotations

import re
import subprocess

import pytest

from domain.clip.presets import find_preset
from infrastructure.ffmpeg.ffmpeg_adapter import FfmpegAdapter
from utils.resources import get_ffmpeg_path


def _video_size(ffmpeg_bin, path) -> tuple[int, int]:
    """ffmpeg가 stderr에 찍는 스트림 줄에서 해상도를 읽는다."""
    proc = subprocess.run(
        [ffmpeg_bin, "-hide_banner", "-i", str(path)],
        capture_output=True, text=True, errors="replace",
    )
    match = re.search(r"Video:.*?\s(\d{2,5})x(\d{2,5})", proc.stderr or "")
    assert match, f"해상도를 찾지 못함:\n{proc.stderr[-800:]}"
    return int(match.group(1)), int(match.group(2))


@pytest.fixture(scope="module")
def ffmpeg_bin():
    try:
        path = get_ffmpeg_path()
    except FileNotFoundError:
        pytest.skip("ffmpeg 없음 — 변환 테스트 건너뜀")
    return path


@pytest.fixture
def sample(tmp_path, ffmpeg_bin):
    """1초짜리 640x360 무음 영상 — 빠르게 만들 수 있는 최소 입력."""
    out = tmp_path / "원본.mp4"
    subprocess.run(
        [
            ffmpeg_bin, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "testsrc=size=640x360:rate=10:duration=1",
            "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
            "-shortest", "-c:v", "libx264", "-c:a", "aac", str(out),
        ],
        check=True,
        capture_output=True,
    )
    return out


class TestConvert:
    def test_영상_프리셋으로_바꾼다(self, sample, tmp_path):
        preset = find_preset("mp4-480p")
        out = tmp_path / preset.output_name(sample.stem)
        result = FfmpegAdapter().convert(sample, preset, out)
        assert result.exists() and result.stat().st_size > 0

    def test_음원_프리셋은_소리만_남긴다(self, sample, tmp_path):
        preset = find_preset("mp3")
        out = tmp_path / preset.output_name(sample.stem)
        result = FfmpegAdapter().convert(sample, preset, out)
        assert result.exists() and result.suffix == ".mp3"

    def test_원본보다_큰_해상도로_늘리지_않는다(self, sample, tmp_path, ffmpeg_bin):
        """640x360 원본을 1080p 프리셋으로 바꿔도 높이가 그대로여야 한다.

        해상도 확인에도 ffprobe를 쓰지 않는다 — 배포 패키지에 없다.
        """
        preset = find_preset("mp4-1080p")
        out = tmp_path / preset.output_name(sample.stem)
        FfmpegAdapter().convert(sample, preset, out)
        assert _video_size(ffmpeg_bin, out) == (640, 360)

    def test_진행률이_올라간다(self, sample, tmp_path):
        seen: list[int] = []
        preset = find_preset("mp4-480p")
        FfmpegAdapter().convert(
            sample, preset, tmp_path / "out.mp4", on_progress=seen.append
        )
        assert seen, "진행률 콜백이 한 번도 불리지 않았다"
        assert max(seen) <= 100

    def test_없는_원본은_예외다(self, tmp_path):
        with pytest.raises(Exception):
            FfmpegAdapter().convert(
                tmp_path / "없음.mp4", find_preset("mp3"), tmp_path / "out.mp3"
            )
