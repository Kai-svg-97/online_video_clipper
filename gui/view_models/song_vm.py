from __future__ import annotations

import logging
from uuid import UUID

from PyQt6.QtCore import QObject, QThread, pyqtSignal

from application.song.commands import (
    AddLyricsSourceCommand,
    AddLyricsSourceHandler,
    ApplyLyricsCandidateCommand,
    ApplyLyricsCandidateHandler,
    DeleteLyricsSourceCommand,
    DeleteLyricsSourceHandler,
    FetchSongInfoCommand,
    FetchSongInfoHandler,
    ReorderLyricsSourcesCommand,
    ReorderLyricsSourcesHandler,
    SearchLyricsCandidatesCommand,
    SearchLyricsCandidatesHandler,
    SetLyricsOffsetCommand,
    SetLyricsOffsetHandler,
    SetSongFlagCommand,
    SetSongFlagHandler,
    TranslateSongLyricsCommand,
    TranslateSongLyricsHandler,
    UpdateLyricsSourceCommand,
    UpdateLyricsSourceHandler,
    UpdateSongFieldCommand,
    UpdateSongFieldHandler,
    UpdateSongLyricsCommand,
    UpdateSongLyricsHandler,
)
from application.song.dtos import LyricsCandidateDTO, LyricsSourceDTO, SongInfoDTO
from application.song.queries import GetSongInfoHandler, ListLyricsSourcesHandler
from domain.song.value_objects import LyricsLine

logger = logging.getLogger(__name__)


class _SongFetchWorker(QThread):
    """노래 정보(가사 포함)를 백그라운드로 조회한다."""

    done = pyqtSignal(object, bool)   # (video_id, ok)
    failed = pyqtSignal(object, str)  # (video_id, error)

    def __init__(self, handler: FetchSongInfoHandler, cmd: FetchSongInfoCommand, parent=None) -> None:
        super().__init__(parent)
        self._handler = handler
        self._cmd = cmd

    def run(self) -> None:
        try:
            agg = self._handler.handle(self._cmd)
            self.done.emit(self._cmd.video_id, agg is not None)
        except Exception as exc:
            logger.exception("노래 정보 조회 실패: %s", self._cmd.video_id)
            self.failed.emit(self._cmd.video_id, str(exc))


class _TranslateWorker(QThread):
    """현재 가사를 한글로 (재)번역한다(네트워크 — deep-translator)."""

    done = pyqtSignal(object, bool)   # (video_id, ok)
    failed = pyqtSignal(object, str)  # (video_id, error)

    def __init__(self, handler: TranslateSongLyricsHandler, cmd: TranslateSongLyricsCommand,
                 parent=None) -> None:
        super().__init__(parent)
        self._handler = handler
        self._cmd = cmd

    def run(self) -> None:
        try:
            self._handler.handle(self._cmd)
            self.done.emit(self._cmd.video_id, True)
        except Exception as exc:
            logger.exception("가사 번역 실패: %s", self._cmd.video_id)
            self.failed.emit(self._cmd.video_id, str(exc))


