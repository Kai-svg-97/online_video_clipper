"""저사양 PC(4GB RAM) 메모리 최적화 회귀 테스트 (Step 4).

CLAUDE.md "Memory Optimization Rules"가 요구하는 세 가지를 코드로 고정한다:

1. 썸네일 LRU 캐시가 상한을 실제로 지키고, 밀려난 QPixmap이 파이썬 GC로 회수되는가
   (evict가 "목록에서만 빼기"가 아니라 실제 메모리 반환으로 이어지는가).
2. 1000장 카드를 스크롤하듯 연속 로드해도 캐시가 무한히 자라지 않고, 화면을
   떠나 목록을 비우면(`set_videos([])`) 모델이 보유한 DTO 참조도 함께 풀리는가.
3. 로컬 QThread 워커(`gui/workers.py`)가 retire된 뒤 파이썬 참조가 실제로
   해제되는가 — `test_worker_lifetime.py`는 레지스트리 카운트(`running_count`)만
   보므로, 여기서는 weakref로 "그 객체 자체가 GC 대상이 되는가"까지 확인한다.
   같은 파일에서 `_ThumbBgLoader`가 `track_thread`로도 등록되는지(이 세션에서
   고친 부분)를 함께 고정한다 — 등록되지 않으면 앱 종료 시 `wait_all()`이
   이 로더를 기다리지 못해, 아직 도는 QThread가 파괴되며 프로세스가 죽는
   기존 회귀 패턴(gui/workers.py 문서)이 재발한다.
"""
from __future__ import annotations

import dataclasses
import gc
import weakref
from uuid import uuid4

import pytest
from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QApplication

from application.library.dtos import VideoDTO
from gui.workers import retire_thread, running_count, track_thread, wait_all


def _drain(qtbot, thread: QThread) -> None:
    """워커가 끝날 때까지 기다린다 (tests/gui/test_worker_lifetime.py와 동일 도우미)."""

    def finished() -> bool:
        try:
            return not thread.isRunning()
        except RuntimeError:
            return True

    qtbot.waitUntil(finished, timeout=3000)
    QApplication.processEvents()


def _make_dto(i: int) -> VideoDTO:
    return VideoDTO(
        id=uuid4(),
        url=f"https://youtu.be/vid{i}",
        title=f"영상 {i}",
        channel_name="채널",
        thumbnail_path=f"thumb_{i}.jpg",   # 실제 파일 없음 — placeholder 경로만 필요
        duration_sec=120,
        favorite=False,
        watched=False,
        category_id=None,
    )


def _thread_done(thread: QThread) -> bool:
    """이미 정리돼 접근이 안 되는 객체도 '끝났다'로 본다(뒷정리 전용)."""
    try:
        return thread.isFinished()
    except RuntimeError:
        return True


def _make_dto_with_thumb(path: str) -> VideoDTO:
    return dataclasses.replace(_make_dto(0), thumbnail_path=path)


