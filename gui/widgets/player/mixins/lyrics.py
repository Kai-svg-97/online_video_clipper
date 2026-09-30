"""LyricsSubtitleMixin — 싱크 가사 자막, 자막 크기·위치 설정, 조절 값 임시 안내.

    InlinePlayer에 섞여 들어가는 mixin이라 위젯 상태를 그대로 쓴다
    (런타임 클래스는 하나다 — 조립은 `gui/widgets/video_player.py`).
"""
from __future__ import annotations

import logging

from config import settings
from gui.text import tr
from gui.widgets.lyrics_overlay import LyricsCue, LyricsOverlay, LyricsTrack

logger = logging.getLogger(__name__)


class LyricsSubtitleMixin:
    """가사 트랙·오프셋(`[`/`]`/`\\`)·표시 설정(Ctrl+휠)을 3창 오버레이에 팬아웃한다."""

    # ── 가사 자막 ──────────────────────────────────────────────────
    def set_lyrics(self, track: LyricsTrack | None) -> None:
        """표시할 싱크 가사를 설정한다. None/빈 트랙이면 자막 UI를 비활성한다."""
        self._track = track if (track is not None and not track.is_empty) else None
        has = self._track is not None
        # -1이 아니라 강제 갱신 센티넬(-2)로 둔다 — 새 트랙의 현재 줄이 마침 '없음'(-1)이어도
        # 이전 줄을 강조하던 소비자가 해제 신호(current_line_changed(-1))를 받아야 한다.
        self._current_line_index = -2
        for bar in self._all_bars():
            bar.set_has_subtitle(has)
            bar.set_subtitle_on(self._subtitle_on)
            bar.set_subtitle_offset_ms(self._track.offset_ms if has else 0)
        for overlay in self._all_subtitles():
            overlay.set_cue(None)
            overlay.set_text_visible(self._subtitle_on)
        if has:
            self._apply_subtitle_position(self.position_ms)

    def set_subtitle_enabled(self, on: bool) -> None:
        self._subtitle_on = bool(on)
        for bar in self._all_bars():
            bar.set_subtitle_on(self._subtitle_on)
        for overlay in self._all_subtitles():
            overlay.set_text_visible(self._subtitle_on)

    def subtitle_offset_ms(self) -> int:
        return self._track.offset_ms if self._track else 0

    def set_subtitle_offset_ms(self, ms: int) -> None:
        """외부(상세화면 노래 탭 등)에서 절대 오프셋 값을 지정한다.

        `[`/`]` 단축키·우클릭 메뉴가 쓰는 내부 조정과 동일한 경로를 타므로 바·오버레이
        갱신과 `subtitle_offset_changed` 발행(→디바운스 저장)이 그대로 따라온다.
        """
        self._set_subtitle_offset(int(ms))

    def _subtitle_prefs_dirty(self) -> bool:
        """크기·위치가 기본값에서 벗어나 있는지(초기화 메뉴 노출 조건)."""
        return (
            self._subtitle_font_scale != LyricsOverlay.FONT_SCALE_DEFAULT
            or self._subtitle_bottom_ratio != LyricsOverlay.BOTTOM_RATIO_DEFAULT
        )

    def _apply_subtitle_prefs(self) -> None:
        """현재 크기·위치를 3창 오버레이 전부에 반영한다."""
        for overlay in self._all_subtitles():
            overlay.set_font_scale(self._subtitle_font_scale)
            overlay.set_bottom_ratio(self._subtitle_bottom_ratio)
        # 값이 기본값이 아니면 가사가 없어도 💬 우클릭으로 초기화에 닿을 수 있어야 한다.
        dirty = self._subtitle_prefs_dirty()
        for bar in self._all_bars():
            bar.set_subtitle_prefs_dirty(dirty)

    def _show_transient(self, text: str, ms: int = 1000) -> None:
        """조절 중 현재 값을 잠깐 보여준다.

        가사 줄이 안 나오는 구간에서 조절하면 화면에 아무 변화가 없어 먹었는지
        알 수 없다. 그래서 값 표시는 있으나 마나 한 장식이 아니라 필수다.

        상태 라벨(`_status_lbl`)은 **인라인 위젯의 자식**이라 전체화면에서는 가려지고
        PiP 는 아예 다른 창이다. 그래서 같은 문구를 3창 오버레이에도 그린다 —
        오버레이는 세 창이 모두 갖고 있고 이미 영상 위에 얹혀 있다.
        """
        if not self._transient_text:
            # 진행 중이던 안내(예: "스트림 URL 가져오는 중…")를 덮어쓰므로 되돌릴 수
            # 있게 보관한다. 이미 임시 문구 중이면 처음 보관한 원본을 유지한다.
            self._status_before_transient = (
                self._status_lbl.text(), not self._status_lbl.isHidden()
            )
        self._transient_text = text
        self._status_lbl.setText(text)
        self._status_lbl.show()
        for overlay in self._all_subtitles():
            overlay.set_notice(text)
        self._transient_timer.start(ms)

    def _clear_transient(self) -> None:
        # 그 사이 스트림 안내 문구로 바뀌었다면 건드리지 않는다.
        if self._status_lbl.text() == self._transient_text:
            prev_text, prev_visible = self._status_before_transient
            self._status_lbl.setText(prev_text)
            self._status_lbl.setVisible(prev_visible)
        self._transient_text = ""
        self._status_before_transient = ("", False)
        for overlay in self._all_subtitles():
            overlay.set_notice("")

    def _nudge_subtitle_scale(self, delta: float) -> None:
        ov = self._subtitle
        # 0.1 씩 더하면 부동소수 찌꺼기(1.9700000000000002)가 쌓여 그대로 저장된다.
        # 스텝이 소수 둘째 자리까지라 매번 반올림해 누적 자체를 막는다.
        ov.set_font_scale(round(self._subtitle_font_scale + delta, 2))
        self._subtitle_font_scale = round(ov.font_scale, 2)   # clamp 된 실제 값을 되받는다
        self._apply_subtitle_prefs()
        self._show_transient(
            tr("자막 크기 {pct}%").format(pct=round(self._subtitle_font_scale * 100))
        )
        self._queue_subtitle_prefs_save()

    def _nudge_subtitle_bottom(self, delta: float) -> None:
        ov = self._subtitle
        ov.set_bottom_ratio(round(self._subtitle_bottom_ratio + delta, 2))
        self._subtitle_bottom_ratio = round(ov.bottom_ratio, 2)
        self._apply_subtitle_prefs()
        self._show_transient(
            tr("자막 위치 {pct}%").format(pct=round(self._subtitle_bottom_ratio * 100))
        )
        self._queue_subtitle_prefs_save()

    def _queue_subtitle_prefs_save(self) -> None:
        self._prefs_save_timer.start()

    def _flush_subtitle_prefs(self) -> None:
        try:
            # 설정 파일에 1.9700000000000002 같은 값이 박히지 않게 저장 직전에도 자른다
            # (설정 파일을 손으로 고쳐 들어온 값에도 적용된다).
            settings.save_setting("subtitle_font_scale", round(self._subtitle_font_scale, 2))
            settings.save_setting("subtitle_bottom_ratio", round(self._subtitle_bottom_ratio, 2))
        except OSError:
            logger.exception("자막 표시 설정 저장 실패")

    def _reset_subtitle_prefs(self) -> None:
        self._subtitle_font_scale = LyricsOverlay.FONT_SCALE_DEFAULT
        self._subtitle_bottom_ratio = LyricsOverlay.BOTTOM_RATIO_DEFAULT
        self._apply_subtitle_prefs()
        self._show_transient(tr("자막 크기·위치 초기화"))
        self._queue_subtitle_prefs_save()

    def _apply_subtitle_position(self, pos_ms: int) -> None:
        """재생 위치에 맞춰 자막을 갱신한다. **줄이 바뀔 때만** 다시 그린다."""
        self._apply_video_subtitle_position(pos_ms)
        if self._track is None:
            return
        idx = self._track.index_at(pos_ms)
        line_index = self._track.cue(idx).line_index if idx is not None else -1
        if line_index == self._current_line_index:
            return
        self._current_line_index = line_index
        cue: LyricsCue | None = self._track.cue(idx) if idx is not None else None
        for overlay in self._all_subtitles():
            overlay.set_cue(cue)
        self.current_line_changed.emit(line_index)

    def _set_subtitle_offset(self, ms: int) -> None:
        if self._track is None:
            return
        self._track.offset_ms = ms
        for bar in self._all_bars():
            bar.set_subtitle_offset_ms(self._track.offset_ms)
        # 오프셋이 바뀌면 현재 줄 판정이 달라지므로 강제로 다시 계산한다.
        # -2는 "다음 계산을 반드시 반영하라"는 센티넬 — -1(자막 없음)과 구분해야
        # 오프셋을 늘려 자막이 사라지는 전이(-1로의 변화)도 반영된다.
        self._current_line_index = -2
        self._apply_subtitle_position(self.position_ms)
        self.subtitle_offset_changed.emit(self._track.offset_ms)

    def _nudge_subtitle_offset(self, delta_ms: int) -> None:
        if self._track is None:
            return
        self._set_subtitle_offset(self._track.offset_ms + int(delta_ms))

    def _sync_subtitle_here(self, pos_ms: int) -> None:
        """현재 재생 위치가 '지금 표시 중인 줄'의 시작이 되도록 오프셋을 맞춘다."""
        if self._track is None:
            return
        idx = self._track.index_at(pos_ms)
        if idx is None:
            return
        cue = self._track.cue(idx)
        self._set_subtitle_offset(pos_ms - cue.start_ms)

    def _reset_subtitle_offset(self) -> None:
        self._set_subtitle_offset(0)
