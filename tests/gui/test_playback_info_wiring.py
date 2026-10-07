"""상세 화면 → 플레이어로 `video_info`가 내려가는 배선(배치 6).

`gui/media_services.py` 머리말대로 낱개 인자를 세 단계로 흘리면 한 곳을 잊을 때 그 기능만
조용히 죽는다 — 캐시가 있는데 플레이어가 못 받으면 load+▶가 extract를 두 번 한다.
"""
from __future__ import annotations

import dataclasses

from gui.media_services import MediaServices
from gui.panels.video_detail_panel import VideoDetailWidget
from gui.widgets.video_player import InlinePlayer


class _Info:
    def info(self, url, *, client=None, fresh=False):
        return {}


def test_MediaServices는_video_info_필드를_가진다():
    names = {f.name for f in dataclasses.fields(MediaServices)}
    assert "video_info" in names
    assert MediaServices().video_info is None, "비어 있으면 예전처럼 직접 추출한다"


def test_상세_화면이_플레이어에_video_info를_넘긴다(qapp_instance, qtbot, monkeypatch):
    created: list = []

    class _Spy(InlinePlayer):
        def __init__(self, *args, **kwargs):
            created.append(kwargs)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr("gui.panels.video_detail_panel.InlinePlayer", _Spy)
    info = _Info()

    widget = VideoDetailWidget(media=MediaServices(video_info=info))
    qtbot.addWidget(widget)

    assert len(created) == 1
    assert created[0].get("info_source") is info