class TestThumbnailCacheEviction:
    """`gui/panels/library/thumbnails.py:_ThumbnailCache` — LRU 상한·회수."""

    def test_상한을_넘으면_가장_오래된_항목을_치운다(self, qapp_instance):
        from gui.panels.library.thumbnails import _ThumbnailCache

        cache = _ThumbnailCache(maxsize=5)
        for i in range(8):
            pm = QPixmap(4, 4)
            pm.fill()
            cache.put(f"k{i}", pm)

        assert len(cache._cache) == 5
        for i in range(3):            # 가장 먼저 넣은 0,1,2는 밀려났다
            assert cache.get(f"k{i}") is None
        for i in range(3, 8):         # 최근 5개는 남아 있다
            assert cache.get(f"k{i}") is not None

    def test_get으로_접근하면_최근사용으로_갱신돼_밀려나지_않는다(self, qapp_instance):
        from gui.panels.library.thumbnails import _ThumbnailCache

        cache = _ThumbnailCache(maxsize=3)
        for i in range(3):
            pm = QPixmap(4, 4)
            pm.fill()
            cache.put(f"k{i}", pm)

        cache.get("k0")   # k0를 다시 사용 — 가장 최근으로 갱신
        pm3 = QPixmap(4, 4)
        pm3.fill()
        cache.put("k3", pm3)   # 상한 초과 → 가장 오래 안 쓴 것(k1)이 밀려나야 한다

        assert cache.get("k0") is not None    # 최근 사용이라 살아남음
        assert cache.get("k1") is None        # 안 쓴 채 가장 오래돼 밀려남
        assert cache.get("k2") is not None
        assert cache.get("k3") is not None

    def test_밀려난_QPixmap은_참조가_없으면_GC로_회수된다(self, qapp_instance):
        """evict가 dict에서 빼는 것에 그치지 않고 실제 메모리 반환으로 이어지는지 확인.

        캐시가 유일한 강한 참조원이라면, evict된 뒤 로컬 참조도 지우면
        weakref가 죽어야 한다(= QPixmap이 실제로 회수됨).
        """
        from gui.panels.library.thumbnails import _ThumbnailCache

        cache = _ThumbnailCache(maxsize=3)
        victim = QPixmap(4, 4)
        victim.fill()
        cache.put("victim", victim)
        ref = weakref.ref(victim)
        del victim
        gc.collect()
        assert ref() is not None      # 아직 캐시가 들고 있으므로 살아 있어야 정상

        # 캐시 상한을 넘겨 victim을 밀어낸다
        for i in range(5):
            pm = QPixmap(4, 4)
            pm.fill()
            cache.put(f"other{i}", pm)
            del pm

        assert cache.get("victim") is None   # 캐시에서 빠졌다
        gc.collect()
        assert ref() is None                  # 그리고 실제로 회수됐다

    def test_peek는_최근사용_순서를_바꾸지_않는다(self, qapp_instance):
        """워커 스레드가 `get`(move_to_end)을 부르면 메인 스레드 `put`과 OrderedDict를
        동시에 변경한다 — 워커는 순서를 바꾸지 않는 `peek`만 써야 한다(성능 배치 7, C1)."""
        from gui.panels.library.thumbnails import _ThumbnailCache

        cache = _ThumbnailCache(maxsize=3)
        for k in ("a", "b", "c"):
            pm = QPixmap(4, 4)
            pm.fill()
            cache.put(k, pm)

        assert cache.peek("a") is not None   # 보기만 한다 — 최근 사용으로 올리지 않는다
        pm = QPixmap(4, 4)
        pm.fill()
        cache.put("d", pm)

        assert cache.peek("a") is None        # a가 가장 오래된 채라 쫓겨났다
        assert cache.peek("b") is not None

    def test_peek의_미스는_None이다(self, qapp_instance):
        from gui.panels.library.thumbnails import _ThumbnailCache

        assert _ThumbnailCache(maxsize=3).peek("없음") is None

    def test_메인_put과_워커_peek를_동시에_돌려도_안전하다(self, qapp_instance):
        import threading

        from gui.panels.library.thumbnails import _ThumbnailCache

        cache = _ThumbnailCache(maxsize=50)
        pm = QPixmap(2, 2)
        pm.fill()
        errors: list[BaseException] = []

        def reader() -> None:
            try:
                for i in range(5000):
                    cache.peek(f"k{i % 200}")
            except BaseException as exc:   # noqa: BLE001 - 스레드 예외를 모아 단언한다
                errors.append(exc)

        t = threading.Thread(target=reader)
        t.start()
        for i in range(5000):
            cache.put(f"k{i % 200}", pm)
        t.join(10)

        assert not t.is_alive()
        assert errors == []
        assert len(cache._cache) <= 50


def _calls_get_on_thumb_cache(source: str, class_name: str, method: str) -> list[int]:
    """`class_name.method` 본문에서 `_thumb_cache.get(...)` 호출의 줄 번호."""
    import ast

    tree = ast.parse(source)
    hits: list[int] = []
    for cls in ast.walk(tree):
        if not (isinstance(cls, ast.ClassDef) and cls.name == class_name):
            continue
        for fn in cls.body:
            if not (isinstance(fn, ast.FunctionDef) and fn.name == method):
                continue
            for node in ast.walk(fn):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "get"
                ):
                    target = node.func.value
                    name = target.id if isinstance(target, ast.Name) else getattr(target, "attr", "")
                    if name == "_thumb_cache":
                        hits.append(node.lineno)
    return hits


