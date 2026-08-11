"""쿠키 파일 후보 자동 스캔.

사용자가 브라우저 확장(Get cookies.txt 등)으로 내보낸 Netscape 포맷 쿠키 파일이
어디 있는지 몰라 "쿠키 파일" 등록 기능을 한 번도 써보지 못했다는 신고에 따라,
흔한 저장 위치(다운로드·데스크톱)를 미리 스캔해 후보를 보여준다 — 파일 경로를
직접 찾아 입력할 필요를 없애기 위함이다.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from infrastructure.auth.youtube_auth import find_cookie_file_candidates

_NETSCAPE_YT = (
    "# Netscape HTTP Cookie File\n"
    ".youtube.com\tTRUE\t/\tTRUE\t0\tSID\tabc123\n"
)
_NETSCAPE_OTHER = (
    "# Netscape HTTP Cookie File\n"
    ".example.com\tTRUE\t/\tTRUE\t0\tSID\tabc123\n"
)


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    (tmp_path / "Downloads").mkdir()
    (tmp_path / "Desktop").mkdir()
    return tmp_path


class TestFindCookieFileCandidates:
    def test_유튜브_쿠키가_담긴_파일을_찾는다(self, home):
        target = home / "Downloads" / "youtube.com_cookies.txt"
        target.write_text(_NETSCAPE_YT, encoding="utf-8")

        result = find_cookie_file_candidates()

        assert target in result

    def test_유튜브_도메인이_없는_쿠키_파일은_제외한다(self, home):
        other = home / "Downloads" / "other_cookies.txt"
        other.write_text(_NETSCAPE_OTHER, encoding="utf-8")

        result = find_cookie_file_candidates()

        assert other not in result

    def test_netscape_헤더가_없는_txt는_제외한다(self, home):
        not_cookie = home / "Downloads" / "notes.txt"
        not_cookie.write_text("youtube.com 관련 메모\n어쩌구", encoding="utf-8")

        result = find_cookie_file_candidates()

        assert not_cookie not in result

    def test_데스크톱도_스캔한다(self, home):
        target = home / "Desktop" / "cookies.txt"
        target.write_text(_NETSCAPE_YT, encoding="utf-8")

        result = find_cookie_file_candidates()

        assert target in result

    def test_최근_수정된_파일이_먼저_나온다(self, home):
        import os
        import time

        older = home / "Downloads" / "old_cookies.txt"
        older.write_text(_NETSCAPE_YT, encoding="utf-8")
        newer = home / "Downloads" / "new_cookies.txt"
        newer.write_text(_NETSCAPE_YT, encoding="utf-8")

        past = time.time() - 3600
        os.utime(older, (past, past))

        result = find_cookie_file_candidates()

        assert result.index(newer) < result.index(older)

    def test_폴더가_없어도_예외없이_빈_목록을_반환한다(self, tmp_path, monkeypatch):
        empty_home = tmp_path / "no_such_dirs_home"
        empty_home.mkdir()
        monkeypatch.setattr(Path, "home", lambda: empty_home)

        result = find_cookie_file_candidates()

        assert result == []
