"""변환 유스케이스 — 출력 경로 규칙과 방어.

가장 중요한 계약은 **원본을 덮어쓰지 않는 것**이다. 변환은 되돌릴 수 없어(원본 화질은
복구되지 않는다), 같은 경로로 떨어지는 순간 원본이 사라진다.
"""

from __future__ import annotations

import pytest

from application.clip.convert import ConvertMediaCommand, ConvertMediaHandler, list_presets


class _Converter:
    def __init__(self):
        self.calls: list[tuple] = []

    def convert(self, source, preset, output, on_progress=None):
        self.calls.append((source, preset.key, output))
        if on_progress:
            on_progress(50)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"converted")
        return output


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "영상.mp4"
    path.write_bytes(b"original")
    return path


class TestOutput:
    def test_원본_옆에_새_파일로_떨어진다(self, source):
        conv = _Converter()
        out = ConvertMediaHandler(conv).handle(
            ConvertMediaCommand(str(source), "mp4-720p")
        )
        assert out.parent == source.parent
        assert out.name == "영상 [mp4-720p].mp4"
        assert source.read_bytes() == b"original"     # 원본 그대로

    def test_출력_폴더를_지정할_수_있다(self, source, tmp_path):
        out_dir = tmp_path / "변환본"
        out = ConvertMediaHandler(_Converter()).handle(
            ConvertMediaCommand(str(source), "mp3", output_dir=str(out_dir))
        )
        assert out.parent == out_dir
        assert out.suffix == ".mp3"

    def test_같은_이름이_될_상황에도_원본을_덮지_않는다(self, tmp_path):
        """프리셋 이름이 이미 붙은 파일을 다시 변환하는 경우 실제로 일어난다."""
        source = tmp_path / "영상 [mp4-720p].mp4"
        source.write_bytes(b"original")
        out = ConvertMediaHandler(_Converter()).handle(
            ConvertMediaCommand(str(source), "mp4-720p")
        )
        assert out != source
        assert source.read_bytes() == b"original"


class TestGuards:
    def test_모르는_프리셋은_거부한다(self, source):
        with pytest.raises(ValueError, match="프리셋"):
            ConvertMediaHandler(_Converter()).handle(
                ConvertMediaCommand(str(source), "없는키")
            )

    def test_원본이_없으면_거부한다(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            ConvertMediaHandler(_Converter()).handle(
                ConvertMediaCommand(str(tmp_path / "없음.mp4"), "mp3")
            )


class TestProgress:
    def test_진행률이_전달된다(self, source):
        seen: list[int] = []
        ConvertMediaHandler(_Converter()).handle(
            ConvertMediaCommand(str(source), "mp3"), on_progress=seen.append
        )
        assert seen == [50]


class TestCatalogExposure:
    def test_화면이_쓸_목록을_돌려준다(self):
        presets = list_presets()
        assert presets and all(p.key and p.name for p in presets)