class TestLoaderDoesNotTouchLru:
    """워커(`_ThumbBgLoader.run`)는 캐시 순서를 바꾸는 `get`을 부르지 않는다(C1)."""

    def test_스캐너가_위반을_찾는다(self):
        src = (
            "class _ThumbBgLoader:\n"
            "    def run(self):\n"
            "        if _thumb_cache.get(k) is not None:\n"
            "            pass\n"
        )
        assert _calls_get_on_thumb_cache(src, "_ThumbBgLoader", "run") == [3]

    def test_run은_thumb_cache_get을_부르지_않는다(self):
        from pathlib import Path

        path = Path(__file__).resolve().parents[2] / "gui" / "panels" / "library" / "thumbnails.py"
        hits = _calls_get_on_thumb_cache(
            path.read_text(encoding="utf-8"), "_ThumbBgLoader", "run"
        )
        assert hits == [], f"워커가 LRU 순서를 바꾼다(thumbnails.py:{hits}) — peek를 쓴다"


class TestThumbnailCacheMemoryBudget:
    """LRU_THUMBNAIL_MAX × 렌더 크기 종류 수가 만드는 실제 바이트 예산을 고정한다.

    CLAUDE.md Memory Optimization Rules: "LRU 최대 100개(렌더 크기당)". 이 값이나
    렌더 크기 상수가 조용히 커지면 저사양 PC 예산을 넘길 수 있으므로, 계산한
    상한을 여기 못박아 둔다 — 상수를 바꾸는 사람이 이 테스트의 실패로 예산
    변화를 인지하게 한다.
    """

    def test_전체_캐시_최악의_경우_메모리_상한이_예산_안에_있다(self):
        from config.settings import LRU_THUMBNAIL_MAX, THUMBNAIL_HEIGHT, THUMBNAIL_WIDTH
        from gui.panels.detail.related import _RelatedRow
        from gui.panels.library.constants import (
            _TH_LIST,
            _THUMB_RENDER_SIZE_KINDS,
            _TW_LIST,
        )
        from gui.panels.library.thumbnails import _thumb_cache

        # 실사용 렌더 크기 3종 — 하나라도 추가되면 _THUMB_RENDER_SIZE_KINDS도
        # 함께 늘어나야 한다는 걸 상기시키기 위해 여기서 직접 나열한다.
        sizes = [
            (THUMBNAIL_WIDTH, THUMBNAIL_HEIGHT),   # 아이콘 그리드 (320x180)
            (_TW_LIST, _TH_LIST),                  # 리스트 뷰 (213x120)
            (_RelatedRow._TW, _RelatedRow._TH),    # 상세화면 연관 영상 행 (168x94)
        ]
        assert len(sizes) == _THUMB_RENDER_SIZE_KINDS

        bytes_per_px = 4   # QPixmap은 기본적으로 픽셀당 4바이트(ARGB32/RGB32급)로 상주한다
        max_entries = _thumb_cache._maxsize
        assert max_entries == LRU_THUMBNAIL_MAX * _THUMB_RENDER_SIZE_KINDS

        # 최악의 경우: 캐시 전체가 가장 큰 렌더 크기(아이콘 그리드) 하나로만 채워짐
        # — 단일 OrderedDict를 공유하므로 "크기별 100개 보장"이 구조적으로 강제되지
        # 않는다(사용자가 아이콘 그리드만 오래 스크롤하면 전량이 이 크기로 채워질 수
        # 있다). 그래도 저사양 PC(4GB) 예산 안에 들어야 한다.
        worst_w, worst_h = max(sizes, key=lambda wh: wh[0] * wh[1])
        worst_case_bytes = max_entries * worst_w * worst_h * bytes_per_px
        BUDGET_BYTES = 80 * 1024 * 1024   # 80MB — 4GB 중 썸네일 캐시가 쓸 여유

        assert worst_case_bytes <= BUDGET_BYTES, (
            f"썸네일 캐시 최악 예상 메모리 {worst_case_bytes / 1024 / 1024:.1f}MB가 "
            f"예산 {BUDGET_BYTES / 1024 / 1024:.0f}MB를 넘었다 — "
            "LRU_THUMBNAIL_MAX 또는 렌더 크기 상수를 다시 검토할 것"
        )