class _CandidateSearchWorker(QThread):
    """활성 가사 출처를 전부 훑어 후보를 모은다 — 결과를 **도착하는 대로** 방출한다.

    한 출처가 느려도 앞선 출처의 결과는 이미 화면에 떠 있으므로, 사용자는 기다리는
    동안에도 고를 수 있다. ``cancel()``은 협조적 취소다(진행 중인 HTTP 요청 하나가
    끝난 뒤 멈춘다 — 제공자 타임아웃이 짧아 충분하다).
    """

    started_source = pyqtSignal(str)          # 조회를 시작한 출처 이름
    found = pyqtSignal(str, object)           # (출처 이름, LyricsCandidateDTO) — 출처당 여러 번
    source_done = pyqtSignal(str, int)        # (출처 이름, 그 출처의 후보 수)
    finished_ok = pyqtSignal(int)             # 확보한 후보 수
    failed = pyqtSignal(str)

    def __init__(
        self,
        handler: SearchLyricsCandidatesHandler,
        cmd: SearchLyricsCandidatesCommand,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._handler = handler
        self._cmd = cmd
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        try:
            found = self._handler.handle(
                self._cmd,
                on_start=self.started_source.emit,
                on_result=self.found.emit,
                on_source_done=self.source_done.emit,
                should_cancel=lambda: self._cancelled,
            )
            self.finished_ok.emit(len(found))
        except Exception as exc:
            logger.exception("가사 후보 검색 실패: %s", self._cmd.video_id)
            self.failed.emit(str(exc))


class _ApplyCandidateWorker(QThread):
    """고른 후보를 반영한다 — 번역이 네트워크 호출이라 백그라운드로 돌린다."""

    done = pyqtSignal(object, bool)   # (video_id, ok)
    failed = pyqtSignal(object, str)  # (video_id, error)

    def __init__(
        self,
        handler: ApplyLyricsCandidateHandler,
        cmd: ApplyLyricsCandidateCommand,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._handler = handler
        self._cmd = cmd

    def run(self) -> None:
        try:
            agg = self._handler.handle(self._cmd)
            self.done.emit(self._cmd.video_id, agg is not None)
        except Exception as exc:
            logger.exception("가사 후보 적용 실패: %s", self._cmd.video_id)
            self.failed.emit(self._cmd.video_id, str(exc))


class SongViewModel(QObject):
    """상세화면 '노래' 탭의 상태를 관리한다.

    - ``load``: DB의 노래 정보를 즉시 방출하고, 가사가 없으면 백그라운드로 조회한다.
    - ``refresh``: 출처 체인/yt-dlp를 다시 돌려 메타데이터·가사를 재수집한다.
    - 편집(가수/앨범/제목/가사)·노래 토글은 동기 저장 후 최신 상태를 방출한다.
    네트워크 조회는 모두 QThread에서 실행한다.
    """

    song_info_changed = pyqtSignal(object)   # SongInfoDTO | None
    busy_changed = pyqtSignal(bool)
    sources_changed = pyqtSignal()
    error_occurred = pyqtSignal(str)
    # 가사 후보 검색 — 목록을 먼저 띄우고(조회중), 확인되는 대로 한 행씩 채운다.
    candidates_started = pyqtSignal(object, object)       # (video_id, list[출처 이름])
    candidate_ready = pyqtSignal(object, str, object)     # (video_id, 출처, DTO) — 출처당 여러 번
    candidate_source_done = pyqtSignal(object, str, int)  # (video_id, 출처, 그 출처 후보 수)
    candidates_finished = pyqtSignal(object, int)         # (video_id, 후보 수)

    def __init__(
        self,
        *,
        get_song_info: GetSongInfoHandler,
        fetch_song: FetchSongInfoHandler,
        search_candidates: SearchLyricsCandidatesHandler | None = None,
        apply_candidate: ApplyLyricsCandidateHandler | None = None,
        set_flag: SetSongFlagHandler,
        update_field: UpdateSongFieldHandler,
        update_lyrics: UpdateSongLyricsHandler,
        translate_lyrics: TranslateSongLyricsHandler,
        set_lyrics_offset: SetLyricsOffsetHandler | None = None,
        list_sources: ListLyricsSourcesHandler,
        add_source: AddLyricsSourceHandler,
        update_source: UpdateLyricsSourceHandler,
        delete_source: DeleteLyricsSourceHandler,
        reorder_sources: ReorderLyricsSourcesHandler,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._get = get_song_info
        self._fetch = fetch_song
        self._search_candidates = search_candidates
        self._apply_candidate = apply_candidate
        self._set_flag = set_flag
        self._update_field = update_field
        self._update_lyrics = update_lyrics
        self._translate = translate_lyrics
        self._set_offset = set_lyrics_offset
        self._list_sources = list_sources
        self._add_source = add_source
        self._update_source = update_source
        self._delete_source = delete_source
        self._reorder_sources = reorder_sources
        self._current: UUID | None = None
        self._workers: list[QThread] = []
        self._in_flight: set[UUID] = set()   # 조회 중인 video_id — 같은 영상 중복 실행 방지
        self._cand_worker: _CandidateSearchWorker | None = None

    # ── 조회 ─────────────────────────────────────────────────────
    def get_song_info(self, video_id: UUID) -> SongInfoDTO | None:
        try:
            return self._get.handle(video_id)
        except Exception:
            logger.exception("노래 정보 조회 실패: %s", video_id)
            return None

    def load(self, video_id: UUID) -> None:
        """DB 상태를 즉시 방출한다. 노래 정보가 아직 없으면(미조회) 영상 제목 기준으로
        메타데이터(가수·앨범·제목·발매년도)만 백그라운드로 채운다 — 가사는 조회하지 않는다
        (가사는 '가사' 레이블 옆 ⟳ 버튼으로만 조회)."""
        self._current = video_id
        dto = self.get_song_info(video_id)
        self.song_info_changed.emit(dto)
        if dto is None:
            self._start_fetch(FetchSongInfoCommand(video_id=video_id, fetch_lyrics=False))

    def refresh(self, video_id: UUID) -> None:
        """가사 갱신(⟳) — 현재 노래 정보를 기준으로 출처 체인에서 가사를 강제 재조회."""
        self._current = video_id
        self._start_fetch(
            FetchSongInfoCommand(video_id=video_id, force=True, fetch_lyrics=True)
        )

    # ── 가사 후보 목록 검색 ───────────────────────────────────────
    def search_lyrics_candidates(self, video_id: UUID) -> None:
        """활성 출처를 전부 조회해 후보 목록을 채운다(결과 도착 순서대로 방출).

        핸들러가 주입되지 않았으면(부분 배선·테스트) 기존 체인 검색으로 폴백한다.
        """
        if self._search_candidates is None:
            self.refresh(video_id)
            return
        self._current = video_id
        # 이전 검색이 돌고 있으면 취소한다 — 다른 영상의 결과가 뒤늦게 도착해
        # 지금 열린 목록에 섞이는 것을 막는다(취소된 워커의 신호는 아래에서 끊는다).
        self._cancel_candidate_search()
        names = self._search_candidates.list_source_names()
        self.candidates_started.emit(video_id, list(names))
        if not names:
            self.candidates_finished.emit(video_id, 0)
            return
        worker = _CandidateSearchWorker(
            self._search_candidates, SearchLyricsCandidatesCommand(video_id), self
        )
        worker.found.connect(
            lambda name, dto, vid=video_id: self.candidate_ready.emit(vid, name, dto)
        )
        worker.source_done.connect(
            lambda name, count, vid=video_id: self.candidate_source_done.emit(vid, name, count)
        )
        worker.finished_ok.connect(
            lambda count, vid=video_id: self.candidates_finished.emit(vid, count)
        )
        worker.failed.connect(self._on_candidates_failed)
        worker.finished.connect(
            lambda: self._workers.remove(worker) if worker in self._workers else None
        )
        self._cand_worker = worker
        self._workers.append(worker)
        worker.start()

    def _cancel_candidate_search(self) -> None:
        worker = self._cand_worker
        self._cand_worker = None
        if worker is None:
            return
        worker.cancel()
        try:
            worker.found.disconnect()
            worker.source_done.disconnect()
            worker.finished_ok.disconnect()
            worker.failed.disconnect()
        except TypeError:
            pass   # 이미 끊겨 있으면 무시

    def _on_candidates_failed(self, err: str) -> None:
        self.error_occurred.emit(err)

    def apply_lyrics_candidate(self, video_id: UUID, candidate: LyricsCandidateDTO) -> None:
        """후보 목록에서 고른 가사를 반영한다(번역 포함 — 백그라운드)."""
        if self._apply_candidate is None or candidate is None:
            return
        if video_id in self._in_flight:
            return
        self._current = video_id
        self._in_flight.add(video_id)
        self.busy_changed.emit(True)
        worker = _ApplyCandidateWorker(
            self._apply_candidate,
            ApplyLyricsCandidateCommand(video_id=video_id, candidate=candidate),
            self,
        )
        worker.done.connect(self._on_fetch_done)
        worker.failed.connect(self._on_fetch_failed)
        worker.finished.connect(
            lambda: self._workers.remove(worker) if worker in self._workers else None
        )
        self._workers.append(worker)
        worker.start()

    def translate_lyrics(self, video_id: UUID) -> None:
        """'번역' — 현재 등록된 가사를 한글로 (재)번역해 저장한다(조회와 분리)."""
        if video_id in self._in_flight:
            return
        self._current = video_id
        self._in_flight.add(video_id)
        self.busy_changed.emit(True)
        worker = _TranslateWorker(self._translate, TranslateSongLyricsCommand(video_id), self)
        worker.done.connect(self._on_fetch_done)
        worker.failed.connect(self._on_fetch_failed)
        worker.finished.connect(
            lambda: self._workers.remove(worker) if worker in self._workers else None
        )
        self._workers.append(worker)
        worker.start()

    def fetch_synced_lyrics(self, video_id: UUID) -> None:
        """'싱크 가사 찾기' — 시간 정보가 있는 가사만 채택해 교체한다.

        전 출처가 실패하면 기존 가사는 그대로 남는다(핸들러 계약).
        """
        self._current = video_id
        self._start_fetch(
            FetchSongInfoCommand(
                video_id=video_id, force=True, fetch_lyrics=True, synced_only=True
            )
        )

    def set_lyrics_offset(self, video_id: UUID, offset_ms: int) -> None:
        """자막 싱크 보정값을 저장한다(짧은 DB 쓰기라 워커 없이 동기 실행)."""
        if self._set_offset is None:
            logger.debug("오프셋 핸들러 미주입 — 저장 생략")
            return
        try:
            self._set_offset.handle(
                SetLyricsOffsetCommand(video_id=video_id, offset_ms=int(offset_ms))
            )
        except Exception as exc:
            logger.exception("자막 오프셋 저장 실패: %s", video_id)
            self.error_occurred.emit(str(exc))
        # song_info_changed는 방출하지 않는다 — 방출하면 set_song_info가 트랙을 새로
        # 만들어 사용자가 슬라이더/단축키로 조정 중인 오프셋 값이 저장 직전 값으로
        # 되돌아가는 왕복이 생긴다(플레이어가 이미 자체 상태로 반영을 마쳤음).

    def _start_fetch(self, cmd: FetchSongInfoCommand) -> None:
        # 같은 영상이 이미 백그라운드로 조회 중이면 중복 실행하지 않는다.
        # ("노래로 표시" 자동 조회 + ⟳ 갱신이 겹쳐 두 워커가 같은 행을 쓰며 경합하는 것 방지)
        if cmd.video_id in self._in_flight:
            return
        self._in_flight.add(cmd.video_id)
        self.busy_changed.emit(True)
        worker = _SongFetchWorker(self._fetch, cmd, self)
        worker.done.connect(self._on_fetch_done)
        worker.failed.connect(self._on_fetch_failed)
        worker.finished.connect(
            lambda: self._workers.remove(worker) if worker in self._workers else None
        )
        self._workers.append(worker)
        worker.start()

    def _on_fetch_done(self, video_id: object, ok: bool) -> None:
        self._in_flight.discard(video_id)
        self.busy_changed.emit(False)
        # 조회 도중 다른 영상으로 이동했으면 화면 갱신은 생략(데이터는 이미 저장됨).
        if video_id == self._current:
            self.song_info_changed.emit(self.get_song_info(video_id))

    def _on_fetch_failed(self, video_id: object, err: str) -> None:
        self._in_flight.discard(video_id)
        self.busy_changed.emit(False)
        self.error_occurred.emit(err)

    # ── 편집 (동기 저장) ──────────────────────────────────────────
    def save_field(self, video_id: UUID, field: str, value: str) -> None:
        try:
            self._update_field.handle(UpdateSongFieldCommand(video_id, field, value))
            if video_id == self._current:
                self.song_info_changed.emit(self.get_song_info(video_id))
        except Exception as exc:
            logger.exception("노래 필드 저장 실패: %s.%s", video_id, field)
            self.error_occurred.emit(str(exc))

    def save_lyrics(self, video_id: UUID, lines: list[LyricsLine]) -> None:
        try:
            self._update_lyrics.handle(UpdateSongLyricsCommand(video_id, lines))
            if video_id == self._current:
                self.song_info_changed.emit(self.get_song_info(video_id))
        except Exception as exc:
            logger.exception("가사 저장 실패: %s", video_id)
            self.error_occurred.emit(str(exc))

    def toggle_song(self, video_id: UUID, is_song: bool) -> None:
        try:
            self._set_flag.handle(SetSongFlagCommand(video_id, is_song))
        except Exception as exc:
            logger.exception("노래 토글 실패: %s", video_id)
            self.error_occurred.emit(str(exc))
            return
        dto = self.get_song_info(video_id)
        if video_id == self._current:
            self.song_info_changed.emit(dto)
        # 노래로 표시하면 영상 제목 기준으로 가수/앨범/제목/발매년도만 채운다(가사는 조회 X).
        if is_song:
            self._start_fetch(FetchSongInfoCommand(video_id=video_id, fetch_lyrics=False))

    # ── 가사 출처 레지스트리 ──────────────────────────────────────
    def list_lyrics_sources(self) -> list[LyricsSourceDTO]:
        try:
            return self._list_sources.handle()
        except Exception:
            logger.exception("가사 출처 목록 조회 실패")
            return []

    def add_lyrics_source(self, name: str, provider_key: str, base_url: str = "") -> None:
        try:
            self._add_source.handle(AddLyricsSourceCommand(name, provider_key, base_url))
            self.sources_changed.emit()
        except Exception as exc:
            self.error_occurred.emit(str(exc))

    def update_lyrics_source(
        self, source_id: UUID, *, name=None, enabled=None, base_url=None
    ) -> None:
        try:
            self._update_source.handle(
                UpdateLyricsSourceCommand(source_id, name=name, enabled=enabled, base_url=base_url)
            )
            self.sources_changed.emit()
        except Exception as exc:
            self.error_occurred.emit(str(exc))

    def delete_lyrics_source(self, source_id: UUID) -> None:
        try:
            self._delete_source.handle(DeleteLyricsSourceCommand(source_id))
            self.sources_changed.emit()
        except Exception as exc:
            self.error_occurred.emit(str(exc))

    def reorder_lyrics_sources(self, ordered_ids: list[UUID]) -> None:
        try:
            self._reorder_sources.handle(ReorderLyricsSourcesCommand(ordered_ids))
            self.sources_changed.emit()
        except Exception as exc:
            self.error_occurred.emit(str(exc))

    # ── 정리 ─────────────────────────────────────────────────────
    def shutdown(self) -> None:
        self._cancel_candidate_search()
        for worker in list(self._workers):
            try:
                if worker.isRunning():
                    worker.quit()
                    if not worker.wait(3000):
                        worker.terminate()
                        worker.wait()
            except RuntimeError:
                pass
        self._workers.clear()
