"""영상 등록과 등록 직후 자동 보강(요약/가사).

보강은 **동시 1건**으로 직렬화한다 — Gemini 요약 추출이 브라우저를 띄우므로
병렬로 돌리면 창이 여러 개 뜨고 메모리가 튄다(`_pending_enrich` 큐).
"""
from __future__ import annotations

import logging
from uuid import UUID

from application.library.commands import AddVideoCommand
from gui.view_models.library.workers import _AddVideoWorker, _EnrichWorker

logger = logging.getLogger(__name__)


class RegistrationMixin:
    """URL을 라이브러리에 등록하고, 설정이 켜져 있으면 보강을 큐에 넣는다."""

    def add_video(self, url: str, category_id: UUID | None = None) -> None:
        cmd = AddVideoCommand(url=url, category_id=category_id)
        worker = _AddVideoWorker(self._add_video, cmd)
        worker.finished_ok.connect(lambda vid: self._on_add_ok(url, vid))
        worker.finished_err.connect(lambda err: self._on_add_err(url, err))
        worker.finished.connect(lambda: self._add_workers.remove(worker))
        self._add_workers.append(worker)
        self._start_worker(worker)
        self.video_add_started.emit(url)

    def _on_add_ok(self, url: str, video_id: object = None) -> None:
        self._refresh_videos(bust_cache=True)
        self._refresh_tags()
        self.video_add_finished.emit(url)
        if isinstance(video_id, UUID):
            self._maybe_enrich(video_id, url)

    def _on_add_err(self, url: str, error: str) -> None:
        # Do NOT emit video_add_finished here — that signal implies success.
        # Emit a status-bar clear via a blank finished, then show the real error.
        self.video_add_finished.emit("")   # clears "영상 등록 중:" status message
        self.error_occurred.emit(error)

    # ── 등록 후 자동 보강 (요약/가사) ──────────────────────────────────
    def _maybe_enrich(self, video_id: UUID, url: str) -> None:
        """설정이 켜져 있으면 보강을 큐에 넣는다(동시 1건)."""
        if self._enrich_video is None:
            return
        try:
            import config.settings as _s  # noqa: PLC0415
            if not getattr(_s, "AUTO_ENRICH_ON_ADD", True):
                return
        except Exception:
            logger.exception("자동 보강 설정 조회 실패")
            return
        self._pending_enrich.append((video_id, url))
        self._drain_enrich()

    def _drain_enrich(self) -> None:
        """대기 중인 보강 작업을 하나 꺼내 실행한다(이미 실행 중이면 대기)."""
        if self._enrich_workers or not self._pending_enrich:
            return
        video_id, url = self._pending_enrich.popleft()
        from application.library.commands import EnrichVideoCommand  # noqa: PLC0415

        # kind는 상태바 라벨용 사전 판정 — 실제 분기는 핸들러가 결정한다.
        try:
            kind = "song" if self._enrich_video.is_song_video(video_id) else "summary"
        except Exception:
            logger.exception("보강 종류 판정 실패: %s", video_id)
            kind = "summary"

        worker = _EnrichWorker(
            self._enrich_video, EnrichVideoCommand(video_id=video_id), url
        )
        worker.finished_result.connect(self._on_enrich_done)
        worker.finished.connect(lambda: self._release_enrich(worker))
        self._enrich_workers.append(worker)
        self._start_worker(worker)
        self.enrich_started.emit(url, kind)

    def _release_enrich(self, worker) -> None:
        if worker in self._enrich_workers:
            self._enrich_workers.remove(worker)
        self._drain_enrich()

    def _on_enrich_done(self, url: str, kind: str, ok: bool, detail: str) -> None:
        self.enrich_finished.emit(url, kind, ok, detail)
