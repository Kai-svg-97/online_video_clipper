"""가사/노래 DTO가 `__slots__`를 갖는지 확인한다.

v1.22.0 체감 성능 개선 Phase 1 Step 2 — 도메인 `LyricsLine`은 이미
`frozen=True, slots=True`인데 DTO 경계에서 slots가 빠져 있어 인스턴스마다
`__dict__`를 들고 있었다(저사양 4GB 목표에서 항목당 메모리 낭비). 이 테스트는
`application/song/dtos.py`의 각 DTO가 slots를 유지하는지 못박는다 — 누군가
필드를 추가하며 `@dataclass(frozen=True)`로 되돌리면(slots를 빼먹으면) 여기서
바로 드러난다.
"""
from __future__ import annotations

from uuid import uuid4

from application.song.dtos import (
    LyricsCandidateDTO,
    LyricsLineDTO,
    LyricsSourceDTO,
    SongInfoDTO,
)


class TestSlotsPresent:
    def test_LyricsLineDTO는_dict가_없다(self):
        dto = LyricsLineDTO(original="원문", translation="번역", start_ms=1000)
        assert not hasattr(dto, "__dict__")
        assert dto.__slots__ == ("original", "translation", "start_ms")

    def test_SongInfoDTO는_dict가_없다(self):
        dto = SongInfoDTO(video_id=uuid4(), is_song=True)
        assert not hasattr(dto, "__dict__")

    def test_LyricsCandidateDTO는_dict가_없다(self):
        dto = LyricsCandidateDTO(
            source_name="LRCLIB",
            artist="가수",
            title="제목",
            first_line="첫 줄",
            is_synced=False,
            lines=(),
            timings=(),
        )
        assert not hasattr(dto, "__dict__")

    def test_LyricsSourceDTO는_dict가_없다(self):
        dto = LyricsSourceDTO(
            id=uuid4(), name="LRCLIB", provider_key="lrclib", priority=0, enabled=True
        )
        assert not hasattr(dto, "__dict__")

    def test_속성_접근은_정상_동작한다(self):
        """slots가 __dict__를 없앨 뿐 필드 읽기/동일성 비교는 그대로여야 한다."""
        a = LyricsLineDTO(original="x", translation="", start_ms=None)
        b = LyricsLineDTO(original="x", translation="", start_ms=None)
        assert a == b
        assert a.original == "x"
