"""버전 비교 유틸리티 유닛 테스트."""
import pytest

from application.updater.version_compare import is_newer, parse_semver


class TestParseSemver:
    def test_plain(self):
        assert parse_semver("1.2.3") == (1, 2, 3)

    def test_v_prefix(self):
        assert parse_semver("v1.2.3") == (1, 2, 3)

    def test_zeros(self):
        assert parse_semver("0.0.0") == (0, 0, 0)

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            parse_semver("1.2")

    def test_non_numeric_raises(self):
        with pytest.raises(ValueError):
            parse_semver("a.b.c")


class TestIsNewer:
    def test_patch_bump(self):
        assert is_newer("1.0.1", "1.0.0") is True

    def test_minor_bump(self):
        assert is_newer("1.1.0", "1.0.9") is True

    def test_major_bump(self):
        assert is_newer("2.0.0", "1.9.9") is True

    def test_same_version(self):
        assert is_newer("1.0.0", "1.0.0") is False

    def test_older_version(self):
        assert is_newer("0.9.9", "1.0.0") is False

    def test_v_prefix_in_latest(self):
        assert is_newer("v1.0.1", "1.0.0") is True

    def test_invalid_version_returns_false(self):
        assert is_newer("invalid", "1.0.0") is False
