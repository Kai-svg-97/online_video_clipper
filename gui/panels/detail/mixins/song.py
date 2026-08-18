"""SongTabMixin — 상세화면의 song 영역.

    VideoDetailWidget에 섞여 들어가는 mixin이라 위젯 상태를 그대로 쓴다
    (런타임 클래스는 하나다).
"""

from __future__ import annotations

import logging





# ── 분할된 부품 (gui/panels/detail/*) ─────────────────────────────
# 이 파일에는 화면 조립·흐름 제어만 남기고 부품은 패키지로 옮겼다.
# 아래 재수출은 기존 임포트 경로를 유지하기 위한 것이다.
from gui.panels.detail.widgets import (  # noqa: F401
    _AutoHeightBrowser,
    _AutoHeightPlainEdit,
    _DblClickLabel,
    _EditableField,
    _FlowLayout,
    _LockedNotice,
    _SpinRefreshButton,
    _TagChip,
    _TagFlow,
    _bold_font,
    _clear_layout,
    _fmt_size,
    _hline,
    _open_file,
    _open_folder,
    _t,
    _wrap,
)
from gui.panels.detail.related import (  # noqa: F401
    RelatedItem,
    _RelatedList,
    _RelatedRow,
    _fmt_dur,
    _fmt_pub,
    _payload_key,
)
from gui.panels.detail.song_tab import (  # noqa: F401
    _LyricRow,
    _LyricsCandidateList,
    _SongTab,
    _candidate_tooltip,
)
from gui.panels.detail.workers import (  # noqa: F401
    _GeminiSummaryWorker,
)

logger = logging.getLogger(__name__)


class SongTabMixin:
    """노래 탭 배선 — 가사 조회·후보 선택·번역·자막 오프셋 저장(디바운스).

    오프셋은 조정 시점의 video_id를 함께 캡처해 저장한다 — 디바운스 대기 중 다른
    영상으로 넘어가도 원래 영상에 저장되도록 하는 레이스 수정이다.
    """

    def set_song_busy(self, busy: bool) -> None:
        self._song_tab.set_busy(busy)

    def _on_song_field_edited(self, field: str, value: str) -> None:
        if self._detail is not None and not self._streaming:
            self.song_field_saved.emit(self._detail.id, field, value)

    def _on_song_lyrics_edited(self, lines: object) -> None:
        if self._detail is not None and not self._streaming:
            self.song_lyrics_saved.emit(self._detail.id, lines)

    def _on_song_candidates(self) -> None:
        if self._detail is not None and not self._streaming:
            self.song_candidates_requested.emit(self._detail.id)

    def _on_song_candidate_chosen(self, dto: object) -> None:
        if self._detail is not None and not self._streaming:
            self.song_candidate_chosen.emit(self._detail.id, dto)

    # 후보 검색 결과 주입 — SongViewModel 신호를 LibraryPanel이 그대로 넘겨준다.
    # video_id를 함께 받아, 검색 중 다른 영상으로 넘어갔으면 무시한다(늦게 도착한 결과가
    # 지금 보고 있는 영상의 목록에 섞이는 것을 막는다).
    def song_candidates_started(self, video_id: object, source_names: object) -> None:
        if self._is_current_song(video_id):
            self._song_tab.begin_candidates(list(source_names or []))

    def song_candidate_ready(self, video_id: object, source_name: str, dto: object) -> None:
        if self._is_current_song(video_id):
            self._song_tab.add_candidate_result(source_name, dto)

    def song_candidate_source_done(self, video_id: object, source_name: str, count: int) -> None:
        if self._is_current_song(video_id):
            self._song_tab.candidate_source_done(source_name, int(count))

    def song_candidates_finished(self, video_id: object, found: int) -> None:
        if self._is_current_song(video_id):
            self._song_tab.finish_candidates(int(found))

    def _is_current_song(self, video_id: object) -> bool:
        return (
            self._detail is not None
            and not self._streaming
            and self._detail.id == video_id
        )

    def _on_song_translate(self) -> None:
        if self._detail is not None and not self._streaming:
            self.song_translate_requested.emit(self._detail.id)

    def _on_song_flag_toggled(self, is_song: bool) -> None:
        if self._detail is not None and not self._streaming:
            self.song_flag_toggled.emit(self._detail.id, is_song)

    def _on_song_synced(self) -> None:
        if self._detail is not None and not self._streaming:
            self.song_synced_requested.emit(self._detail.id)

    def _on_lyrics_seek(self, start_ms: int) -> None:
        """가사 줄 클릭 → 그 줄이 실제로 뜨는 위치로 이동(오프셋 반영)."""
        self._player.seek_to_ms(max(0, start_ms + self._player.subtitle_offset_ms()))

    def _flush_offset(self) -> None:
        pending = self._pending_offset
        self._pending_offset = None
        if pending is None:
            return
        video_id, offset_ms = pending
        self.song_offset_saved.emit(video_id, offset_ms)
