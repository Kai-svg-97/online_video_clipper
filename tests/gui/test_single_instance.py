"""단일 인스턴스 가드와 인스톨러 플래그를 검증한다.

업데이트 후 앱이 2개 실행되던 원인은 두 곳이 각각 앱을 띄웠기 때문이다:
1) installer.iss [Run] 항목에 skipifsilent 가 없어 무인 설치에서도 Inno가 실행
2) main.py 종료 tail 배치의 start "" "<exe>"
"""
from __future__ import annotations

from pathlib import Path

from gui.single_instance import SingleInstanceGuard


class TestSingleInstanceGuard:
    def test_first_acquire_succeeds(self, qapp_instance):
        guard = SingleInstanceGuard(key="ovc-test-first")
        try:
            assert guard.try_acquire() is True
        finally:
            guard.release()

    def test_second_acquire_fails(self, qapp_instance):
        """핵심 — 같은 키로 두 번째 획득은 실패해야 한다."""
        first = SingleInstanceGuard(key="ovc-test-second")
        second = SingleInstanceGuard(key="ovc-test-second")
        try:
            assert first.try_acquire() is True
            assert second.try_acquire() is False
        finally:
            second.release()
            first.release()

    def test_reacquire_after_release(self, qapp_instance):
        """정상 종료 후 다시 획득할 수 있어야 한다(잠금이 남지 않음)."""
        guard = SingleInstanceGuard(key="ovc-test-cycle")
        assert guard.try_acquire() is True
        guard.release()

        again = SingleInstanceGuard(key="ovc-test-cycle")
        try:
            assert again.try_acquire() is True
        finally:
            again.release()

    def test_different_keys_do_not_conflict(self, qapp_instance):
        a = SingleInstanceGuard(key="ovc-test-a")
        b = SingleInstanceGuard(key="ovc-test-b")
        try:
            assert a.try_acquire() is True
            assert b.try_acquire() is True
        finally:
            a.release()
            b.release()

    def test_default_key_is_user_scoped(self, qapp_instance):
        """다중 사용자 환경에서 서로 막지 않도록 키에 사용자명이 들어가야 한다."""
        import getpass

        guard = SingleInstanceGuard()
        assert "ovc" in guard.key
        assert getpass.getuser() in guard.key


class TestInstallerFlags:
    def test_run_entry_has_skipifsilent(self):
        """무인 설치에서 Inno가 앱을 실행하지 않도록 skipifsilent 가 있어야 한다."""
        iss = Path("packaging/installer.iss").read_text(encoding="utf-8", errors="replace")
        run_lines = [
            ln for ln in iss.splitlines()
            if ln.strip().startswith("Filename:") and "YouTubeContentManager.exe" in ln
        ]
        assert run_lines, "[Run] 항목을 찾지 못했다"
        for ln in run_lines:
            assert "skipifsilent" in ln, f"skipifsilent 누락: {ln.strip()}"

    def test_exit_tail_still_launches_app(self):
        """배치의 start 줄은 유지돼야 한다 — 양쪽을 모두 막으면 아무도 앱을 띄우지 않는다.

        installer.iss 에 skipifsilent 를 넣었으므로 재실행 주체는 이 배치 하나뿐이다.
        """
        main_src = Path("main.py").read_text(encoding="utf-8", errors="replace")
        bat_lines = [ln for ln in main_src.splitlines() if "_bat_content" in ln]
        assert any("start" in ln for ln in bat_lines), (
            "종료 tail 배치에서 앱을 재실행하는 start 줄이 사라졌다 — "
            "installer.iss 의 skipifsilent 와 함께라면 앱이 아예 실행되지 않는다"
        )
