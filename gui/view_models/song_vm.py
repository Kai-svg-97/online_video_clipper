from __future__ import annotations

import logging
from uuid import UUID

from PyQt6.QtCore import QObject, QThread, pyqtSignal

from application.song.commands import (
    AddLyricsSourceCommand,
    AddLyricsSourceHandler,
    DeleteLyricsSourceCommand,
    DeleteLyricsSourceHandler,
    FetchSongInfoCommand,
    FetchSongInfoHandler,
    ReorderLyricsSourcesCommand,
    ReorderLyricsSourcesHandler,
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
from application.song.dtos import LyricsSourceDTO, SongInfoDTO
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

    def __init__(
        self,
        *,
        get_song_info: GetSongInfoHandler,
        fetch_song: FetchSongInfoHandler,
        set_flag: SetSongFlagHandler,
        update_field: UpdateSongFieldHandler,
        update_lyrics: UpdateSongLyricsHandler,
        translate_lyrics: TranslateSongLyricsHandler,
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
        self._set_flag = set_flag
        self._update_field = update_field
        self._update_lyrics = update_lyrics
        self._translate = translate_lyrics
        self._list_sources = list_sources
        self._add_source = add_source
        self._update_source = update_source
        self._delete_source = delete_source
        self._reorder_sources = reorder_sources
        self._current: UUID | None = None
        self._workers: list[_SongFetchWorker] = []
        self._in_flight: set[UUID] = set()   # 조회 중인 video_id — 같은 영상 중복 실행 방지

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

    def search_next_source(self, video_id: UUID) -> None:
        """'다음 출처' — 현재 가사 출처 다음부터 순환 검색해 가사를 교체한다."""
        self._current = video_id
        dto = self.get_song_info(video_id)
        current_src = dto.source_name if dto else ""
        self._start_fetch(
            FetchSongInfoCommand(
                video_id=video_id, force=True, fetch_lyrics=True,
                from_source_name=current_src or None,
            )
        )

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
