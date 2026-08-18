"""PlayerControlMixin — 상세화면의 player 영역.

    VideoDetailWidget에 섞여 들어가는 mixin이라 위젯 상태를 그대로 쓴다
    (런타임 클래스는 하나다).
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import (
    QTime,
    QTimer,
    Qt,
)
from PyQt6.QtWidgets import (
    QLabel,
)




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


class PlayerControlMixin:
    """플레이어 연결 — 재생/정지, 자동 다음곡, 재생 실패 표시, 자막 현재 줄."""

    def load_stream(
        self,
        feed,
        related: list[RelatedItem] | None = None,
        poster=None,
        related_header: str | None = None,
    ) -> None:
        """스트리밍(구독 피드/채널) 영상 상세 — URL 직접 재생.

        feed: FeedVideoDTO. 로컬 항목이 아니므로 클립/메모/태그 편집은 비활성.
        """
        self._detail = None
        self._tag_ids = {}
        self._streaming = True
        self._stream_dto = feed          # 📁 카테고리 지정 시 등록에 쓴다
        self._current_url = feed.url
        self._current_key = getattr(feed, "yt_video_id", "") or feed.url
        self._set_crumb_path(None)

        self._player.load(feed.url, [], thumbnail_pixmap=poster)
        QTimer.singleShot(150, self._player.play)

        self._build_info(
            title=feed.title,
            channel=feed.channel_name,
            duration_sec=feed.duration_sec,
            published_at=_fmt_pub(feed.published_at),
            view_count=feed.view_count,
            favorite=False,
            watched=False,
            description="",
            tags=[],
            tag_ids={},
            allow_tag_edit=False,
        )

        # 하단 탭 — 메모/클립 비활성, 다운로드 안내만
        self._set_tabs_enabled(False)
        self._build_downloads_tab([], [])
        self._notes_edit.setReadOnly(True)
        self._notes_edit.blockSignals(True)
        self._notes_edit.setPlainText("스트리밍 영상입니다. 다운로드 후 메모/클립을 사용할 수 있습니다.")
        self._notes_edit.blockSignals(False)
        self._clip_source_file = None
        _clear_layout(self._clip_tab_layout)
        info = QLabel("스트리밍 영상은 클립을 추출할 수 없습니다.\n다운로드 후 다시 시도해 주세요.")
        info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        info.setStyleSheet(f"color:{_t().text_secondary}; font-size:10pt; padding:24px;")
        self._clip_tab_layout.addWidget(info)
        self._clip_tab_layout.addStretch()
        self._tabs.setCurrentIndex(self._TAB_FILES)

        # 노래 탭 — 스트리밍은 편집/조회 불가(카테고리에 담으면 풀린다)
        self._song_tab.set_editable(False)
        self._song_tab.set_busy(False)
        self._song_tab.set_info(None)
        self._summary_raw = ""

        self._btn_refresh.setEnabled(False)  # 스트리밍은 안정적 id 없음
        self.set_related(related or [], header=related_header)

    def player_position_ms(self) -> int:
        """현재 재생 위치(ms) — 등록 후 로컬 상세로 갈아탈 때 이어보기용."""
        try:
            return int(self._player.position_ms())
        except (RuntimeError, AttributeError, TypeError):
            return 0

    def _on_playback_finished(self) -> None:
        """현재 곡 재생이 끝나면 재생목록의 다음 항목을 자동재생 요청한다(끝이면 정지)."""
        if not self._playlist or not self._current_key:
            return
        idx = next(
            (i for i, p in enumerate(self._playlist) if _payload_key(p) == self._current_key),
            -1,
        )
        if idx < 0 or idx + 1 >= len(self._playlist):
            return   # 목록에 없거나 마지막 — 정지
        self.play_next_requested.emit(self._playlist[idx + 1])

    def _set_start_from_player(self) -> None:
        ms = self._player.position_ms
        t = QTime(0, 0, 0).addMSecs(ms)
        self._start_edit.setTime(t)

    def _set_end_from_player(self) -> None:
        ms = self._player.position_ms
        t = QTime(0, 0, 0).addMSecs(ms)
        self._end_edit.setTime(t)

    def _on_current_line_changed(self, line_index: int) -> None:
        self._song_tab.set_current_line(line_index if line_index >= 0 else None)

    def _on_play_failed(self, err: str) -> None:
        """재생 실패 — 이유를 남기고 화면에 보여준다(브라우저를 임의로 열지 않는다).

        예전에는 원인과 무관하게 곧바로 기본 브라우저를 띄웠다. 사용자는 앱에서 보려고
        누른 것이라 창이 튀는 것 자체가 불편했고, 로그도 남지 않아 왜 실패했는지
        추적할 수 없었다(실제로 이 신고가 들어왔을 때 app.log에 흔적이 전혀 없었다).
        """
        logger.warning("영상 재생 실패: %s / url=%s", err, self._current_url)
        self._player.show_playback_error(err)

    def stop_player(self) -> None:
        self._player.stop()

    def is_playing(self) -> bool:
        """현재 영상이 재생 중인지 — 재생목록 뒤로가기 시 이어재생 판단용."""
        try:
            return self._player.is_playing()
        except RuntimeError:
            return False
