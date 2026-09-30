"""`DisplayError` → `describe_error()` — 애플리케이션·인프라의 사용자용 예외가 화면 언어로 나온다.

예전에는 애플리케이션·인프라가 예외에 한국어 문장을 담았고 뷰모델이 `str(exc)`를 그대로
올려, 영어 화면에서도 한국어로 남았다. 여기서 지키는 것:

* `DisplayError`의 `str()`은 **키**(+파라미터)다 — 로그용이며 한국어 문장을 만들지 않는다.
* `describe_error()`는 `DisplayError`를 화면 언어의 문장으로 만들고, 그 밖의 예외는 예전처럼
  `str(exc)`다. **어떤 경우에도 예외를 내지 않는다**(오류를 알리다 두 번째 오류로 죽지 않는다).
* 기존 예외 계층이 유지된다(`except RuntimeError`가 여전히 잡는다).
"""

from __future__ import annotations

import re

import pytest

from domain.shared.messages import DisplayError, Message, error_message
from gui.text.messages import describe_error, render

_HANGUL = re.compile(r"[가-힣]")


@pytest.fixture
def english():
    from gui.text import active_language, set_language

    before = active_language()
    set_language("en")
    yield
    set_language(before)


class _Boom(Exception):
    def __str__(self) -> str:   # 일부 라이브러리 예외는 __str__에서 터진다
        raise ValueError("broken __str__")


class TestDisplayError:
    def test_str은_키다(self):
        assert str(DisplayError(Message.of("sync.schema_newer"))) == "sync.schema_newer"

    def test_파라미터가_있으면_키와_값을_보인다(self):
        text = str(DisplayError(Message.of("convert.ffmpeg_failed", code=3)))
        assert text == "convert.ffmpeg_failed (code=3)"
        assert not _HANGUL.search(text)

    def test_기존_예외_계층을_지킨다(self):
        from domain.sync.services import SyncSchemaError

        with pytest.raises(RuntimeError):
            raise SyncSchemaError(Message.of("sync.schema_newer"))

    def test_error_message는_일반_예외를_값으로_싣는다(self):
        assert error_message(OSError("disk full")) == Message.of("error.raw", reason="disk full")
        inner = Message.of("playlist.api_credentials_unavailable")
        assert error_message(DisplayError(inner)) is inner


class TestDescribeError:
    def test_한국어_문장은_예전과_같다(self):
        exc = DisplayError(Message.of("convert.ffmpeg_failed", code=1))
        assert describe_error(exc) == "ffmpeg 변환 실패 (코드 1)"

    def test_일반_예외는_str_그대로(self):
        assert describe_error(RuntimeError("HTTP Error 403")) == "HTTP Error 403"

    def test_None은_빈_문자열(self):
        assert describe_error(None) == ""

    def test_str이_터지는_예외에도_예외를_내지_않는다(self):
        assert describe_error(_Boom()) == "_Boom"

    def test_모르는_키도_예외를_내지_않는다(self):
        assert describe_error(DisplayError(Message.of("no.such.key"))) == "no.such.key"

    def test_안쪽_사유도_번역된다(self, english):
        exc = DisplayError(Message.of(
            "playlist.import_failed",
            ytdlp_error=error_message(RuntimeError("HTTP Error 403")),
            api_error=error_message(DisplayError(Message.of("playlist.api_not_connected"))),
        ))
        text = describe_error(exc)
        assert "HTTP Error 403" in text
        assert "YouTube API" in text
        assert not _HANGUL.search(text), text


class TestEnglishRender:
    """이번에 옮긴 문장이 영어 화면에서 영어로 나온다(카탈로그가 채워졌다)."""

    @pytest.mark.parametrize("msg", [
        Message.of("enrich.lyrics_exists"),
        Message.of("enrich.lyrics_lines", n=12),
        Message.of("enrich.summary_chars", n=340),
        Message.of("enrich.summary_no_button"),
        Message.of("transfer.lyrics_preview", lines=3, preview="la / la"),
        Message.of("album.released", date="2017-04-21"),
        Message.of("album.library_count", n=4),
        Message.of("convert.unknown_preset", preset="x"),
        Message.of("playlist.private_needs_auth"),
        Message.of("media.cookie_decrypt_failed"),
        Message.of("sync.snapshot_schema_newer", ids="['m9']"),
        Message.of("oauth.missing_field", field="client_id", path="a.json"),
        Message.of("update.download_interrupted", downloaded=1, total=2),
        Message.of("availability.not_youtube"),
    ], ids=lambda m: m.key)
    def test_영어로_나온다(self, english, msg):
        text = render(msg)
        assert text and not _HANGUL.search(text), text

    def test_가사_미리보기_한국어(self):
        msg = Message.of("transfer.lyrics_preview", lines=3, preview="가 / 나…")
        assert render(msg) == "3줄 · 가 / 나…"

    def test_문자열은_그대로(self):
        assert render("IU") == "IU"


class TestCookieDecryptSignal:
    """DPAPI 실패는 **키**로 알아본다 — 문장 비교("복호화" in msg)는 번역하면 어긋난다."""

    def test_어댑터가_키를_가진_DisplayError를_낸다(self):
        from domain.shared.ports import COOKIE_DECRYPT_FAILED
        from infrastructure.downloader.ytdlp_adapter import _dpapi_error

        exc = _dpapi_error()
        assert isinstance(exc, RuntimeError)
        assert exc.message.key == COOKIE_DECRYPT_FAILED
        # 피드 워커는 `str(exc)`를 넘긴다 — 그 문자열이 곧 키다.
        assert str(exc) == COOKIE_DECRYPT_FAILED
