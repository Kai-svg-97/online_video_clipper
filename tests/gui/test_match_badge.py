"""VideoDTO.match_fields 가 모델 롤로 전달되는지 검증한다."""
from __future__ import annotations

from uuid import uuid4

from application.library.dtos import VideoDTO
from gui.panels.library_panel import VideoListModel


def _dto(match_fields=()):
    return VideoDTO(
        id=uuid4(),
        url="https://youtu.be/x",
        title="제목",
        channel_name="채널",
        thumbnail_path="",
        duration_sec=60,
        favorite=False,
        watched=False,
        category_id=None,
        match_fields=match_fields,
    )


class TestMatchFieldsRole:
    def test_default_is_empty(self, qapp_instance):
        model = VideoListModel()
        model.set_videos([_dto()])
        idx = model.index(0, 0)
        assert model.data(idx, VideoListModel.MatchFieldsRole) == ()

    def test_role_returns_fields(self, qapp_instance):
        model = VideoListModel()
        model.set_videos([_dto(("title", "lyrics"))])
        idx = model.index(0, 0)
        assert model.data(idx, VideoListModel.MatchFieldsRole) == ("title", "lyrics")

    def test_role_id_does_not_collide(self):
        role_names = [k for k in vars(VideoListModel) if k.endswith("Role")]
        values = {getattr(VideoListModel, k) for k in role_names}
        assert len(values) == len(role_names), "롤 상수 값이 중복됐다"
