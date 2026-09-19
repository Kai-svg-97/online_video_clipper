"""업데이트 배지 판정 — 무엇을 보여 주고, 누르면 무엇이 일어나나.

이 판정이 위젯 안에 있으면 화면을 띄워야만 검증할 수 있고, `paintEvent` 안에서 난
예외는 **로그도 없이 프로세스를 죽인다**(0xC0000409). 그래서 여기서 경계를 전부
막아 두고 위젯은 결과를 그리기만 한다.

위험한 쪽은 "안 보이는 것"이 아니라 **거짓말하는 것**이다. 총량을 모르는데 백분율을
지어내거나, 재시도로 되돌아간 진행률을 그대로 그리면 사용자는 고장으로 읽는다.
"""

from __future__ import annotations

import pytest

from domain.updater.badge_state import (
    MAX_VERSION_CHARS,
    BadgeState,
    ClickAction,
    describe,
    progress_fraction,
    short_version,
)


class TestHidden:
    def test_새_버전이_없으면_숨긴다(self):
        view = describe(BadgeState.HIDDEN)
        assert view.visible is False
        assert view.action is ClickAction.NOTHING

    def test_버전_문자열이_비면_숨긴다(self):
        """확인은 됐는데 버전이 비어 오는 경우 — 빈 배지를 띄우면 안 된다."""
        view = describe(BadgeState.FOUND, new_version="")
        assert view.visible is False


class TestFound:
    def _view(self, **kw):
        return describe(
            BadgeState.FOUND,
            current_version="1.29.0",
            new_version="1.30.0",
            size_bytes=179 * 1024 * 1024,
            **kw,
        )

    def test_새_버전_번호를_보여_준다(self):
        assert "1.30.0" in self._view().label

    def test_툴팁에_현재_버전과_새_버전이_모두_있다(self):
        """어느 버전에서 어느 버전으로 가는지 모르면 누를 이유가 없다."""
        tip = self._view().tooltip
        assert "1.29.0" in tip and "1.30.0" in tip

    def test_툴팁에_받을_크기를_알려_준다(self):
        assert "179.0MB" in self._view().tooltip

    def test_크기를_모르면_크기를_말하지_않는다(self):
        view = describe(
            BadgeState.FOUND, current_version="1.29.0",
            new_version="1.30.0", size_bytes=0,
        )
        assert "MB" not in view.tooltip

    def test_누르면_다운로드가_시작된다(self):
        assert self._view().action is ClickAction.DOWNLOAD

    def test_아직_채워지지_않았다(self):
        assert self._view().fill == 0.0


class TestDownloading:
    def _view(self, downloaded, total):
        return describe(
            BadgeState.DOWNLOADING, new_version="1.30.0",
            downloaded=downloaded, total=total,
        )

    def test_진행률을_백분율로_보여_준다(self):
        view = self._view(50, 100)
        assert "50%" in view.label
        assert view.fill == pytest.approx(0.5)

    def test_받은_양과_전체를_툴팁에_적는다(self):
        tip = self._view(10 * 1024 * 1024, 100 * 1024 * 1024).tooltip
        assert "10.0MB" in tip and "100.0MB" in tip

    def test_총량을_모르면_백분율을_지어내지_않는다(self):
        """Content-Length 가 없는 응답이 있다 — 0으로 나누지도 않는다."""
        view = self._view(5 * 1024 * 1024, 0)
        assert "%" not in view.label
        assert view.indeterminate is True
        assert view.fill == 0.0

    def test_받은_양이_전체를_넘어도_넘치지_않는다(self):
        """이어받기 뒤 서버가 Range를 무시하면 받은 양이 전체보다 커 보인다."""
        view = self._view(150, 100)
        assert view.fill == 1.0
        assert "100%" in view.label

    def test_받는_중에는_눌러도_아무_일이_없다(self):
        """두 번 누르면 워커가 둘이 된다."""
        assert self._view(50, 100).action is ClickAction.NOTHING

    def test_시작_직후에도_안전하다(self):
        view = self._view(0, 0)
        assert view.visible is True
        assert view.fill == 0.0


class TestReady:
    def _view(self):
        return describe(BadgeState.READY, new_version="1.30.0")

    def test_설치하라고_말한다(self):
        assert "설치" in self._view().label

    def test_앱이_다시_시작된다고_알린다(self):
        """말없이 앱이 닫히면 사용자는 앱이 죽은 줄 안다."""
        assert "다시 시작" in self._view().tooltip

    def test_가득_차_있다(self):
        assert self._view().fill == 1.0

    def test_누르면_설치한다(self):
        assert self._view().action is ClickAction.INSTALL


class TestInstalling:
    def _view(self):
        return describe(BadgeState.INSTALLING, new_version="1.30.0")

    def test_설치_중임을_보여_준다(self):
        assert self._view().visible is True
        assert "설치" in self._view().label

    def test_누르는_것을_막는다(self):
        """이미 종료 절차가 시작됐다."""
        assert self._view().action is ClickAction.NOTHING


class TestFailed:
    def _view(self, error="Read timed out."):
        return describe(BadgeState.FAILED, new_version="1.30.0", error=error)

    def test_이유를_알려_준다(self):
        """왜 실패했는지 모르면 사용자가 할 수 있는 일이 없다."""
        assert "Read timed out." in self._view().tooltip

    def test_이유가_비어도_안전하다(self):
        assert self._view(error="").tooltip

    def test_다시_시도할_수_있다(self):
        assert self._view().action is ClickAction.DOWNLOAD

    def test_채움을_비운다(self):
        """실패했는데 가득 차 있으면 다 받은 것처럼 보인다."""
        assert self._view().fill == 0.0


class TestShortVersion:
    def test_짧으면_그대로(self):
        assert short_version("1.30.0") == "1.30.0"

    def test_길면_줄인다(self):
        """프리릴리스 태그가 붙으면 띠 안에서 폭이 무너진다."""
        got = short_version("1.30.0-rc1.build.20260919")
        assert len(got) == MAX_VERSION_CHARS

    def test_공백을_턴다(self):
        assert short_version("  1.30.0 ") == "1.30.0"

    def test_빈_값도_안전하다(self):
        assert short_version("") == ""


class TestProgressFraction:
    def test_정상_비율(self):
        assert progress_fraction(25, 100) == pytest.approx(0.25)

    def test_총량이_0이면_0(self):
        assert progress_fraction(50, 0) == 0.0

    def test_총량이_음수여도_0(self):
        assert progress_fraction(50, -1) == 0.0

    def test_받은_양이_음수여도_0(self):
        assert progress_fraction(-5, 100) == 0.0

    def test_1을_넘지_않는다(self):
        assert progress_fraction(200, 100) == 1.0
