"""피드 오류 안내 — DPAPI 쿠키 실패를 **키**로 알아본다.

예전에는 어댑터가 만든 한국어 안내문에 "복호화"가 들어 있는지로 판정했다. 그 문장이
번역되면 판정이 조용히 어긋나 사용자는 해결 방법 대신 "오류: …"만 보게 된다.
"""

from __future__ import annotations

from types import SimpleNamespace

from domain.shared.ports import COOKIE_DECRYPT_FAILED
from gui.panels.library.constants import _VIEW_FEED
from gui.panels.library.mixins.feed import FeedViewMixin


class _Status:
    def __init__(self) -> None:
        self.text = ""
        self.shown = False

    def setText(self, text: str) -> None:
        self.text = text

    def show(self) -> None:
        self.shown = True


def _panel() -> SimpleNamespace:
    return SimpleNamespace(
        _view_stack=SimpleNamespace(currentIndex=lambda: _VIEW_FEED),
        _feed_status=_Status(),
        _channels_status=_Status(),
    )


def _shown(msg: str, language: str = "ko") -> str:
    from gui.text import active_language, set_language

    before = active_language()
    set_language(language)
    try:
        panel = _panel()
        FeedViewMixin._on_feed_error(panel, msg)
        assert panel._feed_status.shown
        return panel._feed_status.text
    finally:
        set_language(before)


def test_키로_온_DPAPI_오류는_해결_안내를_보인다():
    text = _shown(COOKIE_DECRYPT_FAILED)
    assert text.startswith("Chrome 쿠키를 복호화할 수 없습니다")


def test_영어_화면에서는_영어_안내다():
    text = _shown(COOKIE_DECRYPT_FAILED, "en")
    assert text.startswith("Can't decrypt Chrome cookies")


def test_yt_dlp_원문의_DPAPI도_알아본다():
    text = _shown("ERROR: Failed to decrypt with DPAPI")
    assert text.startswith("Chrome 쿠키를 복호화할 수 없습니다")


def test_그_밖의_오류는_원문을_보인다():
    assert _shown("HTTP Error 500") == "오류: HTTP Error 500"
