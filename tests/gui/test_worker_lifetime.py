"""실행 중인 QThread가 파괴돼 앱이 종료되던 경로를 고정한다.

Qt는 실행 중인 QThread가 파괴되면 **프로세스를 즉시 죽인다**
(`QThread: Destroyed while thread '' is still running` → abort). 그래서 이 회귀는
예외로 잡히지 않고 테스트 프로세스째 사라진다 — 즉 "테스트가 통과했다"는 것 자체가
증거다. 여기서는 파괴 조건이 만들어지지 않는다는 것(부모 없음 + 레지스트리 보유)을
직접 확인한다.

실제 증상: 스트림 URL을 받는 도중 뒤로가기를 누르면 앱이 통째로 꺼졌다.
"""
from __future__ import annotations

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import QApplication, QWidget

from gui.workers import retire_thread, running_count, track_thread, wait_all


class _Sleeper(QThread):
    done = pyqtSignal(str)

    def __init__(self, msec: int = 120, parent=None) -> None:
        super().__init__(parent)
        self._msec = msec

    def run(self) -> None:
        self.msleep(self._msec)
        self.done.emit("ok")


def _drain(qtbot, thread: QThread) -> None:
    """워커가 끝날 때까지 기다린다.

    끝나면 레지스트리가 ``deleteLater``로 정리하므로 C++ 객체가 먼저 사라질 수 있다 —
    그때 파이썬 래퍼를 만지면 RuntimeError다(정리 완료로 본다).
    """
    def finished() -> bool:
        try:
            return not thread.isRunning()
        except RuntimeError:
            return True

    qtbot.waitUntil(finished, timeout=3000)
    QApplication.processEvents()


class TestTrackThread:
    def test_부모에서_떼어_내_위젯과_함께_죽지_않게_한다(self, qtbot):
        holder = QWidget()
        qtbot.addWidget(holder)
        worker = _Sleeper(parent=holder)

        track_thread(worker)

        assert worker.parent() is None
        worker.start()
        _drain(qtbot, worker)

    def test_실행_중에는_레지스트리가_붙들고_끝나면_놓는다(self, qtbot):
        worker = _Sleeper()
        before = running_count()

        track_thread(worker)
        worker.start()
        assert running_count() == before + 1

        _drain(qtbot, worker)
        qtbot.waitUntil(lambda: running_count() == before, timeout=3000)

    def test_두_번_등록해도_한_번만_센다(self, qtbot):
        worker = _Sleeper()
        before = running_count()

        track_thread(worker)
        track_thread(worker)

        assert running_count() == before + 1
        worker.start()
        _drain(qtbot, worker)


class TestRetireThread:
    def test_실행_중_워커는_신호만_끊고_계속_붙든다(self, qtbot):
        worker = _Sleeper()
        got: list = []
        worker.done.connect(got.append)
        before = running_count()
        worker.start()

        retire_thread(worker, worker.done)

        assert running_count() == before + 1     # 참조를 버려도 파괴되지 않는다
        _drain(qtbot, worker)
        assert got == []                          # 늦게 온 결과는 무시된다

    def test_이미_끝난_워커는_붙들지_않는다(self, qtbot):
        worker = _Sleeper(msec=1)
        worker.start()
        _drain(qtbot, worker)
        before = running_count()

        retire_thread(worker, worker.done)

        assert running_count() == before

    def test_None은_그냥_넘어간다(self):
        retire_thread(None)   # 예외 없이 무시

    def test_wait_all은_남은_워커를_기다린다(self, qtbot):
        worker = track_thread(_Sleeper(msec=80))
        worker.start()

        wait_all(3000)

        assert not worker.isRunning()
        QApplication.processEvents()


class TestWidgetOwnedLoaders:
    """카드·행이 지워져도 로더가 함께 파괴되지 않아야 한다."""

    def test_앨범_카드의_자켓_로더는_부모가_없다(self, qtbot):
        from application.song.album_dtos import AlbumCardDTO
        from gui.panels.album_panel import _AlbumCard

        # 연결 거부가 즉시 나는 로컬 주소 — 실제 네트워크로 나가지 않는다.
        dto = AlbumCardDTO(
            key="k", album_title="A", artist="B",
            artwork_url="http://127.0.0.1:9/none.jpg",
        )
        card = _AlbumCard(dto)
        qtbot.addWidget(card)

        loader = card._loader
        assert loader is not None
        assert loader.parent() is None      # 카드가 지워져도 스레드는 남는다
        card.deleteLater()
        QApplication.processEvents()
        _drain(qtbot, loader)

    def test_연관영상_행의_썸네일_로더도_부모가_없다(self, qtbot):
        from gui.panels.video_detail_panel import RelatedItem, _RelatedRow

        item = RelatedItem(
            key="k", title="t", channel="c", duration_sec=None, meta_text="",
            payload=None, thumb_path="", thumb_url="http://127.0.0.1:9/none.jpg",
        )
        row = _RelatedRow(item)
        qtbot.addWidget(row)

        loader = row._loader
        assert loader is not None
        assert loader.parent() is None
        row.deleteLater()
        QApplication.processEvents()
        _drain(qtbot, loader)
