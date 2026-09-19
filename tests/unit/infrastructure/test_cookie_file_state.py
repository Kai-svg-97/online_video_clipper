"""등록된 쿠키 파일이 지금 쓸 수 있는 상태인가.

설정 화면이 경로만 적어 두면 **죽은 경로가 멀쩡한 것처럼 보인다**. 실제로 다른 PC에서
등록한 경로(다른 계정의 홈 디렉터리)가 그대로 남아 있었고, 요약이 "로그인된 브라우저를
찾지 못했습니다"로 실패하는데 설정 화면만 봐서는 원인을 알 수 없었다 — 경로가 또렷이
적혀 있어 오히려 정상으로 보였다.
"""

from __future__ import annotations

from infrastructure.auth.youtube_auth import (
    COOKIE_EMPTY,
    COOKIE_NOT_COOKIES,
    COOKIE_NOT_FOUND,
    COOKIE_OK,
    COOKIE_UNSET,
    cookie_file_state,
)

_NETSCAPE = (
    "# Netscape HTTP Cookie File\n"
    ".youtube.com\tTRUE\t/\tTRUE\t2000000000\tSID\tabc123\n"
)

# 다른 PC에서 등록된 채 남은 경로 — 이 계정에는 존재하지 않는다.
_OTHER_PC = "C:/Users/otheruser/AppData/Local/Programs/X/data/auth/youtube_cookies.txt"


class TestState:
    def test_등록한_적이_없으면_미설정(self):
        assert cookie_file_state(None) == COOKIE_UNSET
        assert cookie_file_state("") == COOKIE_UNSET

    def test_다른_PC_경로면_없음으로_본다(self):
        """이게 실제로 사용자를 막았던 경우다."""
        assert cookie_file_state(_OTHER_PC) == COOKIE_NOT_FOUND

    def test_폴더를_가리키면_없음으로_본다(self, tmp_path):
        assert cookie_file_state(tmp_path) == COOKIE_NOT_FOUND

    def test_비어_있으면_그렇게_말한다(self, tmp_path):
        f = tmp_path / "c.txt"
        f.write_text("", encoding="utf-8")
        assert cookie_file_state(f) == COOKIE_EMPTY

    def test_쿠키_파일이_아니면_그렇게_말한다(self, tmp_path):
        """엉뚱한 파일을 고르면 '등록했는데 안 된다'가 된다."""
        f = tmp_path / "c.txt"
        f.write_text("이건 그냥 메모입니다", encoding="utf-8")
        assert cookie_file_state(f) == COOKIE_NOT_COOKIES

    def test_제대로_된_파일이면_OK(self, tmp_path):
        f = tmp_path / "c.txt"
        f.write_text(_NETSCAPE, encoding="utf-8")
        assert cookie_file_state(f) == COOKIE_OK


class TestSettingsWording:
    """판정이 화면 문구로 이어지는지 — 경로만 보여주면 사용자가 원인을 못 찾는다."""

    def _text(self, qtbot, profile, cookiefile):
        from gui.panels.settings_panel import SettingsPanel

        return SettingsPanel._cookie_status_text(profile, cookiefile)

    def test_죽은_경로는_경고로_표시한다(self, qtbot):
        text = self._text(qtbot, None, _OTHER_PC)
        assert "⚠" in text
        assert "없습니다" in text
        assert _OTHER_PC in text          # 어느 경로인지도 알려 준다

    def test_멀쩡한_파일은_그냥_경로만(self, qtbot, tmp_path):
        f = tmp_path / "c.txt"
        f.write_text(_NETSCAPE, encoding="utf-8")
        text = self._text(qtbot, None, str(f))
        assert "⚠" not in text

    def test_아무것도_없으면_자동_탐색이라고_말한다(self, qtbot):
        assert "자동" in self._text(qtbot, None, None)

    def test_프로필만_있으면_프로필을_보여준다(self, qtbot):
        assert "프로필" in self._text(qtbot, "C:/x/profile", None)
