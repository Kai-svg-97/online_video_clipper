"""추천 띠 제자리 갱신(D5-a)과 디스크 적중 썸네일의 메모리 캐시 적재(D5-b).

계획: `.omc/research/perf/test_plan_batch8.md` 3절(B1~B17).

- 부분 결과 → 최종 결과가 같은 영상이면 카드를 다시 만들지 않는다(로더 2배 방지).
- `feed_` 디스크 적중 썸네일도 표시 크기로 `_feed_thumb_cache`에 들어가며,
  `put`은 메인 스레드에서만 한다.
"""
from __future__ import annotations

import threading
from unittest.mock import MagicMock

import pytest
from PyQt6 import sip
from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QColor, QImage, QMouseEvent
from PyQt6.QtWidgets import QLabel

import gui.panels.feed_panel as feed_mod
import gui.panels.library.thumbnails as lib_thumbs
from application.library.dtos import FeedVideoDTO
from gui.panels.feed_panel import RecommendStrip, _FeedCard
from gui.text import tr

MAIN_IDENT = threading.get_ident()
RED = "#CC3300"


# ── 헬퍼 ────────────────────────────────────────────────────────────────
def _dto(i: int, *, final: bool, thumb_url: str = "", in_library: bool = False,
         url_override: str | None = None) -> FeedVideoDTO:
    vid = f"rec{i:08d}"
    return FeedVideoDTO(
        url=url_override or f"https://www.youtube.com/watch?v={vid}",
        title=f"최종 {i}" if final else f"부분 {i}",
        channel_name="채널",
        channel_id="UC0",
        thumbnail_url=thumb_url,
        thumbnail_path="",
        published_at="2026-09-30" if final else "",
        view_count=12345 + i if final else None,
        duration_sec=125,
        in_library=in_library,
        yt_video_id=vid,
    )


def _partial(i: int, **kw) -> FeedVideoDTO:
    return _dto(i, final=False, **kw)


def _final(i: int, **kw) -> FeedVideoDTO:
    return _dto(i, final=True, **kw)


def _thumb_url(i: int) -> str:
    return f"https://i.ytimg.com/vi/rec{i:08d}/hqdefault.jpg"


def _cards(strip: RecommendStrip) -> list[_FeedCard]:
    out = []
    for i in range(strip._row.count()):
        w = strip._row.itemAt(i).widget()
        if isinstance(w, _FeedCard):
            out.append(w)
    return out


def _urls(strip: RecommendStrip) -> list[str]:
    return [c._dto.url for c in _cards(strip)]


def _vurl(i: int) -> str:
    return f"https://www.youtube.com/watch?v=rec{i:08d}"


def _left_release():
    return QMouseEvent(
        QMouseEvent.Type.MouseButtonRelease,
        QPointF(QPoint(5, 5)),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )


def _save_jpg(path, w: int, h: int, color: str) -> None:
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(QColor(color))
    assert img.save(str(path), "JPG")


# ── 픽스처 ──────────────────────────────────────────────────────────────
@pytest.fixture
def thumb_dir(tmp_path, monkeypatch):
    d = tmp_path / "thumbs"
    d.mkdir()
    import config.settings as settings

    monkeypatch.setattr(settings, "THUMBNAIL_DIR", d, raising=False)
    monkeypatch.setattr(feed_mod, "THUMBNAIL_DIR", d, raising=False)
    monkeypatch.setattr(lib_thumbs, "THUMBNAIL_DIR", d, raising=False)
    return d


@pytest.fixture(autouse=True)
def clean_feed_cache():
    feed_mod._feed_thumb_cache._cache.clear()
    yield
    feed_mod._feed_thumb_cache._cache.clear()


@pytest.fixture
def loader_calls(monkeypatch):
    """`start_thumb_loader`를 세기만 하는 대역 — 실제 스레드는 뜨지 않는다."""
    calls: list[tuple] = []

    def _fake(url, vid_id, on_loaded, prefix="feed", size=(640, 360)):
        calls.append((url, vid_id, prefix))
        return MagicMock()

    monkeypatch.setattr(feed_mod, "start_thumb_loader", _fake)
    return calls


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
def strip(qtbot, thumb_dir):
    s = RecommendStrip()
    qtbot.addWidget(s)
    return s


