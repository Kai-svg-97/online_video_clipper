"""Unit tests for RefreshCategoryMetadataHandler."""
from __future__ import annotations

from unittest.mock import MagicMock, call
from uuid import uuid4

import pytest

from application.library.commands import (
    RefreshCategoryMetadataCommand,
    RefreshCategoryMetadataHandler,
)
from domain.library.aggregates import VideoAggregate
from domain.library.entities import Tag
from domain.library.value_objects import VideoUrl


def _make_agg(url: str = "https://youtu.be/abc") -> VideoAggregate:
    return VideoAggregate.create(VideoUrl(url), "Old Title")


def _make_handler(repo=None, bus=None, ytdlp=None):
    repo = repo or MagicMock()
    bus = bus or MagicMock()
    ytdlp = ytdlp or MagicMock()
    return RefreshCategoryMetadataHandler(repo, bus, ytdlp), repo, bus, ytdlp


class TestRefreshCategoryMetadataHandler:
    def test_refreshes_video_metadata(self):
        agg = _make_agg()
        repo = MagicMock()
        repo.count.return_value = 1
        repo.search.side_effect = [[agg], []]  # first call returns 1 video, second empty
        repo.get_by_id.return_value = agg
        repo.get_or_create_tag.return_value = Tag(id=uuid4(), name="tag1")

        ytdlp = MagicMock()
        ytdlp.fetch_metadata.return_value = {
            "title": "New Title",
            "description": "New desc",
            "tags": ["tag1"],
            "categories": [],
        }
        ytdlp.download_thumbnail.return_value = None

        bus = MagicMock()
        handler = RefreshCategoryMetadataHandler(repo, bus, ytdlp)
        cmd = RefreshCategoryMetadataCommand(category_ids=[])
        count = handler.handle(cmd)

        assert count == 1
        repo.save.assert_called_once()
        saved = repo.save.call_args[0][0]
        assert saved.video.title == "New Title"
        assert saved.video.description == "New desc"

    def test_progress_callback_called(self):
        agg = _make_agg()
        repo = MagicMock()
        repo.count.return_value = 1
        repo.search.side_effect = [[agg], []]
        repo.get_by_id.return_value = agg
        repo.get_or_create_tag.return_value = Tag(id=uuid4(), name="t")

        ytdlp = MagicMock()
        ytdlp.fetch_metadata.return_value = {"title": "T", "tags": [], "categories": []}
        ytdlp.download_thumbnail.return_value = None

        progress_calls = []
        handler = RefreshCategoryMetadataHandler(repo, MagicMock(), ytdlp)
        handler.handle(
            RefreshCategoryMetadataCommand(category_ids=[]),
            on_progress=lambda cur, total: progress_calls.append((cur, total)),
        )
        assert len(progress_calls) >= 1

    def test_failed_video_skipped_silently(self):
        agg = _make_agg()
        repo = MagicMock()
        repo.count.return_value = 1
        repo.search.side_effect = [[agg], []]
        repo.get_by_id.return_value = agg

        ytdlp = MagicMock()
        ytdlp.fetch_metadata.side_effect = Exception("network error")

        handler = RefreshCategoryMetadataHandler(repo, MagicMock(), ytdlp)
        count = handler.handle(RefreshCategoryMetadataCommand(category_ids=[]))

        assert count == 0
        repo.save.assert_not_called()

    def test_calls_delete_zero_count_tags(self):
        repo = MagicMock()
        repo.count.return_value = 0
        repo.search.return_value = []

        handler = RefreshCategoryMetadataHandler(repo, MagicMock(), MagicMock())
        handler.handle(RefreshCategoryMetadataCommand(category_ids=[]))

        repo.delete_zero_count_tags.assert_called_once()
