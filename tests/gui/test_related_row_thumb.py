"""연관 영상 행(_RelatedRow) 썸네일 — 경로 해석 · 워커 디코드 · 캐시 · 수명.

배치 8 D2. 계획: `.omc/research/perf/test_plan_batch8.md` 2절(A1~A13).

- 라이브러리 썸네일은 DB처럼 **상대 이름**이라 `THUMBNAIL_DIR` 기준으로 풀어야 한다.
- 디스크 디코드는 워커 안에서 `gui.panels.feed_panel._decode_scaled`로 한다(메인 스레드 금지).
- 캐시 `put`은 메인 스레드에서만 한다.

원천은 색으로 구분한다: 라이브러리 파일 파랑, `feed_` 사본 빨강, 네트워크 초록.
"""
from __future__ import annotations

import threading
from uuid import uuid4

import pytest
from PyQt6 import sip
from PyQt6.QtCore import QBuffer, QCoreApplication, QEvent, QIODevice
from PyQt6.QtGui import QColor, QImage

import gui.panels.detail.related as related_mod
import gui.panels.feed_panel as feed_mod
import gui.panels.library.thumbnails as lib_thumbs
from gui.panels.detail.related import RelatedItem, _RelatedList, _RelatedRow
from gui.workers import running_count

MAIN_IDENT = threading.get_ident()

BLUE = "#336699"    # 라이브러리 파일
RED = "#CC3300"     # feed_ 사본
GREEN = "#33AA33"   # 네트워크 응답
VID = "vidA0000001"
URL = "https://i.ytimg.com/vi/vidA0000001/hqdefault.jpg"
CACHE_KEY = f"{VID}@168x94"


# ── 헬퍼 ────────────────────────────────────────────────────────────────
def _save_jpg(path, w: int, h: int, color: str) -> None:
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(QColor(color))
    assert img.save(str(path), "JPG")


def _jpeg_bytes(w: int, h: int, color: str) -> bytes:
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(QColor(color))
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    assert img.save(buf, "JPG")
    return bytes(buf.data())


