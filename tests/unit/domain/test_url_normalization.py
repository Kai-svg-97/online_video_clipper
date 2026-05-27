"""URL normalization correctness tests."""
import pytest
from domain.library.value_objects import VideoUrl, normalize_video_url


class TestNormalizeVideoUrl:
    def test_canonical_youtube_unchanged(self):
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        assert normalize_video_url(url) == url

    def test_strips_list_param(self):
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=RDdQw4w9WgXcQ&start_radio=1"
        assert normalize_video_url(url) == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

    def test_strips_si_tracking_param(self):
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ&si=AbCdEfGhIjKlMnOp"
        assert normalize_video_url(url) == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

    def test_strips_pp_param(self):
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ&pp=ygUHdW5zYWZl"
        assert normalize_video_url(url) == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

    def test_youtu_be_short_link(self):
        assert normalize_video_url("https://youtu.be/dQw4w9WgXcQ") == \
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

    def test_youtu_be_with_si_param(self):
        assert normalize_video_url("https://youtu.be/dQw4w9WgXcQ?si=abc123") == \
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

    def test_without_www(self):
        assert normalize_video_url("https://youtube.com/watch?v=dQw4w9WgXcQ") == \
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

    def test_non_youtube_unchanged(self):
        url = "https://vimeo.com/123456789"
        assert normalize_video_url(url) == url

    def test_no_v_param_unchanged(self):
        url = "https://www.youtube.com/@SomeChannel"
        assert normalize_video_url(url) == url

    def test_idempotent(self):
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=abc&si=xyz"
        assert normalize_video_url(normalize_video_url(url)) == normalize_video_url(url)


class TestVideoUrlNormalizesOnConstruction:
    def test_youtu_be_stored_as_canonical(self):
        assert str(VideoUrl("https://youtu.be/dQw4w9WgXcQ")) == \
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

    def test_list_param_stripped(self):
        url = "https://www.youtube.com/watch?v=abc123&list=RDabc123&start_radio=1"
        assert str(VideoUrl(url)) == "https://www.youtube.com/watch?v=abc123"

    def test_si_param_stripped(self):
        url = "https://www.youtube.com/watch?v=abc123&si=tracking"
        assert str(VideoUrl(url)) == "https://www.youtube.com/watch?v=abc123"

    def test_different_forms_same_video_are_equal(self):
        v1 = VideoUrl("https://www.youtube.com/watch?v=abc123&list=XYZ")
        v2 = VideoUrl("https://youtu.be/abc123?si=tracking")
        v3 = VideoUrl("https://www.youtube.com/watch?v=abc123")
        assert v1 == v2 == v3
