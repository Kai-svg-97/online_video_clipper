"""PlaybackMixin — 영상 적재·재생/정지·볼륨·재생 상태·화질 전환·다운로드 요청.

    InlinePlayer에 섞여 들어가는 mixin이라 위젯 상태를 그대로 쓴다
    (런타임 클래스는 하나다 — 조립은 `gui/widgets/video_player.py`).
"""
from __future__ import annotations

import logging

from PyQt6.QtCore import QUrl
from PyQt6.QtMultimedia import QMediaPlayer

from application.library.dtos import DownloadInfoDTO
from domain.download.value_objects import DownloadSettings
from gui.text import tr
from gui.text.labels import quality_badge_text
from gui.widgets.player.controls import _ControlBar
from gui.widgets.player.stream import _FormatProbeWorker, _HEIGHT_CACHE, _cache_heights
from gui.workers import retire_thread, track_thread

logger = logging.getLogger(__name__)


class PlaybackMixin:
    """재생 흐름의 바깥 뼈대. 스트림 확보 세부는 `StreamSourceMixin`에 있다."""

    def toggle_play(self) -> None:
        """재생/일시정지 — 컨트롤바 밖(미니바 등)에서 부르는 공개 진입점."""
        self._toggle_play()

    def load(
        self,
        video_url: str,
        downloads: list[DownloadInfoDTO],
        thumbnail_pixmap=None,
        title: str = "",
        resume_ms: int = 0,
    ) -> None:
        # 세션 공유 화질은 InlinePlayer **클래스** 속성이다 — 조립부를 위에서 임포트하면
        # 순환이 되므로 여기서 불러온다.
        from gui.widgets.video_player import InlinePlayer  # noqa: PLC0415

        self.stop()
        # 새 영상이므로 이전 영상의 구간을 반드시 지운다 — 남겨 두면 엉뚱한
        # 지점에서 건너뛴다(조회가 비동기라 늦게 도착하는 결과도 있다).
        self._skip_segments = []
        self._skipped_once = set()
        self._video_url   = video_url
        self._video_title = title
        self._downloads   = downloads
        self._resume_ms   = resume_ms
        self._stream_retries = 0   # 영상이 바뀌면 재시도 예산도 새로 준다
        self._reset_stream_mode()  # remux가 버티는지는 영상마다 다르다 — 다시 시도
        self._playing_local  = False
        self._current_quality_fmt   = InlinePlayer._last_quality_fmt
        self._current_merge         = InlinePlayer._last_quality_merge
        self._current_quality_short = InlinePlayer._last_quality_short
        self._stream_quality_label = ""
        self.set_lyrics(None)   # 이전 영상의 자막이 남지 않게 초기화
        self._clear_video_subtitles()
        self._load_video_subtitle_list()
        self._visual_stack.setCurrentIndex(0)
        if thumbnail_pixmap and not thumbnail_pixmap.isNull():
            self._thumb_label.setPixmap(thumbnail_pixmap)
        else:
            self._thumb_label.clear()
            self._thumb_label.setText(tr("미리보기 없음") if not video_url else "")
        self._status_lbl.hide()
        self._bar.set_quality("")
        # 화질 목록은 영상마다 다르다 — 캐시가 있으면 즉시, 없으면 ⬇ 클릭 시 조회한다.
        self._bar.set_available_heights(_HEIGHT_CACHE.get(video_url))
        self._bar.set_download_busy(False)
        self._bar.show()
        self._bar.raise_()
        self._hide_timer.stop()

    def play(self) -> None:
        local = self._find_local_for_quality(self._current_quality_short)
        if local:
            self._start_local(local)
            return
        self._fetch_stream()

    def stop(self) -> None:
        # 분리 재생 창(PiP/전체화면)이 열려 있으면 출력을 인라인으로 복귀 후 정리
        if self._pip_win:
            self._exit_pip()
        if self._fs_win:
            self._exit_fullscreen()
        self._player.stop()
        self._player.setSource(QUrl())   # 파일 핸들 해제 후 임시 파일 삭제 가능
        self._cleanup_temp()
        self._close_remux()
        self._hide_timer.stop()
        if self._worker:
            # 시그널을 먼저 끊고(늦게 오는 결과 무시) 스레드가 끝날 때까지 붙든다.
            # 예전엔 quit()+deleteLater()였는데, quit()은 이벤트 루프만 끝내므로
            # yt-dlp를 도는 run()은 계속 실행되고, 그 상태로 삭제되면 Qt가 프로세스를
            # 죽였다(스트림을 받는 도중 뒤로가기 → 앱 종료).
            retire_thread(self._worker, "stream_ready", "progress", "failed")
            self._worker = None
        if self._probe:
            # 화질 조회 결과가 늦게 와도 이미 다른 영상으로 넘어갔을 수 있다.
            # 스트림 워커와 같은 이유로 quit()+deleteLater()는 쓰지 않는다 —
            # yt-dlp를 도는 run()은 quit()으로 멈추지 않는다.
            retire_thread(self._probe, "heights_ready", "failed")
            self._probe = None
        self._bar.set_download_busy(False)
        self._visual_stack.setCurrentIndex(0)
        self._status_lbl.hide()
        self._bar.show()
        self._bar.raise_()
        self._bar.set_playing(False)
        # 정지는 '같은 영상을 멈춘' 경우도 있으므로 트랙은 유지하고 현재 줄만 지운다.
        # (다른 영상으로 넘어가는 초기화는 load()가 set_lyrics(None)으로 처리한다.)
        self._current_line_index = -1
        for overlay in self._all_subtitles():
            overlay.set_cue(None)

    def is_playing(self) -> bool:
        return self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState

    def _toggle_play(self) -> None:
        state = self._player.playbackState()
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self._player.pause()
        elif state == QMediaPlayer.PlaybackState.PausedState:
            self._player.play()
        else:
            self.play()

    def _change_volume(self, delta: int) -> None:
        vol = max(0, min(self._volume + delta, 100))
        self._volume = vol
        self._audio.setVolume(vol / 100.0)
        self._bar.set_volume(vol)
        if self._fs_win:
            self._fs_win.bar.set_volume(vol)
        if self._pip_win:
            self._pip_win.bar.set_volume(vol)

    def _toggle_mute(self) -> None:
        self._is_muted = not self._is_muted
        self._audio.setMuted(self._is_muted)
        self._bar.set_muted(self._is_muted)
        if self._fs_win:
            self._fs_win.bar.set_muted(self._is_muted)
        if self._pip_win:
            self._pip_win.bar.set_muted(self._is_muted)

    def _on_volume_changed(self, vol: int) -> None:
        self._volume = vol
        self._audio.setVolume(vol / 100.0)
        muted = vol == 0
        if muted != self._is_muted:
            self._is_muted = muted
            self._audio.setMuted(muted)
            self._bar.set_muted(muted)

    def _on_playback_state(self, state: QMediaPlayer.PlaybackState) -> None:
        playing = state == QMediaPlayer.PlaybackState.PlayingState
        self.playing_changed.emit(playing)
        self._bar.set_playing(playing)
        if self._fs_win:
            self._fs_win.bar.set_playing(playing)
        if self._pip_win:
            self._pip_win.bar.set_playing(playing)
        if playing:
            # 실제로 재생이 시작됐으면 재시도 예산을 되돌린다. 여기서 초기화하지 않고
            # 스트림을 받을 때마다 초기화하면 오류→재시도가 무한히 반복될 수 있다.
            self._stream_retries = 0
            self._bar.show()
            self._bar.raise_()
            self._hide_timer.start()
            self._cursor_poll.start()
        else:
            self._hide_timer.stop()
            self._show_timer.stop()
            self._cursor_poll.stop()
            self._bar.show()
            self._bar.raise_()
        if state == QMediaPlayer.PlaybackState.StoppedState:
            self._visual_stack.setCurrentIndex(0)

    def _do_play_start(self) -> None:
        """재생 시작. 이어보기(resume_ms) seek은 미디어가 탐색 가능해지는
        시점(_on_media_status)에서 견고하게 처리한다."""
        self._player.play()

    def _on_quality_changed(self, fmt: str, short: str, merge: bool) -> None:
        # 세션 공유 화질은 InlinePlayer **클래스** 속성이다 — 조립부를 위에서 임포트하면
        # 순환이 되므로 여기서 불러온다.
        from gui.widgets.video_player import InlinePlayer  # noqa: PLC0415

        self._current_quality_fmt   = fmt
        self._current_merge         = merge
        self._current_quality_short = short
        InlinePlayer._last_quality_fmt   = fmt
        InlinePlayer._last_quality_merge = merge
        InlinePlayer._last_quality_short = short
        state = self._player.playbackState()
        if state != QMediaPlayer.PlaybackState.StoppedState:
            # 현재 재생 위치를 저장해 새 화질에서 이어서 재생.
            # remux 스트림은 재생기 위치가 0부터 다시 세므로 절대 위치를 써야 한다.
            self._resume_ms = self.position_ms
            self._player.stop()
            self._visual_stack.setCurrentIndex(0)
            local = self._find_local_for_quality(short)
            if local:
                self._bar.set_quality(quality_badge_text(short))
                self._start_local(local)
            else:
                self._bar.set_quality(tr("전환 중…"))
                self._fetch_stream()

    def _on_metadata_changed(self) -> None:
        """yt-dlp 보고 품질이 없을 때만 Qt 메타데이터 해상도로 뱃지를 보완한다."""
        if self._stream_quality_label:
            return
        try:
            from PyQt6.QtMultimedia import QMediaMetaData  # noqa: PLC0415
            meta = self._player.metaData()
            res = meta.value(QMediaMetaData.Key.Resolution)
            if res is not None and hasattr(res, "height"):
                h = res.height()
                if h > 0:
                    self._bar.set_quality(f"{h}p")
        except Exception:
            logger.exception("Qt 메타데이터 해상도 뱃지 보완 실패")

    def _on_download_requested(self, settings: DownloadSettings) -> None:
        self.download_requested.emit(self._video_url, self._video_title, settings)

    def _on_download_menu_requested(self) -> None:
        """⬇ 클릭 — 사용 가능한 화질을 확인한 뒤 메뉴를 연다.

        고정 목록을 그대로 띄우면 최대 1080p인 영상에도 4K가 나열돼 혼란스럽다.
        조회는 네트워크 작업이라 워커에서 하고, 끝나면 그 바의 메뉴를 대신 연다.
        실패하면 예전처럼 전체 목록을 보여준다(다운로드 자체는 막지 않는다).
        """
        bar = self.sender() if isinstance(self.sender(), _ControlBar) else self._bar
        url = self._video_url
        cached = _HEIGHT_CACHE.get(url)
        if not url or cached is not None:
            bar.set_available_heights(cached)
            bar.open_download_menu()
            return

        bar.set_download_busy(True)

        def _ready(u: str, heights: list, b=bar) -> None:
            _cache_heights(u, heights)
            b.set_download_busy(False)
            b.set_available_heights(heights)
            b.open_download_menu()

        def _failed(_msg: str, b=bar) -> None:
            b.set_download_busy(False)
            b.set_available_heights(None)   # 알 수 없으면 전체 목록으로
            b.open_download_menu()

        # 조회 중 화면을 벗어나도 스레드가 파괴되지 않도록 부모 없이 만들어 등록한다.
        self._probe = track_thread(_FormatProbeWorker(url, info_source=self._info_source))
        self._probe.heights_ready.connect(_ready)
        self._probe.failed.connect(_failed)
        self._probe.start()
