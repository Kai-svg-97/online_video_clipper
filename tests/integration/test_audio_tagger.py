"""mutagen 어댑터 — 실제 파일에 태그를 쓰고 다시 읽는다.

포맷별 키 이름을 틀려도 예외가 나지 않고 **조용히 엉뚱한 곳에 저장**되는 것이
mutagen의 함정이라, 왕복으로만 검증할 수 있다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from domain.shared.ports import AudioTags
from infrastructure.song.audio_tagger import MutagenAudioTagger

pytest.importorskip("mutagen")


@pytest.fixture
def tagger() -> MutagenAudioTagger:
    return MutagenAudioTagger()


@pytest.fixture
def cover(tmp_path: Path) -> Path:
    """1×1 PNG — 표지 바이트가 그대로 실리는지 보기 위해 진짜 이미지를 쓴다."""
    png = bytes.fromhex(
        "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
        "1f15c4890000000a49444154789c6360000002000100"
        "0000000049454e44ae426082"
    )
    p = tmp_path / "cover.png"
    p.write_bytes(png)
    return p


class TestId3:
    def test_mp3_태그_왕복(self, tagger, tmp_path, cover):
        from mutagen.id3 import ID3  # noqa: PLC0415

        path = tmp_path / "노래.mp3"
        path.write_bytes(b"\x00" * 64)   # ID3 프레임만 검증하므로 내용은 무관

        ok = tagger.write_tags(
            path,
            AudioTags(
                title="제목",
                artist="가수",
                album="앨범",
                year="2024",
                lyrics="[00:01.00]첫 줄\n[00:02.00]둘째 줄",
                cover_path=cover,
            ),
        )
        assert ok

        tags = ID3(path)
        assert tags["TIT2"].text == ["제목"]
        assert tags["TPE1"].text == ["가수"]
        assert tags["TALB"].text == ["앨범"]
        assert str(tags["TDRC"].text[0]) == "2024"
        uslt = tags.getall("USLT")
        assert len(uslt) == 1
        assert uslt[0].text.startswith("[00:01.00]첫 줄")
        apic = tags.getall("APIC")
        assert len(apic) == 1
        assert apic[0].mime == "image/png"
        assert apic[0].data == cover.read_bytes()

    def test_다시_쓰면_가사와_표지가_쌓이지_않는다(self, tagger, tmp_path, cover):
        """USLT·APIC이 누적되면 플레이어가 아무거나 하나를 고른다."""
        from mutagen.id3 import ID3  # noqa: PLC0415

        path = tmp_path / "노래.mp3"
        path.write_bytes(b"\x00" * 64)
        first = AudioTags(title="처음", lyrics="옛 가사", cover_path=cover)
        second = AudioTags(title="나중", lyrics="새 가사", cover_path=cover)
        tagger.write_tags(path, first)
        tagger.write_tags(path, second)

        tags = ID3(path)
        assert len(tags.getall("USLT")) == 1
        assert tags.getall("USLT")[0].text == "새 가사"
        assert len(tags.getall("APIC")) == 1
        assert tags["TIT2"].text == ["나중"]


class TestGuards:
    def test_빈_태그는_파일을_건드리지_않는다(self, tagger, tmp_path):
        path = tmp_path / "노래.mp3"
        path.write_bytes(b"\x00" * 64)
        before = path.read_bytes()
        assert tagger.write_tags(path, AudioTags()) is False
        assert path.read_bytes() == before

    def test_없는_파일이면_False(self, tagger, tmp_path):
        assert tagger.write_tags(tmp_path / "없음.mp3", AudioTags(title="x")) is False

    def test_지원하지_않는_확장자는_False(self, tagger, tmp_path):
        path = tmp_path / "영상.mkv"
        path.write_bytes(b"\x00" * 16)
        assert tagger.write_tags(path, AudioTags(title="x")) is False

    def test_깨진_파일이어도_예외를_내지_않는다(self, tagger, tmp_path):
        """m4a 는 유효한 컨테이너를 요구한다 — 여기서 터지면 다운로드가 실패로 보고된다."""
        path = tmp_path / "노래.m4a"
        path.write_bytes(b"not an mp4 container")
        assert tagger.write_tags(path, AudioTags(title="제목")) is False

    def test_webp_표지는_넣지_않는다(self, tagger, tmp_path):
        """대부분의 플레이어가 webp 표지를 읽지 못한다 — 넣으면 표지가 깨져 보인다."""
        from mutagen.id3 import ID3  # noqa: PLC0415

        webp = tmp_path / "cover.webp"
        webp.write_bytes(b"RIFF----WEBP")
        path = tmp_path / "노래.mp3"
        path.write_bytes(b"\x00" * 64)

        assert tagger.write_tags(path, AudioTags(title="제목", cover_path=webp)) is True
        assert ID3(path).getall("APIC") == []
