import sys
from pathlib import Path


def get_resource_path(relative: str) -> Path:
    """Return the absolute path to a bundled resource.

    Works in both development (relative to project root) and in a
    PyInstaller one-file bundle (relative to sys._MEIPASS).
    """
    if hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / relative
    return Path(__file__).parent.parent / relative


def get_ffmpeg_path() -> str:
    """Return the path to the ffmpeg binary.

    Priority: bundled bin/ → system PATH.
    """
    import shutil

    candidates = ["bin/ffmpeg.exe", "bin/ffmpeg"]
    for rel in candidates:
        bundled = get_resource_path(rel)
        if bundled.exists():
            return str(bundled)

    system = shutil.which("ffmpeg")
    if system:
        return system

    raise FileNotFoundError(
        "ffmpeg not found. Install ffmpeg or place the binary in the bin/ directory."
    )
