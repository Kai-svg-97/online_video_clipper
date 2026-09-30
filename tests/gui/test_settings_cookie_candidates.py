"""설정 패널 — 감지된 쿠키 파일 후보 콤보.

쿠키 파일을 한 번도 등록해본 적이 없어 어디 있는지 모른다는 신고에 따라,
다운로드·데스크톱 폴더를 미리 스캔해 후보를 콤보박스로 보여주고 선택만 하면
경로란이 채워지도록 한다.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import infrastructure.auth.youtube_auth as youtube_auth
from infrastructure.auth.youtube_auth import YouTubeAuthService


def _panel():
    """조립 루트처럼 실제 인증 서비스를 넣는다 — 모듈 함수 패치가 그대로 먹는다."""
    from gui.panels.settings_panel import SettingsPanel

    return SettingsPanel(get_tags_fn=lambda: [], auth_service=YouTubeAuthService())


class TestCookieFileCandidates:
    def test_후보가_있으면_콤보에_채워진다(self, qtbot, monkeypatch):
        candidates = [Path("/home/u/Downloads/youtube.com_cookies.txt")]
        monkeypatch.setattr(
            youtube_auth, "find_cookie_file_candidates", lambda: candidates
        )

        panel = _panel()
        qtbot.addWidget(panel)

        combo = panel._feed_cookie_candidates_combo
        # 첫 항목은 안내용 placeholder, 두 번째부터 실제 후보.
        assert combo.count() == 2
        assert "youtube.com_cookies.txt" in combo.itemText(1)

    def test_후보가_없으면_안내_문구만_보여준다(self, qtbot, monkeypatch):
        monkeypatch.setattr(youtube_auth, "find_cookie_file_candidates", lambda: [])

        panel = _panel()
        qtbot.addWidget(panel)

        combo = panel._feed_cookie_candidates_combo
        assert combo.count() == 1
        assert combo.itemData(0) is None

    def test_후보_선택시_경로란이_채워진다(self, qtbot, monkeypatch):
        target = Path("/home/u/Desktop/cookies.txt")
        monkeypatch.setattr(
            youtube_auth, "find_cookie_file_candidates", lambda: [target]
        )

        panel = _panel()
        qtbot.addWidget(panel)

        combo = panel._feed_cookie_candidates_combo
        combo.setCurrentIndex(1)

        assert panel._feed_cookie_edit.text() == str(target)

    def test_인증_서비스가_없으면_후보를_찾지_않는다(self, qtbot):
        from gui.panels.settings_panel import SettingsPanel

        panel = SettingsPanel(get_tags_fn=lambda: [])
        qtbot.addWidget(panel)

        combo = panel._feed_cookie_candidates_combo
        assert combo.count() == 1
        assert combo.itemData(0) is None

    def test_다시_검색_버튼을_누르면_재스캔한다(self, qtbot, monkeypatch):
        scan = MagicMock(return_value=[])
        monkeypatch.setattr(youtube_auth, "find_cookie_file_candidates", scan)

        panel = _panel()
        qtbot.addWidget(panel)
        call_count_after_init = scan.call_count

        panel._reload_cookie_candidates()

        assert scan.call_count == call_count_after_init + 1
