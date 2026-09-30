"""StreamSourceMixin — 재생 소스 확보(로컬·스트림·실시간 remux)와 실패 시 방식 전환.

    InlinePlayer에 섞여 들어가는 mixin이라 위젯 상태를 그대로 쓴다
    (런타임 클래스는 하나다 — 조립은 `gui/widgets/video_player.py`).
"""
from __future__ import annotations

import logging
from pathlib import Path

from PyQt6.QtCore import QTimer, QUrl
from PyQt6.QtMultimedia import QMediaPlayer

from gui.text import tr
from gui.widgets.player.constants import _MAX_STREAM_RETRIES
from gui.widgets.player.stream import _StreamWorker
from gui.workers import retire_thread, track_thread

logger = logging.getLogger(__name__)


class StreamSourceMixin:
    """스트림 워커·remux 세션·임시 파일 정리, 끊긴 remux의 EndOfMedia 판정과 병합 폴백."""

    def _reset_stream_mode(self) -> None:
        """새 영상 — 실시간 remux를 다시 처음부터 시도한다(영상마다 다르다)."""
        self._prefer_remux = True

    def _find_local_for_quality(self, short: str) -> str | None:
        """선택 품질과 일치하는 다운로드 파일 경로 반환.
        `auto` 면 품질 무관 첫 번째 파일, 없으면 None."""
        target = self._SHORT_TO_QUALITIES.get(short)  # None → 자동
        for dl in reversed(self._downloads):
            if not (dl.file_path and Path(dl.file_path).exists()):
                continue
            if target is None or dl.quality in target:
                return dl.file_path
        return None

    def _close_remux(self) -> None:
        """실시간 remux 세션을 닫는다 — 남은 ffmpeg가 상위 대역폭을 계속 먹지 않게.

        세션을 지우면 그 URL로 오는 요청이 404가 되고, 흐르던 중계도 곧 끝난다.
        seek을 반복하면 세션당 ffmpeg가 여러 번 뜨므로 정리는 필수다.
        """
        url, self._remux_url = self._remux_url, ""
        self._last_truncation_ms = -1
        self._stream_offset_ms = 0
        self._stream_duration_ms = 0
        self._pending_seek_ms = None
        self._seek_commit.stop()
        if not url or self._stream_relay is None:
            return
        try:
            self._stream_relay.close_session(url)
        except Exception:
            logger.debug("중계 세션 정리 실패", exc_info=True)

    def _cleanup_temp(self) -> None:
        """고화질 병합 임시 파일/디렉터리를 삭제한다."""
        path = self._temp_stream_path
        self._temp_stream_path = ""
        if not path:
            return
        try:
            import os  # noqa: PLC0415
            import shutil  # noqa: PLC0415
            d = os.path.dirname(path)
            if os.path.isfile(path):
                os.remove(path)
            if d and os.path.basename(d).startswith("ovc_stream_") and os.path.isdir(d):
                shutil.rmtree(d, ignore_errors=True)
        except OSError:
            logger.debug("임시 스트림 파일 정리 실패", exc_info=True)

    def _on_media_status(self, status) -> None:
        """미디어가 로드/버퍼되어 탐색 가능해지면 이어보기 위치로 이동한다.
        고정 지연(seek-after-80ms)은 네트워크 스트림에서 불안정하므로 사용하지 않는다."""
        # 끝까지 재생되면(수동 stop과 구분되는 유일한 지표) 재생목록 다음곡 신호를 낸다.
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            # remux 스트림은 상위가 조각을 거부하면 **중간에서도** EndOfMedia가 된다.
            # 그대로 믿으면 재생목록이 멋대로 다음 곡으로 넘어간다 — 실제 끝 근처일
            # 때만 '다 봤다'로 친다.
            dur = self._effective_duration()
            pos = self.position_ms
            if self._remux_url and dur > 0 and pos < dur - 3000:
                # 같은 자리에서 또 끊겼다면 다시 받아도 같다 — 되풀이하지 않는다.
                stuck = abs(pos - self._last_truncation_ms) < 1000
                self._last_truncation_ms = pos
                if stuck:
                    logger.warning(
                        "remux 스트림이 같은 지점에서 반복 중단(%d ms) — 병합 방식으로", pos
                    )
                    self._fall_back_to_merge(pos)
                    return
                logger.warning(
                    "remux 스트림이 중간에서 끊김(%d/%d ms) — 다시 받아 이어 간다", pos, dur
                )
                self._seek_to(pos)
                return
            self._last_truncation_ms = -1
            self.playback_finished.emit()
            return
        if self._resume_ms <= 0:
            return
        if status in (
            QMediaPlayer.MediaStatus.LoadedMedia,
            QMediaPlayer.MediaStatus.BufferedMedia,
        ) and self._player.isSeekable():
            self._player.setPosition(self._resume_ms)
            self._resume_ms = 0

    def _start_local(self, path: str) -> None:
        self._playing_local = True
        self._player.setSource(QUrl.fromLocalFile(path))
        self._visual_stack.setCurrentIndex(1)
        self._bar.show()
        self._bar.raise_()
        QTimer.singleShot(50, self._do_play_start)

    def _fetch_stream(self) -> None:
        if not self._video_url:
            self.playback_failed.emit(tr("재생할 URL이 없습니다."))
            return
        # 이전 소스/임시 파일/중계 세션 해제 (특히 품질 전환 시)
        self._player.setSource(QUrl())
        self._cleanup_temp()
        self._close_remux()
        self._status_lbl.setText(
            tr("고화질 준비 중…") if self._current_merge else tr("스트림 URL 가져오는 중…")
        )
        self._status_lbl.show()
        # 이전 워커가 살아 있으면 늦게 도착하는 신호를 무시한다.
        # 참조만 버리면 실행 중인 QThread가 파괴돼 프로세스가 죽는다 — retire_thread가
        # 신호를 끊고 끝날 때까지 대신 붙들어 준다(gui/workers.py).
        retire_thread(self._worker, "stream_ready", "progress", "failed")
        # 부모를 주지 않는다 — 플레이어가 사라져도 스레드가 함께 파괴되지 않게.
        self._worker = track_thread(_StreamWorker(
            self._video_url, self._current_quality_fmt, self._current_merge,
            prefer_remux=self._prefer_remux,
            relay=self._stream_relay,
        ))
        # 끝나면 참조를 놓는다 — 끝난 워커를 계속 들고 있으면 뒤늦은 정리에서 헷갈린다.
        self._worker.finished.connect(lambda w=self._worker: self._forget_stream_worker(w))
        self._worker.stream_ready.connect(self._on_stream_ready)
        self._worker.progress.connect(self._on_merge_progress)
        self._worker.failed.connect(self._on_stream_failed)
        self._worker.start()

    def _forget_stream_worker(self, worker) -> None:
        """스트림 워커가 끝나면 참조를 놓는다(다음 정리에서 죽은 객체를 만지지 않게)."""
        if self._worker is worker:
            self._worker = None

    def _on_merge_progress(self, pct: int) -> None:
        self._status_lbl.setText(tr("고화질 준비 중…  {pct}%").format(pct=pct))
        self._status_lbl.show()

    def _on_stream_ready(
        self, src: str, quality: str, is_local: bool, duration_ms: int = 0
    ) -> None:
        self._status_lbl.hide()
        self._playing_local = is_local
        self._temp_stream_path = src if is_local else ""
        # duration_ms > 0 이면 실시간 remux 스트림이다 — 재생기가 길이도 seek도 모르는
        # 소스라 길이는 우리가 들고, seek은 ?ss= 로 새 연결을 여는 방식으로 처리한다.
        self._remux_url = src if (duration_ms > 0 and not is_local) else ""
        self._stream_duration_ms = duration_ms if self._remux_url else 0
        self._pending_seek_ms = None
        if self._remux_url:
            # 이어보기는 스트림 시작점에 태워 보낸다 — seek 불가 소스라 재생 후에는
            # 옮길 수 없다(`_on_media_status`의 isSeekable 경로를 타지 못한다).
            self._stream_offset_ms = max(0, self._resume_ms)
            self._resume_ms = 0
            src = f"{self._remux_url}?ss={self._stream_offset_ms / 1000:.3f}"
        else:
            self._stream_offset_ms = 0
        self._player.setSource(QUrl.fromLocalFile(src) if is_local else QUrl(src))
        self._publish_duration()
        self._visual_stack.setCurrentIndex(1)
        self._bar.show()
        self._bar.raise_()
        self._stream_quality_label = quality  # metadata 업데이트 기준으로 사용
        self._bar.set_quality(quality or "")
        QTimer.singleShot(50, self._do_play_start)

    def _on_stream_failed(self, err: str) -> None:
        self._status_lbl.hide()
        self.playback_failed.emit(err)

    def _fall_back_to_merge(self, resume_ms: int) -> None:
        """실시간 remux를 포기하고 예전 방식(전체를 받아 두고 재생)으로 내려간다.

        원본이 먼 오프셋을 거부하는 영상이 있다(실측: 파일 절반 이후 바이트에 403).
        그런 영상은 **처음부터 순차로 받는 것만** 허용되므로, 받아 둔 뒤 재생하면
        seek까지 정상으로 돌아온다. 기다림이 생기지만 재생을 포기하는 것보다 낫다.
        """
        self._prefer_remux = False
        self._resume_ms = max(0, resume_ms)
        self._stream_retries = 0
        self._close_remux()
        self._status_lbl.setText(tr("스트림이 불안정해 고화질을 준비합니다…"))
        self._status_lbl.show()
        self._fetch_stream()

    def _on_error(self, error, error_string: str) -> None:
        if error == QMediaPlayer.Error.NoError:
            return
        # remux 스트림이 오류를 내면 다시 받아도 같은 원본이다 — 방식을 바꾼다.
        if self._remux_url and self._stream_retries >= _MAX_STREAM_RETRIES:
            logger.warning("remux 스트림 재생 오류 — 병합 방식으로: %s", error_string)
            self._fall_back_to_merge(self.position_ms)
            return
        # 스트리밍 재생 오류는 URL 만료·일시적 거부가 대부분이라, 새 URL을 받아 한 번은
        # 조용히 다시 시도한다(사용자에게는 잠깐 버퍼링한 것처럼 보인다). 로컬 파일
        # 재생 오류는 다시 받아도 같은 파일이라 재시도하지 않는다.
        if (
            self._video_url
            and not self._playing_local
            and self._stream_retries < _MAX_STREAM_RETRIES
        ):
            self._stream_retries += 1
            logger.warning(
                "재생 오류 — 스트림을 다시 받아 재시도(%d/%d): %s",
                self._stream_retries, _MAX_STREAM_RETRIES, error_string,
            )
            self._player.stop()
            self._player.setSource(QUrl())
            self._fetch_stream()
            return
        logger.warning("재생 오류(재시도 소진): %s / url=%s", error_string, self._video_url)
        self.stop()
        self.playback_failed.emit(error_string)

    def show_playback_error(self, message: str) -> None:
        """재생 실패를 영상 자리에 표시한다.

        예전에는 실패하면 곧바로 기본 브라우저를 열었다. 사용자는 **앱에서 보려고**
        누른 것이므로 창이 튀는 것 자체가 불편하고, 원인도 알 수 없었다. 이제는 이유를
        보여주고, 브라우저로 갈지는 상단 🌐 버튼으로 직접 고르게 한다.
        """
        self._visual_stack.setCurrentIndex(0)
        text = message.strip().replace("\n", " ")
        if len(text) > 110:
            text = text[:110] + "…"
        self._status_lbl.setText(
            tr("재생 실패: {text} — 🌐 버튼으로 브라우저에서 열 수 있습니다.").format(text=text)
        )
        self._status_lbl.show()
