"""썸네일 디코드 — `setScaledSize`로 읽을 때 크기·예외 계약(성능 배치 7, A7).

원본을 전부 디코드한 뒤 `scaled()`로 줄이면 장당 3.4ms, 디코드 시점에 줄이면 0.9ms다.
빠르게 하다 비율이 틀어지면 안 되므로 **결과 크기가 지금 `scaled(KeepAspectRatio)`와
같은지**를 고정한다. 화질은 육안 확인 대상이라 시험하지 않는다.
"""

from __future__ import annotations

import pytest
from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QColor, QImage

from gui.panels.library import thumbnails


def _save(tmp_path, name: str, w: int, h: int) -> str:
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(QColor("#336699"))
    p = tmp_path / name
    assert img.save(str(p), "JPG")
    return str(p)


def _reference_size(path: str, w: int, h: int) -> QSize:
    """지금 구현(전체 디코드 후 `scaled`)이 내는 크기."""
    return (
        QImage(path)
        .scaled(
            w, h,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        .size()
    )


@pytest.fixture
def decode():
    fn = getattr(thumbnails, "_decode_scaled", None)
    assert fn is not None, "gui.panels.library.thumbnails._decode_scaled가 없다(기능 부재)"
    return fn


class TestDecodeScaled:
    def test_16_9_원본은_목표_크기가_된다(self, qapp_instance, tmp_path, decode):
        p = _save(tmp_path, "wide.jpg", 1280, 720)

        img = decode(p, 160, 90)

        assert img is not None
        assert img.size() == QSize(160, 90)

    def test_4_3_원본은_비율을_유지한다(self, qapp_instance, tmp_path, decode):
        p = _save(tmp_path, "std.jpg", 640, 480)

        img = decode(p, 160, 90)

        assert img.size() == QSize(120, 90)
        assert img.size() == _reference_size(p, 160, 90)

    def test_세로_원본도_현행과_같은_크기다(self, qapp_instance, tmp_path, decode):
        p = _save(tmp_path, "tall.jpg", 90, 160)

        img = decode(p, 160, 90)

        assert img.size() == _reference_size(p, 160, 90)

    def test_목표보다_작은_원본은_현행과_같이_다룬다(self, qapp_instance, tmp_path, decode):
        p = _save(tmp_path, "small.jpg", 80, 45)

        img = decode(p, 160, 90)

        assert img.size() == _reference_size(p, 160, 90)

    def test_손상된_파일과_없는_파일은_None이고_예외가_없다(
        self, qapp_instance, tmp_path, decode
    ):
        bad = tmp_path / "bad.jpg"
        bad.write_bytes(b"this is not a jpeg at all")

        assert decode(str(bad), 160, 90) is None
        assert decode(str(tmp_path / "missing.jpg"), 160, 90) is None


class TestLoaderRun:
    def test_유효한_한_장만_배치로_오고_예외가_없다(
        self, qapp_instance, tmp_path, monkeypatch
    ):
        good = _save(tmp_path, "good.jpg", 1280, 720)
        bad = tmp_path / "bad.jpg"
        bad.write_bytes(b"garbage")
        monkeypatch.setattr(thumbnails, "THUMBNAIL_DIR", str(tmp_path))
        thumbnails._thumb_cache._cache.clear()

        loader = thumbnails._ThumbBgLoader(
            [(good, 160, 90), (str(bad), 160, 90), (str(tmp_path / "none.jpg"), 160, 90)]
        )
        received: list = []
        loader.batch_ready.connect(received.extend)

        loader.run()   # 동기 직접 호출 — 스레드를 띄우지 않는다

        assert len(received) == 1
        path, w, h, img = received[0]
        assert path == good
        assert (w, h) == (160, 90)
        assert img.size() == QSize(160, 90)
