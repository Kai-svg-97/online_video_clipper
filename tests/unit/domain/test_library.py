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


class TestAddVideoHandlerDescription:
    """Verify AddVideoHandler propagates description from yt-dlp metadata."""

    def _make_repo(self):
        """Return a minimal in-memory stub repository."""
        from unittest.mock import MagicMock
        from domain.library.repositories import IVideoRepository
        repo = MagicMock(spec=IVideoRepository)
        repo.get_by_url.return_value = None  # no existing video (new-video path)
        repo.get_or_create_tag.return_value = MagicMock(id=None)
        return repo

    def _make_ytdlp(self, description: str):
        from unittest.mock import MagicMock
        ytdlp = MagicMock()
        ytdlp.fetch_metadata.return_value = {
            "title": "Test Video",
            "description": description,
            "tags": [],
            "categories": [],
        }
        ytdlp.download_thumbnail.return_value = None
        return ytdlp

    def test_description_saved_from_metadata(self):
        from unittest.mock import MagicMock
        from application.library.commands import AddVideoCommand, AddVideoHandler
        from infrastructure.event_bus import EventBus

        repo = self._make_repo()
        ytdlp = self._make_ytdlp("This is the video description.")
        bus = MagicMock(spec=EventBus)
        handler = AddVideoHandler(repo, bus, ytdlp)

        handler.handle(AddVideoCommand(url="https://youtu.be/abc123", fetch_metadata=True))

        # repo.save() is called with the aggregate; inspect what was saved
        repo.save.assert_called_once()
        saved_agg = repo.save.call_args[0][0]
        assert saved_agg.video.description == "This is the video description."

    def test_empty_description_not_saved(self):
        from unittest.mock import MagicMock
        from application.library.commands import AddVideoCommand, AddVideoHandler
        from infrastructure.event_bus import EventBus

        repo = self._make_repo()
        ytdlp = self._make_ytdlp("")
        bus = MagicMock(spec=EventBus)
        handler = AddVideoHandler(repo, bus, ytdlp)

        handler.handle(AddVideoCommand(url="https://youtu.be/abc123", fetch_metadata=True))

        saved_agg = repo.save.call_args[0][0]
        # Empty description means update_metadata(description=...) was never called,
        # so the video description remains the default empty string
        assert saved_agg.video.description == ""
