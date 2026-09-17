"""mutagen 기반 음원 태그 기록 어댑터.

포맷마다 태그 규격이 다르다(ID3v2 / MP4 atom / Vorbis comment). mutagen의
``File(easy=True)``는 공통 키만 다뤄 **가사와 표지를 못 쓴다** — 그래서 포맷별
저수준 API를 직접 쓴다.

실패해도 예외를 밖으로 내지 않는다. 태그는 다운로드의 부가 산출물이라, 여기서
터지면 "받았는데 실패했다"는 잘못된 보고가 된다.
"""

from __future__ import annotations

import logging
from pathlib import Path

from domain.shared.ports import AudioTags

logger = logging.getLogger(__name__)

# 표지 바이트를 그대로 파일에 넣으므로 확장자로 MIME을 정한다.
_COVER_MIME = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
}


def _read_cover(path: Path | None) -> tuple[bytes, str] | None:
    if path is None:
        return None
    mime = _COVER_MIME.get(path.suffix.lower())
    if mime is None:
        # webp 등은 대부분의 플레이어가 표지로 읽지 못한다 — 넣지 않는다.
        logger.debug("표지로 쓸 수 없는 형식이라 건너뜀: %s", path)
        return None
    try:
        return path.read_bytes(), mime
    except OSError:
        logger.exception("표지 파일 읽기 실패: %s", path)
        return None


class MutagenAudioTagger:
    """`IAudioTagger` 구현. 배경 스레드에서 호출한다(파일 I/O)."""

    def write_tags(self, file_path: Path, tags: AudioTags) -> bool:
        if tags.is_empty():
            return False
        if not file_path.exists():
            logger.debug("태그를 쓸 파일이 없음: %s", file_path)
            return False

        ext = file_path.suffix.lower()
        try:
            if ext == ".mp3":
                return self._write_id3(file_path, tags)
            if ext in (".m4a", ".mp4", ".m4b"):
                return self._write_mp4(file_path, tags)
            if ext in (".flac", ".ogg", ".opus"):
                return self._write_vorbis(file_path, tags)
        except Exception:
            logger.exception("음원 태그 기록 실패 (무시): %s", file_path)
            return False

        logger.debug("태그를 지원하지 않는 확장자라 건너뜀: %s", file_path)
        return False

    # ── 포맷별 구현 ────────────────────────────────────────────────

    def _write_id3(self, file_path: Path, tags: AudioTags) -> bool:
        from mutagen.id3 import (  # noqa: PLC0415
            APIC,
            ID3,
            TALB,
            TDRC,
            TIT2,
            TPE1,
            USLT,
            ID3NoHeaderError,
        )

        try:
            audio = ID3(file_path)
        except ID3NoHeaderError:
            audio = ID3()

        if tags.title:
            audio.setall("TIT2", [TIT2(encoding=3, text=tags.title)])
        if tags.artist:
            audio.setall("TPE1", [TPE1(encoding=3, text=tags.artist)])
        if tags.album:
            audio.setall("TALB", [TALB(encoding=3, text=tags.album)])
        if tags.year:
            audio.setall("TDRC", [TDRC(encoding=3, text=tags.year)])
        if tags.lyrics:
            # USLT는 (언어, 설명)이 키다. 기존 가사를 지우고 하나만 남긴다 —
            # 갱신할 때마다 쌓이면 플레이어가 아무거나 하나를 고른다.
            audio.delall("USLT")
            audio.add(USLT(encoding=3, lang="kor", desc="", text=tags.lyrics))
        cover = _read_cover(tags.cover_path)
        if cover:
            data, mime = cover
            audio.delall("APIC")
            audio.add(APIC(encoding=3, mime=mime, type=3, desc="Cover", data=data))

        audio.save(file_path, v2_version=3)
        return True

    def _write_mp4(self, file_path: Path, tags: AudioTags) -> bool:
        from mutagen.mp4 import MP4, MP4Cover  # noqa: PLC0415

        audio = MP4(file_path)
        if tags.title:
            audio["\xa9nam"] = [tags.title]
        if tags.artist:
            audio["\xa9ART"] = [tags.artist]
        if tags.album:
            audio["\xa9alb"] = [tags.album]
        if tags.year:
            audio["\xa9day"] = [tags.year]
        if tags.lyrics:
            audio["\xa9lyr"] = [tags.lyrics]
        cover = _read_cover(tags.cover_path)
        if cover:
            data, mime = cover
            fmt = MP4Cover.FORMAT_PNG if mime == "image/png" else MP4Cover.FORMAT_JPEG
            audio["covr"] = [MP4Cover(data, imageformat=fmt)]

        audio.save()
        return True

    def _write_vorbis(self, file_path: Path, tags: AudioTags) -> bool:
        import base64  # noqa: PLC0415

        from mutagen import File as MutagenFile  # noqa: PLC0415
        from mutagen.flac import Picture  # noqa: PLC0415

        audio = MutagenFile(file_path)
        if audio is None:
            return False
        if tags.title:
            audio["title"] = tags.title
        if tags.artist:
            audio["artist"] = tags.artist
        if tags.album:
            audio["album"] = tags.album
        if tags.year:
            audio["date"] = tags.year
        if tags.lyrics:
            audio["lyrics"] = tags.lyrics
        cover = _read_cover(tags.cover_path)
        if cover:
            data, mime = cover
            pic = Picture()
            pic.data = data
            pic.type = 3
            pic.mime = mime
            if hasattr(audio, "add_picture"):   # FLAC
                audio.clear_pictures()
                audio.add_picture(pic)
            else:                                # Ogg/Opus — base64 주석으로 넣는다
                audio["metadata_block_picture"] = [
                    base64.b64encode(pic.write()).decode("ascii")
                ]

        audio.save()
        return True
