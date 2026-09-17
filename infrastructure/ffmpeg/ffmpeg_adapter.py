from __future__ import annotations

import logging
import re
import subprocess
import sys
from pathlib import Path

from domain.clip.value_objects import TimeRange
from utils.resources import get_ffmpeg_path

logger = logging.getLogger(__name__)

# Windows에서 콘솔 창이 깜빡이지 않게 한다 — 변환은 사용자가 보는 앞에서 돈다.
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


# `ffmpeg -i`가 stderr에 찍는 길이 표기: `Duration: 00:01:23.45, start: ...`
_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d{2}):(\d{2})\.(\d+)")


def _probe_duration_us(path: Path) -> int:
    """영상 길이(마이크로초). 모르면 0 — 진행률만 못 보여줄 뿐 변환은 된다.

    **ffprobe를 쓰지 않는다.** 배포 패키지에는 `bin/ffmpeg`만 들어 있고 ffprobe는
    없다(PATH에도 없는 환경이 정상이다). ffprobe에 기대면 진행률이 **조용히** 0에
    머물러, 몇 분짜리 변환이 멈춘 것처럼 보인다 — 실제로 이 테스트가 그 상태를 잡았다.
    대신 ffmpeg 자신이 입력을 열며 stderr에 찍는 `Duration:` 줄을 읽는다.
    """
    try:
        proc = subprocess.run(
            [get_ffmpeg_path(), "-hide_banner", "-i", str(path)],
            capture_output=True,
            text=True,
            errors="replace",
            creationflags=_NO_WINDOW,
        )
    except OSError:
        logger.debug("길이 조회 실패 — 진행률 없이 변환한다: %s", path, exc_info=True)
        return 0
    # 출력 파일을 주지 않았으므로 ffmpeg는 오류로 끝난다(정상이다). 필요한 건 stderr다.
    match = _DURATION_RE.search(proc.stderr or "")
    if not match:
        logger.debug("길이 표기를 찾지 못함 — 진행률 없이 변환한다: %s", path)
        return 0
    hours, minutes, seconds, frac = match.groups()
    total = int(hours) * 3600 + int(minutes) * 60 + int(seconds)
    return int((total + float(f"0.{frac}")) * 1_000_000)


class FfmpegAdapter:
    """Wraps ffmpeg-python for clip extraction.

    All I/O runs in a background QThread — never call from the GUI thread.
    """

    def extract_clip(
        self,
        source_path: Path,
        time_range: TimeRange,
        output_path: Path,
    ) -> Path:
        """Extract *time_range* from *source_path* into *output_path*."""
        import ffmpeg  # noqa: PLC0415
        output_path.parent.mkdir(parents=True, exist_ok=True)
        (
            ffmpeg
            .input(str(source_path), ss=time_range.start_sec, to=time_range.end_sec)
            .output(str(output_path), c="copy")
            .overwrite_output()
            .run(cmd=get_ffmpeg_path(), quiet=True)
        )
        return output_path

    def extract_thumbnail(
        self,
        source_path: Path,
        timestamp_sec: float,
        output_path: Path,
        width: int = 160,
        height: int = 90,
    ) -> Path:
        """Extract a single frame as a JPEG thumbnail."""
        import ffmpeg  # noqa: PLC0415
        output_path.parent.mkdir(parents=True, exist_ok=True)
        (
            ffmpeg
            .input(str(source_path), ss=timestamp_sec)
            .filter("scale", width, height)
            .output(str(output_path), vframes=1)
            .overwrite_output()
            .run(cmd=get_ffmpeg_path(), quiet=True)
        )
        return output_path

    def convert(
        self,
        source_path: Path,
        preset,
        output_path: Path,
        on_progress=None,
    ) -> Path:
        """`preset`대로 변환한다. 배경 QThread에서만 호출한다(오래 걸린다).

        ffmpeg-python 대신 **subprocess로 직접 돌린다** — 진행률을 읽으려면
        `-progress pipe:1` 출력을 줄 단위로 따라가야 하는데, ffmpeg-python의
        `run()`은 끝날 때까지 돌려주지 않아 몇 분짜리 변환이 '멈춘 것처럼' 보인다.
        """
        import subprocess  # noqa: PLC0415

        from domain.clip.presets import scale_filter  # noqa: PLC0415

        output_path.parent.mkdir(parents=True, exist_ok=True)
        cmd = [get_ffmpeg_path(), "-hide_banner", "-nostdin", "-y", "-i", str(source_path)]

        if preset.is_audio_only:
            cmd += ["-vn", "-c:a", preset.audio_codec, "-b:a", preset.audio_bitrate]
        else:
            scale = scale_filter(preset)
            if scale:
                cmd += ["-vf", scale]
            cmd += [
                "-c:v", preset.video_codec,
                "-crf", str(preset.crf),
                "-preset", "veryfast",     # 품질보다 시간 — 데스크탑에서 몇 분을 넘기지 않게
                "-c:a", preset.audio_codec,
                "-b:a", preset.audio_bitrate,
                "-movflags", "+faststart",  # 처음부터 바로 재생되게(웹·모바일 플레이어)
            ]
        cmd += ["-progress", "pipe:1", "-nostats", str(output_path)]

        total_us = _probe_duration_us(source_path)
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            creationflags=_NO_WINDOW,
        )
        try:
            for line in proc.stdout or ():
                if on_progress is None or not total_us:
                    continue
                if line.startswith("out_time_us="):
                    done = line.strip().split("=", 1)[1]
                    if done.isdigit():
                        on_progress(min(100, int(int(done) * 100 / total_us)))
        finally:
            proc.wait()
        if proc.returncode != 0:
            raise RuntimeError(f"ffmpeg 변환 실패 (코드 {proc.returncode})")
        return output_path
