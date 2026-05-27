"""ytdlp_adapter 의 _height_to_quality_label 단위 테스트."""
import pytest
from infrastructure.downloader.ytdlp_adapter import _height_to_quality_label


class TestHeightToQualityLabel:
    def test_4k(self):
        assert _height_to_quality_label(2160) == "UHD (4K)"

    def test_above_4k(self):
        assert _height_to_quality_label(4320) == "UHD (4K)"

    def test_qhd(self):
        assert _height_to_quality_label(1440) == "QHD (2K)"

    def test_fhd(self):
        assert _height_to_quality_label(1080) == "FHD"

    def test_hd(self):
        assert _height_to_quality_label(720) == "HD"

    def test_sd(self):
        assert _height_to_quality_label(480) == "SD"

    def test_below_sd(self):
        assert _height_to_quality_label(360) == "360p"

    def test_none_returns_empty(self):
        assert _height_to_quality_label(None) == ""