# ── D5-a ────────────────────────────────────────────────────────────────
class TestInPlaceUpdate:
    def test_B1_부분_뒤_최종이_오면_카드_객체를_재사용한다(self, strip, loader_calls):
        strip.set_items([_partial(i) for i in range(18)])
        cards0 = _cards(strip)   # 붙들어 둔다 — id 재활용 오판 방지
        ids0 = [id(c) for c in cards0]
        assert len(cards0) == 18

        strip.set_items([_final(i) for i in range(18)])

        cards1 = _cards(strip)
        assert [id(c) for c in cards1] == ids0, "카드가 다시 만들어졌다"
        assert strip.count() == 18
        assert not any(sip.isdeleted(c) for c in cards0)

    def test_B2_제자리_갱신_뒤_메타_제목_클릭이_최종_DTO_기준이다(
        self, qtbot, strip, loader_calls
    ):
        strip.set_items([_partial(i) for i in range(4)])
        cards0 = _cards(strip)
        ids0 = [id(c) for c in cards0]
        finals = [_final(i) for i in range(4)]

        strip.set_items(finals)

        cards = _cards(strip)
        assert [id(c) for c in cards] == ids0, "제자리 갱신이 아니다(카드 재사용 전제)"
        got: list = []
        strip.video_clicked.connect(got.append)
        for i, card in enumerate(cards):
            ref = _FeedCard(finals[i], thumb_size=RecommendStrip.THUMB_SIZE)
            qtbot.addWidget(ref)
            assert card._meta_lbl.text() == ref._meta_lbl.text()
            assert card._title_lbl.text() == finals[i].title
            card.mouseReleaseEvent(_left_release())
            assert got[-1] is finals[i]

    def test_B3_썸네일_로더를_영상_수만큼만_띄운다(self, strip, loader_calls):
        strip.set_items([_partial(i, thumb_url=_thumb_url(i)) for i in range(18)])
        strip.set_items([_final(i, thumb_url=_thumb_url(i)) for i in range(18)])

        assert len(loader_calls) == 18, f"로더 {len(loader_calls)}회"
        assert len({c[1] for c in loader_calls}) == 18

    def test_B4_제자리_갱신이_이미_있는_썸네일을_지우지_않는다(
        self, qtbot, strip, thumb_dir, loader_calls
    ):
        for i in range(3):
            _save_jpg(thumb_dir / f"feed_rec{i:08d}.jpg", 640, 360, RED)
        strip.set_items([_partial(i) for i in range(3)])
        cards = _cards(strip)
        qtbot.waitUntil(
            lambda: all(c._thumb_lbl._pixmap is not None for c in cards), timeout=5000
        )
        px0 = [c._thumb_lbl._pixmap for c in cards]

        strip.set_items([_final(i) for i in range(3)])

        cards1 = _cards(strip)
        assert [id(c) for c in cards1] == [id(c) for c in cards]
        for card, px in zip(cards1, px0):
            assert card._thumb_lbl._pixmap is px

    def test_B5_부분_결과_없이_최종만_와도_정상이다(self, strip, loader_calls):
        strip.set_items([_final(i, thumb_url=_thumb_url(i)) for i in range(18)])

        assert strip.count() == 18
        assert len(loader_calls) == 18
        assert _urls(strip) == [_vurl(i) for i in range(18)]

    def test_B6_최종_순서가_바뀌면_화면은_최종을_따르고_카드는_재사용한다(
        self, strip, loader_calls
    ):
        strip.set_items([_partial(i, thumb_url=_thumb_url(i)) for i in range(18)])
        cards0 = _cards(strip)
        ids0 = {id(c) for c in cards0}

        order = list(reversed(range(18)))
        strip.set_items([_final(i, thumb_url=_thumb_url(i)) for i in order])

        assert _urls(strip) == [_vurl(i) for i in order]
        assert {id(c) for c in _cards(strip)} == ids0
        assert len(loader_calls) == 18, f"추가 로더가 떴다: {len(loader_calls)}"

    def test_B7_최종이_줄면_빠진_카드만_사라진다(self, strip, loader_calls):
        strip.set_items([_partial(i, thumb_url=_thumb_url(i)) for i in range(18)])
        cards0 = _cards(strip)

        strip.set_items([_final(i, thumb_url=_thumb_url(i)) for i in range(10)])

        cards1 = _cards(strip)
        assert strip.count() == 10
        assert len(cards1) == 10
        assert [id(c) for c in cards1] == [id(c) for c in cards0[:10]]
        for gone in cards0[10:]:
            assert sip.isdeleted(gone) or gone.parent() is None, "유령 카드가 남았다"
        assert strip._empty_lbl.isHidden()
        assert len(loader_calls) == 18

    def test_B8_새_영상이_섞이면_새_것만_만든다(self, strip, loader_calls):
        strip.set_items([_partial(i, thumb_url=_thumb_url(i)) for i in range(18)])
        cards0 = _cards(strip)
        by_url0 = {c._dto.url: id(c) for c in cards0}

        order = list(range(13)) + list(range(100, 105))
        strip.set_items([_final(i, thumb_url=_thumb_url(i)) for i in order])

        cards1 = _cards(strip)
        assert strip.count() == 18
        assert _urls(strip) == [_vurl(i) for i in order]
        for c in cards1[:13]:
            assert id(c) == by_url0[c._dto.url], "기존 영상 카드가 재사용되지 않았다"
        assert len(loader_calls) == 23, f"로더 {len(loader_calls)}회(기대 23)"

    def test_B9_최종이_비면_비운다(self, strip, loader_calls):
        strip.set_items([_partial(i) for i in range(18)])

        strip.set_items([])

        assert strip.count() == 0
        assert _cards(strip) == []
        assert strip._empty_lbl.isVisibleTo(strip)

    def test_B10_같은_URL이_두_번_있어도_항목_수만큼_그린다(self, strip, loader_calls):
        strip.set_items([_partial(i) for i in range(3)])

        strip.set_items([_final(i) for i in (0, 1, 1, 2)])

        assert strip.count() == 4
        assert len(_cards(strip)) == 4
        assert _urls(strip) == [_vurl(i) for i in (0, 1, 1, 2)]

    def test_B11_라이브러리_포함_여부가_바뀌면_배지가_반영된다(self, strip, loader_calls):
        strip.set_items([_partial(0, in_library=False)])

        strip.set_items([_final(0, in_library=True)])

        card = _cards(strip)[0]
        badges = [
            lb for lb in card.findChildren(QLabel)
            if lb.text() == tr("✓ 라이브러리") and lb.isVisibleTo(card)
        ]
        assert len(badges) == 1

    def test_B12_다시_채우면_더_받기가_다시_가능해진다(self, strip, loader_calls):
        strip.set_items([_partial(i) for i in range(3)])
        strip.set_more_exhausted(True)

        strip.set_items([_final(i) for i in range(3)])

        assert strip._more_exhausted is False


