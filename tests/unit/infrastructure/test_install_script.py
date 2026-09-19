"""설치 배치 스크립트 — 내용만 검증한다(실제로 설치하지는 않는다).

이 경로는 **깨져도 사용자가 알 수 없다.** 배치는 앱이 죽은 뒤에 도는 별도
프로세스라 로그도 화면도 없고, 잘못되면 "업데이트를 눌렀는데 버전이 그대로"로만
나타난다. 게다가 업데이트가 막히면 사용자는 그 버전에 갇힌다 — 고칠 방법이 앱
안에만 있기 때문이다.

여기서 지키는 것들은 전부 **실제로 밟은 함정**이다:
  · 시스템 도구를 절대 경로로 부르지 않으면 Git for Windows 의 GNU find 가 잡혀
    PID 대기가 통째로 건너뛰어진다
  · `echo %ERRORLEVEL%> "파일"` 은 `2>` 가 리다이렉션으로 해석돼 기록이 비어 버린다
  · 배치에 한글을 넣으면 mbcs 기록이 한국어가 아닌 코드페이지에서 실패한다
"""

from __future__ import annotations

from infrastructure.updater.install_script import (
    INSTALLER_ARGS,
    build_update_batch,
)

_INSTALLER = r"C:\Users\kai\AppData\Local\Temp\ovc_update_1\setup.exe"
_EXE = r"C:\Program Files\YouTubeContentManager\YouTubeContentManager.exe"
_FAIL = r"C:\Users\kai\AppData\Local\Temp\ovc_update_failed.txt"


def _batch(installer=_INSTALLER, exe=_EXE, pid=4242, fail=_FAIL) -> str:
    return build_update_batch(installer, exe, pid, fail)


class TestWaitsForApp:
    def test_우리_pid를_기다린다(self):
        """앱이 살아 있는 동안 설치하면 파일이 잠겨 실패한다."""
        assert "4242" in _batch()

    def test_고정_대기를_쓰지_않는다(self):
        """`timeout /t 5`는 느린 PC에서 모자라고 빠른 PC에서는 낭비였다.

        게다가 콘솔 없는 프로세스에서는 timeout 자체가 즉시 실패해
        **한 번도 기다린 적이 없었다**(실측).
        """
        assert "timeout" not in _batch().lower()

    def test_대기_루프에_상한이_있다(self):
        """앱이 끝내 안 죽어도 영원히 도는 배치를 남기지 않는다."""
        body = _batch()
        assert "GEQ" in body
        assert ":wait" in body and "goto wait" in body

    def test_시스템_도구를_절대_경로로_부른다(self):
        """그냥 `find`라고 쓰면 Git for Windows 의 GNU find 가 먼저 잡히고,
        그것이 실패하면 `|| goto ready`가 발동해 대기가 통째로 사라진다."""
        body = _batch()
        assert "%SystemRoot%\\System32\\tasklist.exe" in body
        assert "%SystemRoot%\\System32\\findstr.exe" in body

    def test_이름이_겹치는_find를_쓰지_않는다(self):
        body = _batch()
        assert "| find " not in body


class TestInstallerInvocation:
    def test_인스톨러_경로를_따옴표로_감싼다(self):
        """`Program Files` 처럼 공백이 든 경로가 흔하다."""
        assert f'"{_INSTALLER}"' in _batch()

    def test_무인_설치_인자를_넘긴다(self):
        assert INSTALLER_ARGS in _batch()

    def test_진행_막대를_보여_준다(self):
        """`/VERYSILENT`면 앱이 닫힌 뒤 화면에 아무것도 없어 앱이 죽은 줄 안다."""
        assert "/SILENT" in INSTALLER_ARGS
        assert "/VERYSILENT" not in INSTALLER_ARGS

    def test_인스톨러가_스스로_재시작하지_않는다(self):
        """재실행 주체가 둘이면 앱이 두 개 뜬다(과거 실제 회귀)."""
        assert "/NORESTART" in INSTALLER_ARGS

    def test_앱을_닫는_2차_방어가_있다(self):
        """PID 대기가 상한에 걸린 경우를 위한 안전망."""
        assert "/CLOSEAPPLICATIONS" in INSTALLER_ARGS


class TestFailureRecord:
    def test_실패하면_종료_코드를_남긴다(self):
        """남기지 않으면 아무도 모른다 — 배치는 조용히 죽는다."""
        body = _batch()
        assert "errorlevel 1" in body
        assert _FAIL in body

    def test_리다이렉션이_echo_앞에_온다(self):
        """`echo %ERRORLEVEL%> "파일"`로 쓰면 코드가 한 자리 숫자일 때 `2>`가
        stderr 리다이렉션으로 해석돼 파일이 비어 버린다."""
        body = _batch()
        assert f'>"{_FAIL}" echo %ERRORLEVEL%' in body
        assert 'echo %ERRORLEVEL%>' not in body


class TestRelaunch:
    def test_새_버전을_다시_띄운다(self):
        assert f'start "" "{_EXE}"' in _batch()

    def test_exe를_모르면_재실행하지_않는다(self):
        """개발 실행(frozen 아님)은 exe 로 되살릴 수 없다."""
        assert "start " not in _batch(exe="")

    def test_배치가_스스로를_지운다(self):
        assert 'del "%~f0"' in _batch()


class TestEncoding:
    def test_우리가_적는_것은_전부_ASCII다(self):
        """배치에 한글 주석을 넣으면 한국어가 아닌 코드페이지(영문 Windows의
        cp1252 등)에서 **기록 자체가 실패해** 업데이트가 통째로 멈춘다.
        설명은 파이썬 쪽 독스트링에 두고 배치에는 남기지 않는다."""
        _batch().encode("ascii")   # 예외가 나면 실패

    def test_한글_경로를_망가뜨리지_않는다(self):
        """사용자 이름이 한글이면 임시 경로에 한글이 섞인다 — 한국어 사용자에게
        흔하다. 경로는 그대로 실어 보내고, 파일은 시스템 ANSI 코드페이지로 기록하므로
        그 PC 에서는 표현된다(ascii 로 기록하면 업데이트가 통째로 막힌다)."""
        installer = "C:\\사용자\\설치.exe"
        body = build_update_batch(installer, "", 1, "x")
        assert installer in body

    def test_줄바꿈이_CRLF다(self):
        body = _batch()
        assert "\r\n" in body
        assert "\r\r\n" not in body