def _center_matches(px, color: str, tol: int = 24) -> bool:
    c = px.toImage().pixelColor(px.width() // 2, px.height() // 2)
    want = QColor(color)
    return (
        abs(c.red() - want.red()) <= tol
        and abs(c.green() - want.green()) <= tol
        and abs(c.blue() - want.blue()) <= tol
    )


def _center_rgb(px) -> tuple[int, int, int]:
    c = px.toImage().pixelColor(px.width() // 2, px.height() // 2)
    return c.red(), c.green(), c.blue()


def _item(
    thumb_path: str = "fabd0001.jpg",
    thumb_url: str = "",
    yt_video_id: str = VID,
    key: str = "k1",
) -> RelatedItem:
    return RelatedItem(
        key=key,
        title="t",
        channel="c",
        duration_sec=60,
        meta_text="",
        payload=uuid4(),
        thumb_path=thumb_path,
        thumb_url=thumb_url,
        yt_video_id=yt_video_id,
    )


# ── 픽스처 ──────────────────────────────────────────────────────────────
@pytest.fixture
def thumb_dir(tmp_path, monkeypatch):
    d = tmp_path / "thumbs"
    d.mkdir()
    import config.settings as settings

    monkeypatch.setattr(settings, "THUMBNAIL_DIR", d, raising=False)
    monkeypatch.setattr(feed_mod, "THUMBNAIL_DIR", d, raising=False)
    monkeypatch.setattr(lib_thumbs, "THUMBNAIL_DIR", d, raising=False)
    monkeypatch.setattr(related_mod, "THUMBNAIL_DIR", d, raising=False)
    return d


@pytest.fixture(autouse=True)
def clean_feed_cache():
    feed_mod._feed_thumb_cache._cache.clear()
    yield
    feed_mod._feed_thumb_cache._cache.clear()


class _Resp:
    def __init__(self, content: bytes) -> None:
        self.content = content

    def raise_for_status(self) -> None:
        return None


class _NetStub:
    """`feed_panel.requests` 대역 — 실제 네트워크를 쓰지 않는다."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.response: bytes | None = None

    def get(self, url, *a, **k):
        self.calls.append(url)
        if self.response is None:
            raise ConnectionError("no network in tests")
        return _Resp(self.response)


@pytest.fixture
def no_net(monkeypatch):
    stub = _NetStub()
    monkeypatch.setattr(feed_mod, "requests", stub)
    return stub


class _DecodeSpy:
    def __init__(self) -> None:
        self.records: list[tuple] = []     # (is_main, path, (w, h), size|None)
        self.entered: list[str] = []
        self.gate = threading.Event()
        self.gate.set()

    def main_calls(self) -> list[tuple]:
        return [r for r in self.records if r[0]]


@pytest.fixture
def decode_spy(monkeypatch):
    # 구현 전에는 feed_panel에 이름이 없을 수 있다 — 원본은 라이브러리 쪽 것을 쓴다.
    original = getattr(feed_mod, "_decode_scaled", None) or lib_thumbs._decode_scaled
    spy = _DecodeSpy()

    def _spy(path, w, h):
        spy.entered.append(str(path))
        if not spy.gate.is_set():
            spy.gate.wait(5)   # 교착 방지: 5초 뒤엔 그냥 진행
        res = original(path, w, h)
        size = (res.width(), res.height()) if res is not None else None
        spy.records.append(
            (threading.get_ident() == MAIN_IDENT, str(path), (w, h), size)
        )
        return res

    monkeypatch.setattr(feed_mod, "_decode_scaled", _spy, raising=False)
    return spy


@pytest.fixture
def put_spy():
    cache = feed_mod._feed_thumb_cache
    records: list[tuple[bool, str]] = []
    orig = cache.put

    def _put(key, px):
        records.append((threading.get_ident() == MAIN_IDENT, key))
        return orig(key, px)

    cache.put = _put
    yield records
    cache.__dict__.pop("put", None)


@pytest.fixture
def fade_count(monkeypatch):
    calls = []
    orig = related_mod.fade_in

    def _fade(widget, *a, **k):
        calls.append(widget)
        return orig(widget, *a, **k)

    monkeypatch.setattr(related_mod, "fade_in", _fade)
    return calls


def _settle(qtbot, base: int) -> None:
    qtbot.waitUntil(lambda: running_count() == base, timeout=5000)


def _arrive(qtbot, row, timeout: int = 5000) -> None:
    qtbot.waitUntil(lambda: row._thumb._pixmap is not None, timeout=timeout)


def _mkrow(qtbot, item: RelatedItem) -> _RelatedRow:
    row = _RelatedRow(item)
    qtbot.addWidget(row)
    return row


def _both_files(thumb_dir) -> None:
    _save_jpg(thumb_dir / "fabd0001.jpg", 640, 360, BLUE)
    _save_jpg(thumb_dir / f"feed_{VID}.jpg", 640, 360, RED)


# ── 테스트 ──────────────────────────────────────────────────────────────
class TestPathResolution:
    def test_A1_상대경로는_썸네일폴더_기준이고_라이브러리가_feed_사본보다_먼저다(
        self, qtbot, thumb_dir, no_net
    ):
        _both_files(thumb_dir)
        base = running_count()
        row = _mkrow(qtbot, _item())

        _arrive(qtbot, row)
        _settle(qtbot, base)

        assert _center_matches(row._thumb._pixmap, BLUE), (
            f"라이브러리 썸네일(파랑)이어야 한다 — 실제 가운데 RGB={_center_rgb(row._thumb._pixmap)}"
        )

    def test_A2_라이브러리_썸네일이_있으면_네트워크도_feed_사본도_쓰지_않는다(
        self, qtbot, thumb_dir, no_net
    ):
        _save_jpg(thumb_dir / "fabd0001.jpg", 640, 360, BLUE)
        base = running_count()
        row = _mkrow(qtbot, _item(thumb_url=URL))

        try:
            qtbot.waitUntil(lambda: row._thumb._pixmap is not None, timeout=3000)
        except qtbot.TimeoutError:
            pass
        _settle(qtbot, base)

        assert no_net.calls == [], f"네트워크로 내려갔다: {no_net.calls}"
        assert not list(thumb_dir.glob("feed_*")), "feed_ 사본을 새로 썼다"
        assert row._thumb._pixmap is not None, "썸네일이 뜨지 않았다(빈칸)"
        assert _center_matches(row._thumb._pixmap, BLUE)

    def test_A8_절대경로_옛_기록도_읽는다(self, qtbot, thumb_dir, no_net, tmp_path):
        abs_file = tmp_path / "abs.jpg"
        _save_jpg(abs_file, 640, 360, BLUE)
        base = running_count()
        row = _mkrow(qtbot, _item(thumb_path=str(abs_file)))

        _arrive(qtbot, row)
        _settle(qtbot, base)

        assert _center_matches(row._thumb._pixmap, BLUE)


class TestWorkerDecode:
    def test_A3_행_생성이_디스크_디코드를_메인_스레드에서_하지_않는다(
        self, qtbot, thumb_dir, no_net, decode_spy
    ):
        _both_files(thumb_dir)
        base = running_count()
        row = _mkrow(qtbot, _item())

        assert row._thumb._pixmap is None, "생성 직후 이미 그려져 있다 — 동기 디코드다"
        _arrive(qtbot, row)
        _settle(qtbot, base)

        assert decode_spy.records, "feed_panel._decode_scaled가 한 번도 불리지 않았다"
        assert decode_spy.main_calls() == [], f"메인 스레드 디코드: {decode_spy.main_calls()}"

    def test_A4_디코드_결과는_표시_크기이고_원본_해상도가_올라오지_않는다(
        self, qtbot, thumb_dir, no_net, decode_spy
    ):
        _save_jpg(thumb_dir / "fabd0001.jpg", 1280, 720, BLUE)
        base = running_count()
        row = _mkrow(qtbot, _item())

        _arrive(qtbot, row)
        _settle(qtbot, base)

        assert decode_spy.records, "feed_panel._decode_scaled가 한 번도 불리지 않았다"
        for _main, _path, (_w, _h), size in decode_spy.records:
            assert size is not None
            assert size[0] <= 336 and size[1] <= 188, f"디코드 크기가 크다: {size}"
        px = row._thumb._pixmap
        assert px.width() == 168 and px.height() >= 94

    def test_A5_4대3_원본도_칸을_빈_띠_없이_채운다(
        self, qtbot, thumb_dir, no_net, decode_spy
    ):
        _save_jpg(thumb_dir / "fabd0001.jpg", 480, 360, BLUE)
        base = running_count()
        row = _mkrow(qtbot, _item())

        _arrive(qtbot, row)
        _settle(qtbot, base)

        px = row._thumb._pixmap
        assert px.width() >= 168 and px.height() >= 94, f"칸을 못 채운다: {px.width()}x{px.height()}"
        grabbed = row.grab()
        assert not grabbed.isNull()

    def test_A9_라이브러리_파일이_없으면_feed_사본을_쓰고_그것도_워커에서_디코드한다(
        self, qtbot, thumb_dir, no_net, decode_spy
    ):
        _save_jpg(thumb_dir / f"feed_{VID}.jpg", 640, 360, RED)
        base = running_count()
        row = _mkrow(qtbot, _item(thumb_path="missing.jpg"))

        assert row._thumb._pixmap is None, "생성 직후 이미 그려져 있다 — feed_ 단계가 동기다"
        _arrive(qtbot, row)
        _settle(qtbot, base)

        assert _center_matches(row._thumb._pixmap, RED), (
            f"feed_ 사본(빨강)이어야 한다 — RGB={_center_rgb(row._thumb._pixmap)}"
        )
        assert decode_spy.records, "feed_panel._decode_scaled가 한 번도 불리지 않았다"
        assert decode_spy.main_calls() == []


class TestCache:
    def test_A6_같은_영상의_둘째_행은_메모리_캐시에서_즉시_그린다(
        self, qtbot, thumb_dir, no_net, decode_spy, put_spy, fade_count
    ):
        _both_files(thumb_dir)
        base = running_count()
        row1 = _mkrow(qtbot, _item())
        _arrive(qtbot, row1)
        _settle(qtbot, base)

        cache = feed_mod._feed_thumb_cache
        cached = cache.get(CACHE_KEY)
        assert cached is not None, f"캐시에 {CACHE_KEY} 키가 없다"
        assert _center_matches(cached, BLUE), "캐시에는 라이브러리 썸네일이 들어가야 한다"
        assert put_spy, "put이 한 번도 불리지 않았다"
        assert all(is_main for is_main, _k in put_spy), f"워커에서 put: {put_spy}"
        decodes_before = len(decode_spy.records)
        fades_before = len(fade_count)

        row2 = _mkrow(qtbot, _item())

        assert row2._thumb._pixmap is not None, "둘째 행이 즉시 그려지지 않았다"
        assert row2._thumb._pixmap is cache.get(CACHE_KEY)
        assert len(decode_spy.records) == decodes_before
        assert len(fade_count) == fades_before
        _settle(qtbot, base)

    def test_A7_비동기_도착은_fade_in으로_얹는다(
        self, qtbot, thumb_dir, no_net, decode_spy, fade_count
    ):
        _both_files(thumb_dir)
        base = running_count()
        row = _mkrow(qtbot, _item())

        _arrive(qtbot, row)
        _settle(qtbot, base)

        assert len(fade_count) == 1, f"fade_in 호출 수 {len(fade_count)}"

    def test_A10_깨진_파일은_죽지도_영구_빈칸이_되지도_않는다_원천이_없는_경우(
        self, qtbot, thumb_dir, no_net
    ):
        (thumb_dir / "fabd0001.jpg").write_bytes(b"not an image")
        base = running_count()
        row = _mkrow(qtbot, _item(thumb_url=""))

        _settle(qtbot, base)
        qtbot.wait(50)   # 대기가 아니라 큐에 남은 신호를 흘려보내는 용도

        assert row._thumb._pixmap is None
        assert not row.grab().isNull()
        assert feed_mod._feed_thumb_cache.get(CACHE_KEY) is None, "깨진 결과가 캐시에 들어갔다"

    def test_A10_깨진_파일은_URL로_내려간다(self, qtbot, thumb_dir, no_net):
        (thumb_dir / "fabd0001.jpg").write_bytes(b"not an image")
        no_net.response = _jpeg_bytes(640, 360, GREEN)
        base = running_count()
        row = _mkrow(qtbot, _item(thumb_url=URL))

        _arrive(qtbot, row)
        _settle(qtbot, base)

        assert len(no_net.calls) == 1, f"requests.get 호출 {no_net.calls}"
        assert _center_matches(row._thumb._pixmap, GREEN), (
            f"네트워크 응답(초록)이어야 한다 — RGB={_center_rgb(row._thumb._pixmap)}"
        )


class TestLifetime:
    def test_A11_로더가_도는_중에_행이_파괴돼도_죽지_않고_스레드가_정리된다(
        self, qtbot, thumb_dir, no_net, decode_spy
    ):
        _both_files(thumb_dir)
        decode_spy.gate.clear()
        base = running_count()
        # 직접 지우는 행이라 qtbot.addWidget으로 등록하지 않는다(이중 정리 방지).
        row = _RelatedRow(_item())
        try:
            qtbot.waitUntil(lambda: len(decode_spy.entered) >= 1, timeout=3000)
            row.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            assert sip.isdeleted(row)
        finally:
            decode_spy.gate.set()
        _settle(qtbot, base)
        qtbot.wait(50)   # 도착한 결과 슬롯이 죽은 행을 건드리는지 흘려보낸다

    def test_A12_썸네일_원천이_없으면_스레드를_띄우지_않는다(
        self, qtbot, thumb_dir, no_net
    ):
        base = running_count()
        row = _mkrow(qtbot, _item(thumb_path="", thumb_url="", yt_video_id="vidZ"))

        assert running_count() == base
        qtbot.wait(50)
        assert running_count() == base
        assert row._thumb._pixmap is None
        assert not row.grab().isNull()


class TestListFill:
    def test_A13_목록_30개를_채울때_메인_디코드가_0이고_전부_도착한다(
        self, qtbot, thumb_dir, no_net, decode_spy
    ):
        items = []
        for i in range(30):
            name = f"fab{i:05d}.jpg"
            w, h = (1280, 720) if i % 2 == 0 else (480, 360)
            _save_jpg(thumb_dir / name, w, h, BLUE)
            items.append(
                _item(thumb_path=name, yt_video_id=f"vid{i:08d}", key=f"k{i}")
            )
        base = running_count()
        lst = _RelatedList()
        qtbot.addWidget(lst)

        lst.set_items(items)

        assert decode_spy.main_calls() == [], "set_items 반환 시점에 메인 스레드 디코드가 있다"
        rows = [
            lst._rel_layout.itemAt(i).widget()
            for i in range(lst._rel_layout.count())
            if isinstance(lst._rel_layout.itemAt(i).widget(), _RelatedRow)
        ]
        assert len(rows) == 30
        qtbot.waitUntil(
            lambda: all(r._thumb._pixmap is not None for r in rows), timeout=10000
        )
        _settle(qtbot, base)

        assert decode_spy.main_calls() == []
        for r in rows:
            assert _center_matches(r._thumb._pixmap, BLUE)


class TestLoaderConcurrency:
    """연관 행 로더 동시 실행 수 제한 — 동시 디코드가 GIL을 다퉈 메인 스레드를 잠식했다."""

    @staticmethod
    def _make_items(thumb_dir, n: int) -> list[RelatedItem]:
        items = []
        for i in range(n):
            name = f"cc{i:05d}.jpg"
            _save_jpg(thumb_dir / name, 640, 360, BLUE)
            items.append(
                _item(thumb_path=name, yt_video_id=f"cc{i:09d}", key=f"c{i}")
            )
        return items

    @staticmethod
    def _rows(lst) -> list[_RelatedRow]:
        out = []
        for i in range(lst._rel_layout.count()):
            w = lst._rel_layout.itemAt(i).widget()
            if isinstance(w, _RelatedRow):
                out.append(w)
        return out

    def test_B1_동시에_도는_로더는_상수를_넘지_않고_결국_전부_처리된다(
        self, qtbot, thumb_dir, no_net, decode_spy
    ):
        limit = related_mod.RELATED_THUMB_CONCURRENCY
        assert limit == 3
        items = self._make_items(thumb_dir, 30)
        decode_spy.gate.clear()
        base = running_count()
        lst = _RelatedList()
        qtbot.addWidget(lst)
        try:
            lst.set_items(items)
            qtbot.waitUntil(lambda: len(decode_spy.entered) >= limit, timeout=3000)
            qtbot.wait(100)
            assert len(decode_spy.entered) <= limit, (
                f"동시 디코드가 상한 {limit}을 넘었다: {len(decode_spy.entered)}"
            )
            assert running_count() - base <= limit
        finally:
            decode_spy.gate.set()
        rows = self._rows(lst)
        assert len(rows) == 30
        qtbot.waitUntil(
            lambda: all(r._thumb._pixmap is not None for r in rows), timeout=15000
        )
        _settle(qtbot, base)

    def test_B2_목록을_바꾸면_이전_대기열은_버려진다(
        self, qtbot, thumb_dir, no_net, decode_spy
    ):
        items = self._make_items(thumb_dir, 30)
        decode_spy.gate.clear()
        base = running_count()
        lst = _RelatedList()
        qtbot.addWidget(lst)
        try:
            lst.set_items(items)
            qtbot.waitUntil(lambda: len(decode_spy.entered) >= 3, timeout=3000)
            lst.set_items([])   # 대기 중이던 27개는 버려져야 한다
        finally:
            decode_spy.gate.set()
        _settle(qtbot, base)
        qtbot.wait(100)

        assert len(decode_spy.entered) == 3, (
            f"버려졌어야 할 대기 항목이 처리됐다: {len(decode_spy.entered)}"
        )