class TestVideoListModelCleanup:
    """1000개 카드를 스크롤로 훑고 목록을 비우는 시나리오 시뮬레이션."""

    def test_1000개_로드_후_스크롤해도_캐시는_상한을_유지한다(self, qapp_instance, monkeypatch):
        import gui.panels.library.thumbnails as thumb_mod

        small_cache = thumb_mod._ThumbnailCache(maxsize=60)
        monkeypatch.setattr(thumb_mod, "_thumb_cache", small_cache)

        # 가상 스크롤: 뷰포트에 들어온 카드만 그때 디코딩한다는 전제를 그대로
        # 흉내낸다 — 1000개 카드를 순서대로 "보이게" 하며 각각 썸네일을 요청한다.
        for i in range(1000):
            thumb_mod._load_thumb(f"thumb_{i}.jpg", 320, 180)

        assert len(small_cache._cache) == 60   # 마지막 60장만 남는다(무한 증가 없음)
        # 스크롤 맨 처음 카드는 이미 밀려났다
        assert small_cache.get("thumb_0.jpg@320x180") is None
        # 가장 마지막(현재 뷰포트) 카드는 살아 있다
        assert small_cache.get("thumb_999.jpg@320x180") is not None

    def test_목록을_비우면_모델이_들고_있던_DTO_참조가_풀린다(self, qapp_instance):
        from gui.panels.library.models import VideoListModel

        model = VideoListModel()
        dtos = [_make_dto(i) for i in range(1000)]
        model.set_videos(dtos)
        assert model.rowCount() == 1000

        # 화면을 떠날 때(카테고리 전환 등)와 동일하게 빈 목록으로 교체한다.
        watched = weakref.ref(dtos[500])
        del dtos
        model.set_videos([])

        assert model.rowCount() == 0
        gc.collect()
        assert watched() is None   # 모델도 다른 곳도 더는 참조하지 않는다


class _Worker(QThread):
    """워커 GC 확인용 최소 QThread — 즉시 끝난다."""

    done = pyqtSignal()

    def run(self) -> None:
        self.done.emit()


