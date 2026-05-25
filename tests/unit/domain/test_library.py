import pytest
from domain.library.aggregates import VideoAggregate
from domain.library.events import VideoAdded, VideoDeleted, VideoMarkedWatched, VideoUpdated
from domain.library.services import DuplicateDetectionService, DuplicateVideoError
from domain.library.value_objects import Duration, VideoUrl


class TestVideoUrl:
    def test_valid_http(self):
        url = VideoUrl("https://www.youtube.com/watch?v=abc")
        assert str(url) == "https://www.youtube.com/watch?v=abc"

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            VideoUrl("not-a-url")

    def test_equality(self):
        assert VideoUrl("https://a.com") == VideoUrl("https://a.com")
        assert VideoUrl("https://a.com") != VideoUrl("https://b.com")

    def test_hashable(self):
        s = {VideoUrl("https://a.com"), VideoUrl("https://a.com")}
        assert len(s) == 1


class TestDuration:
    def test_formatted_seconds_only(self):
        assert Duration(90).formatted() == "1:30"

    def test_formatted_with_hours(self):
        assert Duration(3661).formatted() == "1:01:01"

    def test_negative_raises(self):
        with pytest.raises(ValueError):
            Duration(-1)


class TestVideoAggregate:
    def _make(self, url="https://youtu.be/abc", title="Test Video"):
        return VideoAggregate.create(VideoUrl(url), title)

    def test_create_raises_video_added_event(self):
        agg = self._make()
        events = agg.pull_events()
        assert len(events) == 1
        assert isinstance(events[0], VideoAdded)
        assert events[0].title == "Test Video"

    def test_pull_events_clears_queue(self):
        agg = self._make()
        agg.pull_events()
        assert agg.pull_events() == []

    def test_mark_watched_is_idempotent(self):
        agg = self._make()
        agg.pull_events()
        agg.mark_watched()
        agg.mark_watched()
        events = agg.pull_events()
        assert len(events) == 1
        assert isinstance(events[0], VideoMarkedWatched)

    def test_update_metadata_raises_event(self):
        agg = self._make()
        agg.pull_events()
        agg.update_metadata(title="New Title", notes="some notes")
        events = agg.pull_events()
        assert len(events) == 1
        assert isinstance(events[0], VideoUpdated)
        assert "title" in events[0].changed_fields
        assert "notes" in events[0].changed_fields

    def test_update_metadata_no_event_when_unchanged(self):
        agg = self._make(title="Same")
        agg.pull_events()
        agg.update_metadata(title="Same")
        assert agg.pull_events() == []

    def test_delete_raises_event(self):
        agg = self._make()
        agg.pull_events()
        agg.delete()
        events = agg.pull_events()
        assert len(events) == 1
        assert isinstance(events[0], VideoDeleted)

    def test_update_metadata_description(self):
        agg = self._make()
        agg.pull_events()
        agg.update_metadata(description="hello world")
        assert agg.video.description == "hello world"
        events = agg.pull_events()
        assert any("description" in e.changed_fields for e in events)


class TestDuplicateDetectionService:
    def test_raises_on_duplicate(self):
        class FakeRepo:
            def exists_by_url(self, url):
                return True

        svc = DuplicateDetectionService(FakeRepo())
        with pytest.raises(DuplicateVideoError):
            svc.assert_unique("https://youtu.be/x")

    def test_passes_on_unique(self):
        class FakeRepo:
            def exists_by_url(self, url):
                return False

        svc = DuplicateDetectionService(FakeRepo())
        svc.assert_unique("https://youtu.be/x")  # no exception
