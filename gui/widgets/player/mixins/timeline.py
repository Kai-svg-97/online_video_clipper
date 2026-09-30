"""TimelineMixin — 재생 위치·길이·seek의 단일 경로와 SponsorBlock 건너뛰기.

    InlinePlayer에 섞여 들어가는 mixin이라 위젯 상태를 그대로 쓴다
    (런타임 클래스는 하나다 — 조립은 `gui/widgets/video_player.py`).
"""
from __future__ import annotations

import logging

from PyQt6.QtCore import QTimer, QUrl

from gui.text.labels import sponsor_category_label

logger = logging.getLogger(__name__)


class TimelineMixin:
    """`position_ms`·`_effective_duration`·`_publish_duration`·`_seek_to`가 사는 곳.

    재생 스트림 규칙(CLAUDE.md)의 네 진입점이 한 파일에 모여 있어야 새 경로가
    이들을 건너뛰는지 한눈에 보인다.
    """

    @property
    def position_ms(self) -> int:
        """현재 재생 위치(ms). 재생 전이면 0.

        실시간 remux 스트림에서는 재생기가 **0부터 다시 세므로**(seek 할 때마다
        ffmpeg를 그 지점에서 새로 띄운다) 그 시작 오프셋을 더해야 영상 기준 위치가
        된다. 아직 반영되지 않은 seek 요청이 있으면 그 목표를 먼저 답한다 — 안 그러면
        J/L 연타에서 매번 옛 위치를 기준으로 계산해 제자리를 맴돈다.
        """
        if self._pending_seek_ms is not None:
            return self._pending_seek_ms
        return max(0, self._player.position()) + self._stream_offset_ms

    @property
    def duration_ms(self) -> int:
        """현재 영상 길이(ms). 아직 모르면 0."""
        return self._effective_duration()

    def seek_to_ms(self, ms: int) -> None:
        """절대 위치(ms)로 재생 위치를 이동한다. 설명 타임스탬프 클릭 등에서 사용."""
        self._seek_to(ms)

    def _seek_relative(self, delta_sec: int) -> None:
        dur = self._effective_duration()
        if dur > 0:
            self._seek_to(max(0, min(self.position_ms + delta_sec * 1000, dur)))

    def set_skip_segments(self, segments: list) -> None:
        """SponsorBlock 건너뛰기 구간을 건네받는다(`domain.clip.sponsor.SkipSegment`).

        `load()`가 구간을 지우므로 **조회 결과가 늦게 와도 안전하다** — 다른 영상으로
        넘어간 뒤 도착한 결과는 그 영상에 적용되지 않는다. 지금 위치가 이미 구간
        안이면 즉시 한 번 판정한다(재생 시작 직후 도착하는 경우가 흔하다).
        """
        self._skip_segments = list(segments or [])
        if self._skip_segments:
            self._maybe_skip(self._player.position())

    def _maybe_skip(self, pos_ms: int) -> None:
        """현재 위치가 건너뛸 구간 안이면 그 끝으로 넘긴다.

        **되돌아오는 것을 막는다**: 사용자가 직접 구간 안으로 seek 했다면(지나간
        구간을 다시 보려는 것) 건너뛰지 않는다. 그 판단은 '방금 우리가 건너뛴
        구간인가'로 한다 — 한 번 건너뛴 구간은 다시 건너뛰지 않는다.
        """
        if not self._skip_segments:
            return
        from domain.clip.sponsor import segment_at  # noqa: PLC0415 (도메인 순수 함수)

        seg = segment_at(self._skip_segments, pos_ms / 1000.0)
        if seg is None or seg in self._skipped_once:
            return
        self._skipped_once.add(seg)
        self._seek_to(int(seg.end_sec * 1000))
        self.segment_skipped.emit(sponsor_category_label(seg.category))

    def _effective_duration(self) -> int:
        """영상 길이(ms). 실시간 remux 스트림은 재생기가 모르므로 yt-dlp 값을 쓴다.

        fragmented mp4를 파이프로 흘리는 소스라 길이 정보가 담기지 않는다 — 여기서
        대신 답하지 않으면 진행 막대가 끝까지 채워진 채로 멈춰 있다.
        """
        if self._stream_duration_ms > 0:
            return self._stream_duration_ms
        return max(0, self._player.duration())

    def _publish_duration(self, _dur: int = 0) -> None:
        """길이를 모든 바에 알린다. 재생기 값이 아니라 `_effective_duration`을 쓴다."""
        dur = self._effective_duration()
        self._bar.update_duration(dur)
        if self._fs_win:
            self._fs_win.bar.update_duration(dur)
        if self._pip_win:
            self._pip_win.bar.update_duration(dur)

    def _seek_to(self, ms: int) -> None:
        """모든 seek의 단일 진입점. 일반 소스는 재생기에게, remux는 우리가 처리한다."""
        ms = max(0, int(ms))
        dur = self._effective_duration()
        if dur > 0:
            ms = min(ms, dur)
        if not self._remux_url:
            self._player.setPosition(ms)
            return
        # 실제 반영은 타이머가 한다. 화면은 먼저 옮겨 둔다 — 300ms 동안 막대가
        # 옛 위치에 머물면 "눌러도 안 움직인다"로 보인다.
        self._pending_seek_ms = ms
        self._update_bars(ms, dur)
        self._seek_commit.start()

    def _commit_pending_seek(self) -> None:
        """미뤄 둔 seek을 실제 스트림 재시작으로 옮긴다."""
        ms, self._pending_seek_ms = self._pending_seek_ms, None
        if ms is None or not self._remux_url:
            return
        self._stream_offset_ms = ms
        self._player.stop()
        self._player.setSource(QUrl(f"{self._remux_url}?ss={ms / 1000:.3f}"))
        # 일시정지 중에 seek 해도 재생이 시작된다. 멈춘 채로 새 스트림을 열어 두면
        # ffmpeg가 첫 조각만 만들고 파이프가 막힌 채 대기해, 다시 누를 때까지
        # 화면이 이전 프레임 그대로여서 seek이 실패한 것처럼 보인다.
        QTimer.singleShot(0, self._do_play_start)

    def _update_bars(self, pos_ms: int, dur_ms: int) -> None:
        self._bar.update_position(pos_ms, dur_ms)
        if self._fs_win:
            self._fs_win.bar.update_position(pos_ms, dur_ms)
        if self._pip_win:
            self._pip_win.bar.update_position(pos_ms, dur_ms)

    def _on_position(self, pos: int) -> None:
        if self._pending_seek_ms is not None:
            return   # 곧 갈아탈 스트림이다 — 옛 위치를 화면에 되돌려 쓰지 않는다
        pos = max(0, pos) + self._stream_offset_ms
        self._maybe_skip(pos)
        self._update_bars(pos, self._effective_duration())
        self._apply_subtitle_position(pos)