class TestWorkerReferenceRelease:
    """retire_thread 이후 워커 객체 자체가 실제로 GC 대상이 되는지 확인.

    `test_worker_lifetime.py`는 `running_count()`(레지스트리 부기)만 검증한다.
    부기가 0으로 돌아와도 다른 어딘가(클로저·리스트 등)가 여전히 강한 참조를
    쥐고 있으면 메모리는 누수된다 — 그래서 여기서는 weakref로 "그 객체 자체가
    사라지는가"까지 본다.
    """

    def test_retire_후_참조를_모두_버리면_워커는_GC된다(self, qtbot):
        worker = track_thread(_Worker())
        worker.start()
        _drain(qtbot, worker)

        retire_thread(worker, "done")
        ref = weakref.ref(worker)
        del worker
        gc.collect()

        assert ref() is None

    def test_ThumbBgLoader도_track_thread_레지스트리에_잡힌다(self, qtbot):
        """이번 세션에서 추가한 고정: `_start_thumb_preload`가 만드는
        `_ThumbBgLoader`는 자체 리스트(`_active_thumb_loaders`)만으로는
        `MainWindow.closeEvent`의 `wait_all()`이 알 수 없다. `track_thread`로도
        등록해야 앱 종료 시 이 로더도 함께 기다려진다(gui/panels/library/
        mixins/video_list.py:_start_thumb_preload).
        """
        from gui.panels.library.thumbnails import _ThumbBgLoader

        before = running_count()
        loader = _ThumbBgLoader([])   # 빈 목록 — 배치 없이 즉시 finished
        track_thread(loader)
        loader.start()

        _drain(qtbot, loader)
        qtbot.waitUntil(lambda: running_count() == before, timeout=3000)

    def test_wait_all은_실행_중인_로더를_기다린다(self, qtbot):
        from gui.panels.library.thumbnails import _ThumbBgLoader

        loader = _ThumbBgLoader([("존재하지않음.jpg", 10, 10)] * 3)
        track_thread(loader)
        loader.start()

        wait_all(3000)

        assert not loader.isRunning()
        QApplication.processEvents()

    # ── 성능 배치 7, C2 — 실제 `_start_thumb_preload` 경로 ───────────────────

    @pytest.fixture
    def preload_panel(self, qtbot, library_vm, download_vm, clip_vm, tmp_path, monkeypatch):
        from PyQt6.QtGui import QColor, QImage

        from gui.panels.library import thumbnails
        from gui.panels.library_panel import LibraryPanel

        img = QImage(64, 36, QImage.Format.Format_RGB32)
        img.fill(QColor("#336699"))
        assert img.save(str(tmp_path / "t.jpg"), "JPG")
        monkeypatch.setattr(thumbnails, "THUMBNAIL_DIR", str(tmp_path))
        thumbnails._thumb_cache._cache.clear()

        panel = LibraryPanel(vm=library_vm, clip_vm=clip_vm, download_vm=download_vm)
        qtbot.addWidget(panel)
        monkeypatch.setattr(panel, "_maybe_fill_viewport", lambda: None)
        yield panel
        for worker in list(library_vm._list_workers):
            worker.wait(3000)
        library_vm.shutdown()
        thumbnails._thumb_cache._cache.clear()

    def test_끝난_로더는_deleteLater_뒤에도_접근이_안전하다(self, qtbot, preload_panel):
        from PyQt6.QtCore import QCoreApplication, QEvent

        panel = preload_panel
        panel._active_thumb_loaders.clear()
        panel._start_thumb_preload([_make_dto_with_thumb("t.jpg")])
        loader = panel._active_thumb_loaders[-1]

        qtbot.waitUntil(loader.isFinished, timeout=3000)
        qtbot.waitUntil(lambda: loader not in panel._active_thumb_loaders, timeout=3000)
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)

        # `deleteLater`를 불렀다면 여기서 "wrapped C/C++ object ... has been deleted".
        assert loader.isFinished() is True

    def test_실제_프리로드_경로의_로더가_레지스트리에_잡힌다(self, qtbot, preload_panel):
        from gui import workers

        panel = preload_panel
        panel._active_thumb_loaders.clear()
        panel._start_thumb_preload([_make_dto_with_thumb("t.jpg")])
        loader = panel._active_thumb_loaders[-1]

        assert loader in workers._RUNNING

        qtbot.waitUntil(lambda: loader not in workers._RUNNING, timeout=3000)

    def test_옛_세대_배치는_화면에_반영되지_않는다(
        self, qtbot, preload_panel, monkeypatch
    ):
        """세대 판정이 람다 기본값이든 바운드 메서드든 성질은 같다."""
        import threading

        from PyQt6.QtGui import QColor, QImage

        from gui.panels.library import thumbnails
        from gui.panels.library.mixins import video_list

        release = threading.Event()

        class _HeldLoader(QThread):
            batch_ready = pyqtSignal(list)
            made: list = []

            def __init__(self, items, parent=None) -> None:
                super().__init__(parent)
                self.items = list(items)
                _HeldLoader.made.append(self)

            def cancel(self) -> None:
                pass

            def run(self) -> None:
                release.wait(5)

        monkeypatch.setattr(video_list, "_ThumbBgLoader", _HeldLoader)
        panel = preload_panel
        notified: list = []
        monkeypatch.setattr(panel._model, "notify_thumb_cached", lambda paths: notified.append(set(paths)))
        panel._active_thumb_loaders.clear()
        _HeldLoader.made = []
        try:
            panel._start_thumb_preload([_make_dto_with_thumb("old.jpg")])
            panel._start_thumb_preload([_make_dto_with_thumb("new.jpg")])
            l1, l2 = _HeldLoader.made
            img = QImage(4, 4, QImage.Format.Format_RGB32)
            img.fill(QColor("#000000"))

            l1.batch_ready.emit([("old.jpg", 320, 180, img)])
            # 캐시 저장은 현재 동작대로 유지한다(받은 썸네일은 유효하고 LRU 상한이 있다).
            # 여기서는 화면 갱신(notify)만 현재 세대로 제한되는지 본다.
            assert notified == []

            l2.batch_ready.emit([("new.jpg", 320, 180, img)])
            assert "new.jpg@320x180" in thumbnails._thumb_cache._cache
            assert notified == [{"new.jpg"}]
        finally:
            release.set()
            for loader in _HeldLoader.made:
                qtbot.waitUntil(lambda ld=loader: _thread_done(ld), timeout=3000)
