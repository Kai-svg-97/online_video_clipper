"""변환 프리셋의 **순수 정의** — I/O 없음.

이미 받아 둔 파일을 다른 기기에서 열 수 있는 형태로 바꾼다. 프리셋을 코드에 고정하는
이유는, 사용자가 코덱·비트레이트를 직접 고르는 화면은 거의 쓰이지 않고 잘못 고르면
결과가 재생되지 않기 때문이다. "어디서 볼 것인가"만 고르게 한다.

**H.264 + AAC + mp4 가 기본인 이유**: 이 조합만이 폰·TV·차량·구형 플레이어에서
사실상 항상 열린다. 화질이 더 좋은 코덱(H.265·VP9·AV1)은 기기에 따라 아예 열리지
않으므로, '호환' 목적의 변환에서는 선택지로 두지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass

# 오디오만 남기는 프리셋에서 쓸 확장자.
AUDIO_EXTS: frozenset[str] = frozenset({"mp3", "m4a"})


@dataclass(frozen=True, slots=True)
class ConvertPreset:
    """변환 프리셋 하나.

    ``max_height``가 있으면 그보다 큰 영상만 줄인다(작은 영상을 늘리지 않는다 —
    화질은 그대로인데 파일만 커진다). ``video_codec``이 비면 오디오만 남긴다.
    """

    key: str
    name: str
    description: str
    ext: str
    video_codec: str = ""
    audio_codec: str = "aac"
    max_height: int | None = None
    audio_bitrate: str = "192k"
    crf: int = 23

    @property
    def is_audio_only(self) -> bool:
        return not self.video_codec

    def output_name(self, stem: str) -> str:
        """원본 이름에 프리셋을 붙인 출력 파일명 — 원본을 덮어쓰지 않기 위해."""
        return f"{stem} [{self.key}].{self.ext}"


PRESETS: tuple[ConvertPreset, ...] = (
    ConvertPreset(
        key="mp4-1080p",
        name="일반 재생용 (1080p mp4)",
        description="H.264+AAC — 폰·TV·차량에서 거의 항상 열립니다",
        ext="mp4",
        video_codec="libx264",
        max_height=1080,
    ),
    ConvertPreset(
        key="mp4-720p",
        name="용량 줄이기 (720p mp4)",
        description="같은 조합에 해상도만 낮춰 파일을 작게 만듭니다",
        ext="mp4",
        video_codec="libx264",
        max_height=720,
        crf=26,
    ),
    ConvertPreset(
        key="mp4-480p",
        name="휴대용 (480p mp4)",
        description="이동 중 보기·용량이 빠듯할 때",
        ext="mp4",
        video_codec="libx264",
        max_height=480,
        crf=28,
    ),
    ConvertPreset(
        key="mp3",
        name="음원만 (mp3)",
        description="영상을 버리고 소리만 남깁니다",
        ext="mp3",
        video_codec="",
        audio_codec="libmp3lame",
    ),
    ConvertPreset(
        key="m4a",
        name="음원만 (m4a)",
        description="같은 용량에서 mp3보다 소리가 낫습니다",
        ext="m4a",
        video_codec="",
        audio_codec="aac",
    ),
)

PRESETS_BY_KEY: dict[str, ConvertPreset] = {p.key: p for p in PRESETS}


def find_preset(key: str) -> ConvertPreset | None:
    return PRESETS_BY_KEY.get(key)


def scale_filter(preset: ConvertPreset) -> str | None:
    """ffmpeg scale 필터 문자열(줄일 필요가 없으면 None).

    ``-2``는 "짝수로 맞춘 자동 너비"다. H.264는 홀수 크기를 인코딩하지 못해, 그냥
    ``-1``로 두면 세로 영상 등에서 변환이 실패한다.
    """
    if preset.max_height is None or preset.is_audio_only:
        return None
    return f"scale=-2:'min({preset.max_height},ih)'"
