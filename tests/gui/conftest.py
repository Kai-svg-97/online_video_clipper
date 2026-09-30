"""GUI 스모크 테스트용 공통 픽스처."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from PyQt6.QtCore import QCoreApplication, QEvent
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


@pytest.fixture(autouse=True)
def _flush_deferred_deletes():
    """테스트가 끝날 때 `deleteLater()`로 예약된 삭제를 실제로 수행한다.

    테스트에는 앱처럼 도는 이벤트 루프가 없어서 `deleteLater()`(qtbot.addWidget의
    정리 포함)가 예약만 되고 **세션이 끝날 때까지 집행되지 않았다.** 그렇게 쌓인
    위젯이 1만 개 가까이 되자, 전역 QSS를 바꾸는 테스트(ThemeManager.apply)가
    살아 있는 모든 위젯을 다시 polish하느라 한 번에 20초 넘게 걸렸다. 앱에서는
    이벤트 루프가 곧바로 집행하는 일이므로 여기서도 테스트마다 집행한다.
    """
    yield
    app = QApplication.instance()
    if app is not None:
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)


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
        enrich_video=MagicMock(),
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
