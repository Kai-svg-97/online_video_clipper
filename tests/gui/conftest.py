"""GUI 스모크 테스트용 공통 픽스처."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from PyQt6.QtWidgets import QApplication


def _handler(return_value=None):
    """handle() 메서드가 return_value를 반환하는 목 핸들러 생성."""
    m = MagicMock()
    m.handle.return_value = return_value if return_value is not None else []
    return m


@pytest.fixture(scope="session")
def qapp_instance():
    """세션 전체에서 QApplication 인스턴스를 하나만 생성한다."""
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def library_vm(qapp_instance):
    """LibraryViewModel — 모든 핸들러 목으로 대체."""
    from gui.view_models.library_vm import LibraryViewModel

    return LibraryViewModel(
        get_videos=_handler([]),
        search_videos=_handler([]),
        get_categories=_handler([]),
        get_tags=_handler([]),
        add_video=MagicMock(),
        update_video=MagicMock(),
        delete_video=MagicMock(),
        mark_watched=MagicMock(),
        create_category=MagicMock(),
        rename_category=MagicMock(),
        delete_category=MagicMock(),
        move_category=MagicMock(),
        delete_tag=MagicMock(),
        assign_category=MagicMock(),
        get_video_detail=_handler(None),
        refresh_metadata=MagicMock(),
    )


@pytest.fixture
def download_vm(qapp_instance):
    """DownloadViewModel — 이벤트 브릿지 포함 목."""
    from gui.view_models.download_vm import DownloadViewModel

    bridge = MagicMock()
    bridge.add_progress_listener = MagicMock()
    bridge.add_completed_listener = MagicMock()
    bridge.add_failed_listener = MagicMock()

    return DownloadViewModel(
        start_handler=MagicMock(),
        cancel_handler=MagicMock(),
        queue_handler=_handler([]),
        history_handler=_handler([]),
        event_bridge=bridge,
    )


@pytest.fixture
def feed_vm(qapp_instance):
    """FeedViewModel 목."""
    from gui.view_models.feed_vm import FeedViewModel

    return FeedViewModel(handler=_handler([]))


@pytest.fixture
def monitoring_vm(qapp_instance):
    """MonitoringViewModel 목."""
    from gui.view_models.monitoring_vm import MonitoringViewModel

    return MonitoringViewModel(
        subscribe_handler=MagicMock(),
        unsubscribe_handler=MagicMock(),
        set_rule_handler=MagicMock(),
        get_subs_handler=_handler([]),
    )


@pytest.fixture
def clip_vm(qapp_instance):
    """ClipViewModel 목."""
    from gui.view_models.clip_vm import ClipViewModel

    return ClipViewModel(
        extract_handler=MagicMock(),
        delete_handler=MagicMock(),
        get_clips_handler=_handler([]),
    )