# ── D5-b ────────────────────────────────────────────────────────────────
KEY_192 = "rec00000001@192x108"


def _feed_card(qtbot, dto, size=(192, 108)) -> _FeedCard:
    card = _FeedCard(dto, thumb_size=size)
    qtbot.addWidget(card)
    return card


class TestDiskHitCache:
    def test_B13_디스크_적중_썸네일이_표시_크기로_메모리_캐시에_들어간다(
        self, qtbot, thumb_dir, loader_calls
    ):
        _save_jpg(thumb_dir / "feed_rec00000001.jpg", 1280, 720, RED)
        card = _feed_card(qtbot, _final(1))

        qtbot.waitUntil(
            lambda: feed_mod._feed_thumb_cache.get(KEY_192) is not None, timeout=5000
        )
        px = feed_mod._feed_thumb_cache.get(KEY_192)
        assert px.width() == 192 and px.height() >= 108
        assert px.width() != 1280
        qtbot.waitUntil(lambda: card._thumb_lbl._pixmap is not None, timeout=5000)

    def test_B14_두_번째_생성은_재디코드_없이_메모리에서_즉시_그린다(
        self, qtbot, thumb_dir, loader_calls
    ):
        f = thumb_dir / "feed_rec00000001.jpg"
        _save_jpg(f, 1280, 720, RED)
        _feed_card(qtbot, _final(1))
        qtbot.waitUntil(
            lambda: feed_mod._feed_thumb_cache.get(KEY_192) is not None, timeout=5000
        )
        f.unlink()

        card2 = _feed_card(qtbot, _final(1, thumb_url=_thumb_url(1)))

        assert card2._thumb_lbl._pixmap is not None
        assert card2._thumb_lbl._pixmap is feed_mod._feed_thumb_cache.get(KEY_192)
        assert loader_calls == []

    def test_B15_캐시_키에_렌더_크기가_들어간다(self, qtbot, thumb_dir, loader_calls):
        _save_jpg(thumb_dir / "feed_rec00000001.jpg", 1280, 720, RED)
        _feed_card(qtbot, _final(1))
        qtbot.waitUntil(
            lambda: feed_mod._feed_thumb_cache.get(KEY_192) is not None, timeout=5000
        )

        card = _feed_card(qtbot, _final(1), size=None)
        qtbot.waitUntil(lambda: card._thumb_lbl._pixmap is not None, timeout=5000)

        assert card._thumb_lbl._pixmap.width() == 320
        qtbot.waitUntil(
            lambda: feed_mod._feed_thumb_cache.get("rec00000001@320x180") is not None,
            timeout=5000,
        )
        assert feed_mod._feed_thumb_cache.get(KEY_192) is not None

    def test_B16_깨진_feed_파일은_캐시를_오염시키지_않고_URL로_내려간다(
        self, qtbot, thumb_dir, loader_calls
    ):
        (thumb_dir / "feed_rec00000001.jpg").write_bytes(b"garbage")

        card = _feed_card(qtbot, _final(1, thumb_url=_thumb_url(1)))
        qtbot.wait(50)   # 대기가 아니라 큐에 남은 신호를 흘려보내는 용도

        assert feed_mod._feed_thumb_cache.get(KEY_192) is None
        assert len(loader_calls) == 1, f"URL 로더 {len(loader_calls)}회"
        assert not card.grab().isNull()

    def test_B17_캐시_put은_메인_스레드에서만_한다(
        self, qtbot, thumb_dir, loader_calls, put_spy
    ):
        _save_jpg(thumb_dir / "feed_rec00000001.jpg", 1280, 720, RED)
        _feed_card(qtbot, _final(1))

        qtbot.waitUntil(lambda: len(put_spy) >= 1, timeout=5000)
        qtbot.wait(50)

        assert all(is_main for is_main, _k in put_spy), f"워커에서 put: {put_spy}"
