"""상세 설명서 진입점 — F1과 설정 단추가 같은 곳을 가리키는가.

번들된 HTML을 우선하고 없을 때만 온라인 문서로 가는 규칙이 핵심이다. 설치해 쓰는
앱이라 **지금 깔린 버전의 설명서**여야 하고, 인터넷이 없어도 열려야 한다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from gui import help as help_mod


class TestManualTarget:
    def test_번들된_html이_있으면_그것을_연다(self, tmp_path, monkeypatch):
        local = tmp_path / "docs" / "manual" / "index.html"
        local.parent.mkdir(parents=True)
        local.write_text("<html></html>", encoding="utf-8")
        monkeypatch.setattr(help_mod, "get_resource_path", lambda rel: tmp_path / rel)
        assert help_mod.manual_target() == local.as_uri()

    def test_파일_uri로_돌려준다(self, tmp_path, monkeypatch):
        """경로를 그대로 넘기면 Windows에서 드라이브 문자가 스킴으로 해석된다."""
        local = tmp_path / "docs" / "manual" / "index.html"
        local.parent.mkdir(parents=True)
        local.write_text("x", encoding="utf-8")
        monkeypatch.setattr(help_mod, "get_resource_path", lambda rel: tmp_path / rel)
        assert help_mod.manual_target().startswith("file:///")

    def test_번들에_없으면_온라인_문서로(self, tmp_path, monkeypatch):
        monkeypatch.setattr(help_mod, "get_resource_path", lambda rel: tmp_path / rel)
        assert help_mod.manual_target() == help_mod.MANUAL_URL

    def test_경로_확인이_터져도_열_곳을_돌려준다(self, monkeypatch):
        """설명서를 못 여는 것보다 온라인으로라도 보내는 편이 낫다."""
        def boom(_rel):
            raise OSError("no")

        monkeypatch.setattr(help_mod, "get_resource_path", boom)
        assert help_mod.manual_target() == help_mod.MANUAL_URL

    def test_저장소에_실제로_만들어져_있다(self):
        """빌드가 번들할 파일이다 — 없으면 설치본이 온라인 문서로 새어 나간다."""
        built = Path(__file__).resolve().parents[2] / "docs" / "manual" / "index.html"
        assert built.exists(), "python scripts/build_manual.py 를 돌려야 한다"


class TestEntryPoints:
    """F1과 설정 단추가 같은 함수를 부르는지 — 한쪽만 고쳐지는 것을 막는다."""

    def test_설정_패널에_설명서_단추가_있다(self, qapp_instance, qtbot):
        from gui.panels.settings_panel import SettingsPanel

        from PyQt6.QtWidgets import QPushButton

        panel = SettingsPanel()
        qtbot.addWidget(panel)
        labels = [b.text() for b in panel.findChildren(QPushButton)]
        assert any("상세 설명서" in t for t in labels), labels

    def test_설정_패널이_같은_진입점을_쓴다(self, qapp_instance, qtbot, monkeypatch):
        from gui.panels.settings_panel import SettingsPanel

        panel = SettingsPanel()
        qtbot.addWidget(panel)
        called = []
        monkeypatch.setattr(help_mod, "open_manual", lambda: called.append(True) or True)
        panel._open_manual()
        assert called == [True]


@pytest.mark.parametrize("attr", ["MANUAL_URL"])
def test_온라인_문서_주소가_저장소를_가리킨다(attr):
    assert getattr(help_mod, attr).startswith("https://github.com/")
    assert "docs/manual.md" in getattr(help_mod, attr)
