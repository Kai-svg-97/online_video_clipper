"""앨범 보기 UI 상태 — 목록·상세·자동 채우기를 백그라운드로 돌린다.

앨범 상세는 **네트워크**(외부 앨범 정보) + **DB 스캔**(카테고리 전체 노래)이 함께 걸리고,
빠진 곡 채우기는 곡마다 yt-dlp 검색이라 더 느리다. 셋 다 QThread로 내보내고 세대
카운터로 늦게 도착한 결과를 버린다 — 앨범을 빠르게 오가면 이전 조회 결과가 나중에
도착해 다른 앨범 화면을 덮어쓰는 사고가 난다.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from PyQt6.QtCore import QObject, QThread, pyqtSignal

logger = logging.getLogger(__name__)


class _CallWorker(QThread):
    """인자 없는 호출 하나를 백그라운드에서 실행한다."""

    finished_ok = pyqtSignal(object)
    finished_err = pyqtSignal(str)

    def __init__(self, fn: Callable, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._fn = fn

    def run(self) -> None:
        try:
            self.finished_ok.emit(self._fn())
        except Exception as exc:   # noqa: BLE001 — UI로 사유를 올린다
            logger.exception("앨범 작업 실패")
            self.finished_err.emit(str(exc))


class _FillWorker(QThread):
    """빠진 수록곡 채우기 — 곡 하나가 붙을 때마다 신호를 낸다(도착하는 대로 표시)."""

    track_filled = pyqtSignal(object)   # AlbumTrackDTO
    finished_ok = pyqtSignal(int)
    finished_err = pyqtSignal(str)

    def __init__(self, fn: Callable, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._fn = fn
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        try:
            count = self._fn(
                on_track=lambda dto: self.track_filled.emit(dto),
                should_cancel=lambda: self._cancel,
            )
            self.finished_ok.emit(int(count or 0))
        except Exception as exc:   # noqa: BLE001
            logger.exception("앨범 수록곡 채우기 실패")
            self.finished_err.emit(str(exc))


class _AddTracksWorker(QThread):
    """앨범 곡 담기 — 곡마다 등록(yt-dlp 메타데이터 조회)이라 진행률을 흘려보낸다."""

    progress = pyqtSignal(int, int)     # (완료, 전체)
    finished_ok = pyqtSignal(int)
    finished_err = pyqtSignal(str)

    def __init__(self, fn: Callable, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._fn = fn
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        try:
            count = self._fn(
                on_progress=lambda done, total: self.progress.emit(done, total),
                should_cancel=lambda: self._cancel,
            )
            self.finished_ok.emit(int(count or 0))
        except Exception as exc:   # noqa: BLE001
            logger.exception("앨범 곡 담기 실패")
            self.finished_err.emit(str(exc))


class AlbumViewModel(QObject):
    """앨범 그리드/상세 화면의 상태."""

    albums_changed = pyqtSignal(list)      # list[AlbumCardDTO]
    detail_ready = pyqtSignal(object)      # AlbumDetailDTO | None
    track_filled = pyqtSignal(object)      # AlbumTrackDTO — 자동 매핑 1곡 완료
    fill_finished = pyqtSignal(int)
    unknown_resolved = pyqtSignal(int)     # 앨범을 추정해 채운 곡 수(>0이면 목록 재조회)
    add_progress = pyqtSignal(int, int)    # 카테고리 담기 진행 (완료, 전체)
    tracks_added = pyqtSignal(int)         # 카테고리에 담은 곡 수
    track_removed = pyqtSignal(object)     # AlbumTrackDTO — 삭제 후 '없음'으로 되돌린 슬롯
    loading_changed = pyqtSignal(bool)
    error_occurred = pyqtSignal(str)

    def __init__(
        self,
        get_albums,          # GetAlbumsHandler
        get_detail,          # GetAlbumDetailHandler
        fill_tracks=None,    # FillAlbumTracksHandler | None
        resolve_unknown=None,  # ResolveUnknownAlbumsHandler | None
        add_tracks=None,     # AddAlbumTracksHandler | None
        remove_track_link=None,   # RemoveAlbumTrackLinkHandler | None
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._get_albums = get_albums
        self._get_detail = get_detail
        self._fill = fill_tracks
        self._resolve = resolve_unknown
        self._add = add_tracks
        self._remove_link = remove_track_link
        self._add_worker: _AddTracksWorker | None = None
        self._workers: list[QThread] = []
        self._fill_worker: _FillWorker | None = None
        self._gen = 0
        self._albums: list = []
        self._detail = None

    # ── 조회 ────────────────────────────────────────────────────────
    @property
    def albums(self) -> list:
        return self._albums

    @property
    def detail(self):
        return self._detail

    def load_albums(self, category_id=None, category_ids=None) -> None:
        from application.song.album_queries import GetAlbumsQuery  # noqa: PLC0415

        query = GetAlbumsQuery(
            category_id=category_id, category_ids=list(category_ids or [])
        )
        self._gen += 1
        gen = self._gen
        self.loading_changed.emit(True)
        self._run(
            lambda: self._get_albums.handle(query),
            lambda result: self._on_albums(result, gen),
        )

    def load_detail(self, album_key: str, category_id=None, category_ids=None,
                    refresh: bool = False) -> None:
        from application.song.album_queries import GetAlbumDetailQuery  # noqa: PLC0415

        query = GetAlbumDetailQuery(
            album_key=album_key,
            category_id=category_id,
            category_ids=list(category_ids or []),
            refresh=refresh,
        )
        self._gen += 1
        gen = self._gen
        self.loading_changed.emit(True)
        self._run(
            lambda: self._get_detail.handle(query),
            lambda result: self._on_detail(result, gen),
        )

    # ── 자동 채우기 ─────────────────────────────────────────────────
    def fill_missing_tracks(self, album_key: str, category_id=None, category_ids=None,
                            cookie_opts=None) -> None:
        """라이브러리에 없는 수록곡에 official 음원 영상을 붙인다(곡마다 검색 1회)."""
        if self._fill is None or not album_key:
            self.fill_finished.emit(0)
            return
        from application.song.album_queries import FillAlbumTracksCommand  # noqa: PLC0415

        self.cancel_fill()
        cmd = FillAlbumTracksCommand(
            album_key=album_key,
            category_id=category_id,
            category_ids=list(category_ids or []),
            cookie_opts=dict(cookie_opts or {}),
        )
        worker = _FillWorker(lambda **kw: self._fill.handle(cmd, **kw), self)
        worker.track_filled.connect(self.track_filled)
        worker.finished_ok.connect(self.fill_finished)
        worker.finished_err.connect(self.error_occurred)
        worker.finished.connect(lambda w=worker: self._retire(w))
        self._fill_worker = worker
        self._workers.append(worker)
        worker.start()

    def cancel_fill(self) -> None:
        """진행 중인 채우기를 멈춘다 — 다른 앨범으로 넘어갈 때 호출한다."""
        worker = self._fill_worker
        self._fill_worker = None
        if worker is not None and worker.isRunning():
            worker.cancel()
            try:
                worker.track_filled.disconnect()
                worker.finished_ok.disconnect()
            except TypeError:
                logger.debug("채우기 워커 신호가 이미 해제됨")

    def add_tracks_to_category(self, detail, category_id=None) -> None:
        """앨범의 자동 매핑 곡들을 카테고리에 담는다(곡마다 등록이라 백그라운드)."""
        if self._add is None or detail is None:
            self.tracks_added.emit(0)
            return
        from application.song.album_queries import AddAlbumTracksCommand  # noqa: PLC0415

        cmd = AddAlbumTracksCommand(
            album_title=detail.album_title,
            artist=detail.artist,
            category_id=category_id,
            tracks=list(detail.tracks),
        )
        self.cancel_add()
        worker = _AddTracksWorker(lambda **kw: self._add.handle(cmd, **kw), self)
        worker.progress.connect(self.add_progress)
        worker.finished_ok.connect(self.tracks_added)
        worker.finished_err.connect(self.error_occurred)
        worker.finished.connect(lambda w=worker: self._retire(w))
        self._add_worker = worker
        self._workers.append(worker)
        worker.start()

    def cancel_add(self) -> None:
        """담기 진행 중이면 멈춘다(앨범을 옮기거나 화면을 떠날 때)."""
        worker = self._add_worker
        self._add_worker = None
        if worker is not None and worker.isRunning():
            worker.cancel()

    def resolve_unknown_albums(self, category_id=None, category_ids=None) -> None:
        """앨범 값이 빈 노래의 앨범을 외부 조회로 추정해 채운다(백그라운드)."""
        if self._resolve is None:
            return
        from application.song.album_queries import (  # noqa: PLC0415
            ResolveUnknownAlbumsCommand,
        )

        cmd = ResolveUnknownAlbumsCommand(
            category_id=category_id, category_ids=list(category_ids or [])
        )
        self._run(
            lambda: self._resolve.handle(cmd),
            lambda count: self.unknown_resolved.emit(int(count or 0)),
        )

    def remove_track_link(self, disc_no: int, track_no: int) -> None:
        """자동 매핑을 지운다 — 잘못 붙은 음원(동명이곡·커버 등)을 사용자가 직접 제거.

        DB 삭제 한 줄이라 네트워크가 없어 QThread 없이 즉시 처리한다. 성공하면 그
        슬롯을 '없음'으로 되돌린 DTO를 실어 ``track_removed``를 방출한다 — 화면은
        전체를 다시 조회하지 않고 그 자리만 갱신한다(다른 슬롯의 자동 채우기 결과가
        섞여 들어올 여지를 없앤다).
        """
        if self._remove_link is None or self._detail is None:
            return
        from application.song.album_dtos import TRACK_ORIGIN_MISSING, AlbumTrackDTO  # noqa: PLC0415
        from application.song.album_queries import RemoveAlbumTrackLinkCommand  # noqa: PLC0415

        target = next(
            (t for t in self._detail.tracks if t.slot == (disc_no, track_no)), None
        )
        if target is None:
            return
        try:
            self._remove_link.handle(
                RemoveAlbumTrackLinkCommand(
                    album_key=self._detail.key, disc_no=disc_no, track_no=track_no
                )
            )
        except Exception as exc:   # noqa: BLE001 — UI로 사유를 올린다
            logger.exception("자동 매핑 삭제 실패")
            self.error_occurred.emit(str(exc))
            return
        missing = AlbumTrackDTO(
            track_no=target.track_no,
            disc_no=target.disc_no,
            title=target.title,
            artist=target.artist,
            duration_sec=target.duration_sec,
            origin=TRACK_ORIGIN_MISSING,
        )
        self.track_removed.emit(missing)

    # ── 내부 ───────────────────────────────────────────────────────
    def _run(self, fn: Callable, on_ok: Callable) -> None:
        worker = _CallWorker(fn, self)
        worker.finished_ok.connect(on_ok)
        worker.finished_err.connect(self._on_err)
        worker.finished.connect(lambda w=worker: self._retire(w))
        self._workers.append(worker)
        worker.start()

    def _retire(self, worker: QThread) -> None:
        if worker in self._workers:
            self._workers.remove(worker)
        if worker is self._fill_worker:
            self._fill_worker = None
        if worker is self._add_worker:
            self._add_worker = None

    def _on_albums(self, albums: list, gen: int) -> None:
        if gen != self._gen:
            return
        self._albums = albums or []
        self.loading_changed.emit(False)
        self.albums_changed.emit(self._albums)

    def _on_detail(self, detail, gen: int) -> None:
        if gen != self._gen:
            return
        self._detail = detail
        self.loading_changed.emit(False)
        self.detail_ready.emit(detail)

    def _on_err(self, msg: str) -> None:
        self.loading_changed.emit(False)
        self.error_occurred.emit(msg)

    def shutdown(self) -> None:
        """종료 시 워커 정리 (MainWindow.closeEvent → LibraryPanel)."""
        self.cancel_fill()
        self.cancel_add()
        for worker in list(self._workers):
            if worker.isRunning():
                worker.wait(3000)
        self._workers.clear()
