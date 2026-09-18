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

from gui.toast import show_toast




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
        self._request_skip_segments(feed.url)
        self._subtitle_tab.show_streaming_notice()
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

    # ── SponsorBlock 건너뛰기 ──────────────────────────────────────

    def _request_skip_segments(self, url: str) -> None:
        """이 영상의 건너뛸 구간을 조회 요청한다(결과는 비동기로 돌아온다).

        플레이어에는 `load()`가 이미 이전 영상의 구간을 지워 뒀으므로, 늦게 도착한
        결과가 엉뚱한 영상에 붙는 일은 아래 URL 대조로 한 번 더 막는다.
        """
        if self._clip_vm is None or not url:
            return
        self._clip_vm.load_skip_segments(url)

    def _on_skip_segments_loaded(self, url: str, segments: object) -> None:
        """조회 결과 도착 — **지금 보고 있는 영상일 때만** 적용한다."""
        if url != self._current_url:
            return
        try:
            self._player.set_skip_segments(list(segments or []))
        except RuntimeError:
            logger.debug("플레이어가 이미 파괴됨 — 구간 적용 생략")

    def _on_segment_skipped(self, name: str) -> None:
        show_toast(self, f"{name} 구간을 건너뛰었습니다")

    def player_position_ms(self) -> int:
        """현재 재생 위치(ms) — 이어보기 저장·미니바 표시용.

        `InlinePlayer.position_ms`는 **프로퍼티**다. 예전엔 이걸 메서드처럼 불러
        (`position_ms()`) 매번 TypeError가 났고, 그 예외를 아래 except가 삼켜
        **항상 0을 돌려줬다** — 이어보기 위치가 조용히 저장되지 않았다(테스트가
        이 메서드를 통째로 monkeypatch해 잡히지 않았다).
        """
        try:
            return int(self._player.position_ms)
        except (RuntimeError, AttributeError, TypeError):
            logger.debug("재생 위치 조회 실패 — 0으로 간주", exc_info=True)
            return 0

    def player_duration_ms(self) -> int:
        """현재 영상 길이(ms) — 미니바 슬라이더 범위용(모르면 0)."""
        try:
            return int(self._player.duration_ms)
        except (RuntimeError, AttributeError, TypeError):
            logger.debug("재생 길이 조회 실패 — 0으로 간주", exc_info=True)
            return 0

    def toggle_play(self) -> None:
        """재생/일시정지 — 미니바처럼 플레이어 밖에서 조작할 때 쓴다."""
        self._player.toggle_play()

    def seek_to_ms(self, ms: int) -> None:
        self._player.seek_to_ms(ms)

    def next_payload(self):
        """재생목록에서 지금 다음 항목(없으면 None) — 미니바 ⏭ 노출 판단용."""
        if not self._playlist or not self._current_key:
            return None
        idx = next(
            (i for i, p in enumerate(self._playlist) if _payload_key(p) == self._current_key),
            -1,
        )
        if idx < 0 or idx + 1 >= len(self._playlist):
            return None
        return self._playlist[idx + 1]

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

    def _on_playback_state_for_position(self, playing: bool) -> None:
        """재생 중일 때만 위치를 보고한다(멈춰 있으면 쓸 이유가 없다)."""
        if playing and self._detail is not None and not self._streaming:
            self._position_timer.start()
        else:
            self._position_timer.stop()

    def _report_position(self) -> None:
        """지금 재생 위치를 상위에 알린다(저장은 LibraryPanel→ViewModel이 한다).

        스트리밍(라이브러리 밖) 영상은 저장할 곳이 없어 건너뛴다.
        """
        if self._detail is None or self._streaming:
            return
        position = self.player_position_ms()
        if position > 0:
            self.playback_position_changed.emit(self._detail.id, position)

    def stop_player(self) -> None:
        # 떠나기 직전 위치를 한 번 더 남긴다 — 주기 저장만 믿으면 마지막 몇 초가 날아간다.
        self._report_position()
        self._position_timer.stop()
        self._player.stop()

    def is_playing(self) -> bool:
        """현재 영상이 재생 중인지 — 재생목록 뒤로가기 시 이어재생 판단용."""
        try:
            return self._player.is_playing()
        except RuntimeError:
            return False

    # ── 자막 색인 탭 ───────────────────────────────────────────────

    def _reload_subtitle_tab(self) -> None:
        """자막 탭을 지금 영상 기준으로 다시 그린다.

        색인이 없으면 목록 대신 '가져오기' 안내판이 뜬다 — 자동으로 받아 오지 않는
        이유는 영상마다 네트워크 왕복이 있어서다(대량 등록 경로를 막는다).
        """
        if self._subtitle_vm is None or self._detail is None:
            return
        self._subtitle_tab.clear_search()
        self._subtitle_tab.set_transcribe_available(
            self._subtitle_vm.can_transcribe and bool(self._clip_source_file)
        )
        if self._subtitle_vm.has_index(self._detail.id):
            self._subtitle_vm.load_lines(self._detail.id)
        else:
            self._subtitle_tab.set_lines([], indexed=False)

    def _on_subtitle_search(self, text: str) -> None:
        if self._subtitle_vm is None or self._detail is None:
            return
        self._subtitle_vm.load_lines(self._detail.id, text.strip())

    def _on_subtitle_lines(self, video_id, lines) -> None:
        """조회 결과 도착 — **지금 보고 있는 영상일 때만** 반영한다."""
        if self._detail is None or video_id != self._detail.id:
            return
        self._subtitle_tab.set_lines(lines, indexed=True)

    def _on_subtitle_index_requested(self) -> None:
        if self._subtitle_vm is None or self._detail is None:
            return
        self._subtitle_tab.set_busy(True)
        self._subtitle_vm.fetch_and_index(self._detail.id, self._current_url)

    def _on_subtitle_indexed(self, video_id, count: int) -> None:
        if self._detail is None or video_id != self._detail.id:
            return
        self._subtitle_tab.set_busy(False)
        if count:
            self._subtitle_vm.load_lines(self._detail.id, self._subtitle_tab.search_text)
            show_toast(self, f"자막 {count}줄을 색인했습니다")
        else:
            self._subtitle_tab.show_no_subtitle()

    def _on_subtitle_seek(self, ms: int) -> None:
        """자막 줄 클릭 → 그 시점부터 재생. 멈춰 있었다면 재생까지 시작한다."""
        try:
            self._player.seek_to_ms(int(ms))
            if not self._player.is_playing():
                self._player.toggle_play()
        except RuntimeError:
            logger.debug("플레이어가 이미 파괴됨 — 자막 점프 생략")

    def _on_subtitle_cues_ready(self, lang: str, label: str, cues) -> None:
        """재생용으로 받아 온 자막 큐를 검색 색인에도 남긴다(**공짜 경로**).

        네트워크 왕복이 없으므로 조건 없이 저장한다. 스트리밍 영상은 저장할 대상
        (라이브러리 영상)이 없어 건너뛴다.
        """
        if self._subtitle_vm is None or self._detail is None or self._streaming:
            return
        self._subtitle_vm.index_cues(self._detail.id, lang, label, cues)

    # ── 음성 인식으로 자막 만들기 ──────────────────────────────────

    def _on_transcribe_requested(self) -> None:
        """받아 둔 파일의 소리를 듣고 자막을 만든다.

        **로컬 파일이 있어야 한다** — 스트리밍만으로는 소리를 읽을 수 없다.
        `_clip_source_file`은 이 시점에 이미 채워져 있다(`load()`가 자막 탭보다 먼저
        다운로드 목록을 훑는다).
        """
        if self._subtitle_vm is None or self._detail is None:
            return
        media = self._clip_source_file or ""
        if not media:
            self._subtitle_tab.show_transcribing(
                "받아 둔 파일이 없어 음성 인식을 할 수 없습니다.\n먼저 다운로드해 주세요."
            )
            return
        if not self._subtitle_vm.transcribe(self._detail.id, media):
            return
        self._asr_downloading = False
        self._asr_stopping = False
        self._subtitle_tab.show_transcribing("음성 인식을 준비하는 중…", stoppable=True)

    def _on_transcribe_stop_requested(self) -> None:
        """중단 — **그때까지 인식한 부분은 남는다**(어댑터가 모은 것을 돌려준다).

        협조적 중단이라 즉시 멈추지 않는다. 세그먼트 경계에서 멈추므로 한 박자
        걸리고, 모델을 내려받는 중이면 그것이 끝나야 멈춘다 — 둘을 구분해 알린다.
        """
        if self._subtitle_vm is None or self._detail is None:
            return
        self._asr_stopping = True
        self._subtitle_vm.stop_transcribe(self._detail.id)
        self._subtitle_tab.show_stopping(
            "모델 내려받기가 끝나면 멈춥니다…"
            if self._asr_downloading
            else "중단하는 중… 지금까지 인식한 부분은 자막으로 남깁니다."
        )

    def _on_asr_model_downloading(self, model_key: str) -> None:
        """모델은 처음 한 번만 받는다 — 수십~수백 MB라 반드시 알린다."""
        from domain.library.transcribe import resolve_model  # noqa: PLC0415

        model = resolve_model(model_key)
        self._asr_downloading = True
        # 내려받는 동안에는 중단 버튼을 띄우지 않는다 — 협조적 중단이 세그먼트
        # 경계에서만 걸려, 눌러도 몇 분간 아무 반응이 없으면 고장처럼 보인다.
        self._subtitle_tab.show_transcribing(
            f"음성 인식 모델을 처음 한 번 내려받는 중… ({model.disk_mb}MB)\n"
            "다음부터는 바로 시작합니다."
        )

    def _on_asr_progress(self, video_id, ratio: float) -> None:
        if self._detail is None or video_id != self._detail.id:
            return
        # 첫 진행률이 왔다 = 모델은 이미 준비됐다는 뜻이다.
        self._asr_downloading = False
        if self._asr_stopping:
            return   # 중단 안내를 진행률로 덮지 않는다
        self._subtitle_tab.show_transcribing(
            f"소리를 듣는 중… {int(ratio * 100)}%", stoppable=True
        )

    def _on_asr_finished(self, video_id, count: int) -> None:
        if self._detail is None or video_id != self._detail.id:
            return
        stopped = self._asr_stopping
        self._asr_stopping = False
        self._asr_downloading = False
        if count:
            self._subtitle_vm.load_lines(self._detail.id)
            show_toast(
                self,
                f"중단 전까지 자막 {count}줄을 만들었습니다"
                if stopped
                else f"음성 인식으로 자막 {count}줄을 만들었습니다",
            )
            return
        # 결과가 없다 — **왜** 없는지는 중단했는지에 달렸다. 중단한 사람에게
        # "말을 찾지 못했다"고 하면 기능이 고장 난 것처럼 들린다.
        if stopped:
            self._subtitle_tab.show_transcribing(
                "중단했습니다. 인식된 부분이 없어 자막을 만들지 못했습니다."
            )
            return
        self._subtitle_tab.show_transcribing(
            "소리에서 말을 찾지 못했습니다.\n음악만 있거나 소리가 없는 영상일 수 있습니다."
        )
