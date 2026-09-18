"""받아 둔 전사 모델 판정 — **파일만 보고** 답해야 한다.

`WhisperTranscriber.is_model_ready()`는 모델을 실제로 **메모리에 올려** 판정한다
(faster-whisper 에 "받아졌나"만 묻는 API가 없다). 전사를 시작하기 직전이라면 그게
맞지만, 설정 화면처럼 목록만 보여주는 자리에서 부르면 열기만 해도 수백 MB가
붙잡힌다 — 목표 사양이 4GB RAM 인 앱에서 그냥 넘길 값이 아니다.

그래서 목록·용량·삭제 경로는 전부 파일 기반이다. 이 파일은 그 경계를 고정한다.
"""

from __future__ import annotations

import pytest

from infrastructure.subtitle import whisper_transcriber as wt


@pytest.fixture
def model_root(tmp_path, monkeypatch):
    root = tmp_path / "models" / "whisper"
    root.mkdir(parents=True)
    monkeypatch.setattr(wt, "model_root", lambda: root)
    return root


def _install(root, key: str, size: int = 2048) -> None:
    """HuggingFace 캐시 규약대로 모델 하나를 놓는다."""
    snap = root / f"models--Systran--faster-whisper-{key}" / "snapshots" / "abc123"
    snap.mkdir(parents=True)
    (snap / "model.bin").write_bytes(b"0" * size)
    (snap / "config.json").write_text("{}", encoding="utf-8")


class TestDetection:
    def test_없으면_받지_않은_것이다(self, model_root):
        assert wt.is_model_downloaded("base") is False

    def test_가중치가_있으면_받은_것이다(self, model_root):
        _install(model_root, "base")
        assert wt.is_model_downloaded("base") is True

    def test_폴더만_있고_가중치가_없으면_받은_것이_아니다(self, model_root):
        """내려받다 끊기면 폴더는 생기고 `model.bin`은 없다."""
        (model_root / "models--Systran--faster-whisper-base" / "blobs").mkdir(
            parents=True
        )
        assert wt.is_model_downloaded("base") is False

    def test_빈_가중치는_받은_것이_아니다(self, model_root):
        _install(model_root, "base", size=0)
        assert wt.is_model_downloaded("base") is False

    def test_모델마다_따로_센다(self, model_root):
        _install(model_root, "tiny")
        assert wt.is_model_downloaded("tiny") is True
        assert wt.is_model_downloaded("small") is False

    def test_알_수_없는_키는_기본_모델로_되돌린다(self, model_root):
        """설정 파일이 손으로 고쳐져도 죽지 않아야 한다(`resolve_model`)."""
        _install(model_root, "base")
        assert wt.is_model_downloaded("turbo-9000") is True


class TestNoModelLoad:
    def test_목록을_읽을_때_모델을_올리지_않는다(self, model_root, monkeypatch):
        """`_load`가 불리면 수백 MB가 붙잡힌다 — 불리면 테스트가 깨지게 둔다."""
        _install(model_root, "base", size=2 * 1024**2)
        t = wt.WhisperTranscriber()
        monkeypatch.setattr(
            t, "_load", lambda *a, **k: pytest.fail("모델을 메모리에 올렸다")
        )

        assert t.installed_models() == {"base"}
        assert t.model_disk_mb("base") > 0


class TestDiskUsage:
    def test_받지_않았으면_0(self, model_root):
        assert wt.model_disk_bytes("base") == 0

    def test_실제_파일_크기를_잰다(self, model_root):
        _install(model_root, "base", size=3 * 1024**2)
        assert wt.model_disk_bytes("base") >= 3 * 1024**2


class TestDelete:
    def test_지우면_폴더가_사라진다(self, model_root):
        _install(model_root, "base")
        t = wt.WhisperTranscriber()

        assert t.delete_model("base") is True
        assert wt.is_model_downloaded("base") is False

    def test_없는_것을_지우면_False(self, model_root):
        assert wt.WhisperTranscriber().delete_model("base") is False

    def test_올려_둔_모델을_지우면_참조도_놓는다(self, model_root):
        """지운 파일을 가리키는 모델을 붙들고 있으면 다음 전사가 이상해진다."""
        _install(model_root, "base")
        t = wt.WhisperTranscriber()
        t._model = object()
        t._loaded_key = "base"

        t.delete_model("base")

        assert t._model is None
        assert t._loaded_key == ""
