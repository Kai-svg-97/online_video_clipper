"""이미 받아 둔 파일을 다른 기기용으로 변환하는 유스케이스.

**원본을 덮어쓰지 않는다.** 변환은 되돌릴 수 없고(원본 화질은 복구되지 않는다),
사용자가 결과를 확인한 뒤 원본을 지울지 정하는 편이 안전하다. 그래서 출력은 항상
`제목 [프리셋].확장자`라는 새 파일이다.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from domain.clip.presets import ConvertPreset, find_preset

logger = logging.getLogger(__name__)


@dataclass
class ConvertMediaCommand:
    source_file_path: str
    preset_key: str
    output_dir: str | None = None   # 비우면 원본과 같은 폴더


class ConvertMediaHandler:
    """ffmpeg 변환 실행. 배경 QThread에서만 호출한다(몇 분이 걸릴 수 있다)."""

    def __init__(self, converter) -> None:
        self._converter = converter

    def handle(
        self,
        cmd: ConvertMediaCommand,
        on_progress: Callable[[int], None] | None = None,
    ) -> Path:
        preset = find_preset(cmd.preset_key)
        if preset is None:
            raise ValueError(f"알 수 없는 변환 프리셋: {cmd.preset_key}")

        source = Path(cmd.source_file_path)
        if not source.exists():
            raise FileNotFoundError(f"원본 파일이 없습니다: {source}")

        out_dir = Path(cmd.output_dir) if cmd.output_dir else source.parent
        output = out_dir / preset.output_name(source.stem)
        if output.resolve() == source.resolve():
            # 같은 이름으로 떨어지면 원본이 사라진다. 프리셋 이름이 파일명에 이미
            # 들어 있는 경우(재변환)에 실제로 일어난다.
            output = out_dir / preset.output_name(f"{source.stem} (2)")

        logger.info("변환 시작: %s → %s (%s)", source.name, output.name, preset.key)
        result = self._converter.convert(source, preset, output, on_progress=on_progress)
        logger.info("변환 완료: %s", result)
        return result


def list_presets() -> list[ConvertPreset]:
    """화면이 그릴 프리셋 목록(도메인 정의를 그대로 노출한다)."""
    from domain.clip.presets import PRESETS  # noqa: PLC0415

    return list(PRESETS)
