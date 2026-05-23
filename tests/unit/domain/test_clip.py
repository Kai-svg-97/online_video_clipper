import pytest
from uuid import uuid4
from domain.clip.aggregates import ClipAggregate
from domain.clip.events import ClipCreated, ClipDeleted
from domain.clip.value_objects import TimeRange


class TestTimeRange:
    def test_valid(self):
        tr = TimeRange(10.0, 30.0)
        assert tr.duration_sec == pytest.approx(20.0)

    def test_negative_start_raises(self):
        with pytest.raises(ValueError):
            TimeRange(-1.0, 10.0)

    def test_end_before_start_raises(self):
        with pytest.raises(ValueError):
            TimeRange(30.0, 10.0)

    def test_end_equal_start_raises(self):
        with pytest.raises(ValueError):
            TimeRange(10.0, 10.0)

    def test_equality(self):
        assert TimeRange(0, 10) == TimeRange(0, 10)
        assert TimeRange(0, 10) != TimeRange(0, 11)


class TestClipAggregate:
    def test_create_raises_event(self):
        vid_id = uuid4()
        agg = ClipAggregate.create(vid_id, "Intro", TimeRange(0, 30))
        events = agg.pull_events()
        assert len(events) == 1
        assert isinstance(events[0], ClipCreated)
        assert events[0].source_video_id == vid_id

    def test_delete_raises_event(self):
        agg = ClipAggregate.create(uuid4(), "Clip", TimeRange(5, 15))
        agg.pull_events()
        agg.delete()
        events = agg.pull_events()
        assert any(isinstance(e, ClipDeleted) for e in events)
