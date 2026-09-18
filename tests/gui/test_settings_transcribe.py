"""설정 화면의 음성 인식 모델 선택.

고르는 값이 **디스크·시간과 직결**된다(tiny 75MB ↔ small 484MB, 속도는 6배 차이).
그래서 화면이 지켜야 할 것은 세 가지다.

1. 지금 설정된 값이 선택돼 보여야 한다 — 뭘 쓰는지 모르면 고칠 수도 없다.
2. 고르면 곧바로 저장돼야 한다(이 화면에는 '적용' 버튼이 없다).
3. **받아 두지 않은 모델은 지울 수 없다** — 눌러도 아무 일 없는 버튼을 켜 두지 않는다.
"""

from __future__ import annotations

from PyQt6.QtCore import QObject, pyqtSignal

from application.library.subtitle_queries import SubtitleCoverageDTO
from domain.library.transcribe import MODELS
from gui.panels.settings_panel import SettingsPanel


class _VM(QObject):
    bulk_progress = pyqtSignal(int, int, str)
    bulk_finished = pyqtSignal(object)

    def __init__(self, current="base", installed=()):
        super().__init__()
        self.is_bulk_running = False
        self.transcribe_model_key = current
        self._installed = set(installed)
        self.saved: list[str] = []
        self.deleted: list[str] = []

    def coverage(self):
        return SubtitleCoverageDTO(indexed_videos=1, total_videos=2)

    def set_transcribe_model(self, key):
        self.saved.append(key)
        self.transcribe_model_key = key

    def installed_models(self):
        return set(self._installed)

    def model_disk_mb(self, key):
        return 140 if key in self._installed else 0

    def delete_model(self, key):
        self.deleted.append(key)
        self._installed.discard(key)
        return True


def _panel(qtbot, **kwargs):
    vm = _VM(**kwargs)
    p = SettingsPanel(subtitle_vm=vm)
    qtbot.addWidget(p)
    p.vm = vm            # type: ignore[attr-defined]
    return p


class TestModelChoice:
    def test_모든_모델을_고를_수_있다(self, qtbot):
        panel = _panel(qtbot)
        keys = [
            panel._asr_model_combo.itemData(i)
            for i in range(panel._asr_model_combo.count())
        ]
        assert keys == [m.key for m in MODELS]

    def test_디스크_크기를_같이_적는다(self, qtbot):
        """고르는 값이 곧 용량이라, 고르기 전에 보여야 한다."""
        panel = _panel(qtbot)
        assert "MB" in panel._asr_model_combo.currentText()

    def test_지금_설정된_값이_선택돼_있다(self, qtbot):
        panel = _panel(qtbot, current="small")
        assert panel._asr_model_combo.currentData() == "small"

    def test_알_수_없는_값이면_첫_항목으로_되돌린다(self, qtbot):
        """설정 파일을 손으로 고쳐도 화면이 죽지 않아야 한다."""
        panel = _panel(qtbot, current="turbo-9000")
        assert panel._asr_model_combo.currentIndex() == 0

    def test_고르면_바로_저장한다(self, qtbot):
        """'적용' 버튼이 없는 화면이다 — 저장을 미루면 영영 저장되지 않는다."""
        panel = _panel(qtbot)
        panel._asr_model_combo.setCurrentIndex(
            panel._asr_model_combo.findData("small")
        )
        assert panel.vm.saved == ["small"]

    def test_고른_모델의_설명을_보여준다(self, qtbot):
        panel = _panel(qtbot)
        panel._asr_model_combo.setCurrentIndex(
            panel._asr_model_combo.findData("tiny")
        )
        assert panel._asr_model_note.text()


class TestInstalledModels:
    def test_받아_두지_않았으면_지울_수_없다(self, qtbot):
        panel = _panel(qtbot, current="base", installed=())
        assert panel._asr_delete_btn.isEnabled() is False

    def test_처음_쓸_때_받는다고_알린다(self, qtbot):
        panel = _panel(qtbot, current="base", installed=())
        assert "내려받습니다" in panel._asr_installed_lbl.text()

    def test_받아_뒀으면_지울_수_있다(self, qtbot):
        panel = _panel(qtbot, current="base", installed=("base",))
        assert panel._asr_delete_btn.isEnabled() is True

    def test_지우면_버튼이_꺼진다(self, qtbot):
        panel = _panel(qtbot, current="base", installed=("base",))
        panel._asr_delete_btn.click()
        assert panel.vm.deleted == ["base"]
        assert panel._asr_delete_btn.isEnabled() is False

    def test_모델을_바꾸면_지울_수_있는지도_다시_판정한다(self, qtbot):
        """base 는 받아 뒀지만 small 은 아니다 — 버튼이 따라가야 한다."""
        panel = _panel(qtbot, current="base", installed=("base",))
        panel._asr_model_combo.setCurrentIndex(
            panel._asr_model_combo.findData("small")
        )
        assert panel._asr_delete_btn.isEnabled() is False


class TestWithoutViewModel:
    def test_뷰모델이_없으면_섹션_자체가_없다(self, qtbot):
        """다른 진입점에서 연 설정 화면도 열려야 한다."""
        p = SettingsPanel()
        qtbot.addWidget(p)
        assert not hasattr(p, "_asr_model_combo")
