"""미디어 서버 사이드카 내보내기 — 실제 DB·실제 파일로 확인한다.

이 기능의 실패는 **조용하다**: 파일을 엉뚱한 곳에 쓰거나 인코딩이 틀려도 앱에서는
"완료"로 보이고, 며칠 뒤 서버 목록이 비어 있는 것만 남는다. 그래서 위치·인코딩·
건너뛰기를 실제 파일로 못 박는다.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from uuid import uuid4

import pytest

from application.transfer.media_server import (
    ExportMediaServerCommand,
    ExportMediaServerHandler,
)
from domain.download.entities import DownloadJob, JobStatus
from domain.library.aggregates import VideoAggregate
from domain.library.value_objects import ChannelInfo, Duration, VideoUrl
from domain.song.aggregates import SongInfoAggregate
from infrastructure.persistence.database import Database
from infrastructure.persistence.sqlite_download_repository import SqliteDownloadRepository
from infrastructure.persistence.sqlite_song_repository import SqliteSongRepository
from infrastructure.persistence.sqlite_video_repository import SqliteVideoRepository


@pytest.fixture
def db():
    database = Database(Path(tempfile.mkdtemp()) / "t.db")
    database.initialize()
    return database


@pytest.fixture
def repos(db):
    return (
        SqliteVideoRepository(db),
        SqliteSongRepository(db),
        SqliteDownloadRepository(db),
    )


@pytest.fixture
def media_dir():
    return Path(tempfile.mkdtemp())


def _add_video(videos, title="영상", url=None, channel="채널", duration=185):
    agg = VideoAggregate.create(
        url=VideoUrl(url or f"https://youtu.be/{uuid4().hex[:11]}"),
        title=title,
        channel=ChannelInfo(name=channel, url="", channel_id="UC0"),
    )
    agg.update_metadata(duration=Duration(duration), description="설명 본문")
    videos.save(agg)
    return agg


def _add_download(downloads, url, path: Path):
    path.write_bytes(b"media")
    job = DownloadJob.create(url=str(url), title="t")
    job.status = JobStatus.COMPLETED
    job.file_path = str(path)
    downloads.save(job)
    return job


def _export(repos, **kw):
    videos, songs, downloads = repos
    handler = ExportMediaServerHandler(videos, songs, downloads)
    return handler.handle(ExportMediaServerCommand(**kw))


class TestNfoPlacement:
    def test_미디어_파일_옆에_같은_이름으로_쓴다(self, repos, media_dir):
        videos, _, downloads = repos
        agg = _add_video(videos)
        media = media_dir / "영상.mp4"
        _add_download(downloads, agg.video.url, media)

        result = _export(repos)

        nfo = media_dir / "영상.nfo"
        assert nfo.exists()
        assert result.nfo_written == 1

    def test_UTF8로_쓴다(self, repos, media_dir):
        """기본 인코딩(Windows=cp949)으로 쓰면 다른 기기에서 깨진다."""
        videos, _, downloads = repos
        agg = _add_video(videos, title="한글 제목 & 기호")
        _add_download(downloads, agg.video.url, media_dir / "영상.mp4")

        _export(repos)

        text = (media_dir / "영상.nfo").read_text(encoding="utf-8")
        assert "한글 제목 &amp; 기호" in text

    def test_내용에_메타데이터가_들어간다(self, repos, media_dir):
        videos, _, downloads = repos
        agg = _add_video(videos, title="제목", channel="어떤채널")
        _add_download(downloads, agg.video.url, media_dir / "영상.mp4")

        _export(repos)

        text = (media_dir / "영상.nfo").read_text(encoding="utf-8")
        assert "<title>제목</title>" in text
        assert "<studio>어떤채널</studio>" in text
        assert "<plot>설명 본문</plot>" in text
        assert "<runtime>3</runtime>" in text


class TestSkipping:
    def test_받아_둔_파일이_없으면_건너뛴다(self, repos, media_dir):
        """서버가 읽을 미디어가 없는데 사이드카만 남겨도 쓸모가 없다."""
        videos, _, _ = repos
        _add_video(videos)

        result = _export(repos)

        assert result.nfo_written == 0
        assert result.skipped_no_file == 1
        assert list(media_dir.iterdir()) == []

    def test_경로만_있고_파일이_사라졌으면_건너뛴다(self, repos, media_dir):
        videos, _, downloads = repos
        agg = _add_video(videos)
        media = media_dir / "영상.mp4"
        _add_download(downloads, agg.video.url, media)
        media.unlink()

        result = _export(repos)

        assert result.skipped_no_file == 1


class TestSongs:
    def test_노래는_musicvideo로_쓴다(self, repos, media_dir):
        videos, songs, downloads = repos
        agg = _add_video(videos, title="가수 - 곡 (Official MV)")
        _add_download(downloads, agg.video.url, media_dir / "노래.mp4")
        song = SongInfoAggregate.create(agg.id, is_song=True)
        song.apply_fetched(artist="가수", album="앨범", song_title="곡")
        songs.save(song)

        _export(repos)

        text = (media_dir / "노래.nfo").read_text(encoding="utf-8")
        assert "<musicvideo>" in text
        assert "<artist>가수</artist>" in text
        assert "<album>앨범</album>" in text
        assert "<title>곡</title>" in text     # 영상 제목의 꼬리표가 아니라 곡 제목


class TestM3u:
    def test_재생목록을_쓴다(self, repos, media_dir):
        videos, _, downloads = repos
        for i in range(2):
            agg = _add_video(videos, title=f"영상{i}")
            _add_download(downloads, agg.video.url, media_dir / f"영상{i}.mp4")
        m3u = media_dir / "목록.m3u"

        result = _export(repos, m3u_path=str(m3u))

        text = m3u.read_text(encoding="utf-8")
        assert text.startswith("#EXTM3U")
        assert text.count("#EXTINF:") == 2
        assert result.m3u_entries == 2

    def test_경로를_비우면_만들지_않는다(self, repos, media_dir):
        videos, _, downloads = repos
        agg = _add_video(videos)
        _add_download(downloads, agg.video.url, media_dir / "영상.mp4")

        _export(repos, m3u_path="")

        assert not any(p.suffix == ".m3u" for p in media_dir.iterdir())

    def test_상위_폴더가_없으면_만든다(self, repos, media_dir):
        videos, _, downloads = repos
        agg = _add_video(videos)
        _add_download(downloads, agg.video.url, media_dir / "영상.mp4")
        m3u = media_dir / "새폴더" / "목록.m3u"

        _export(repos, m3u_path=str(m3u))

        assert m3u.exists()


class TestOptions:
    def test_nfo를_끄면_재생목록만_만든다(self, repos, media_dir):
        videos, _, downloads = repos
        agg = _add_video(videos)
        _add_download(downloads, agg.video.url, media_dir / "영상.mp4")
        m3u = media_dir / "목록.m3u"

        result = _export(repos, write_nfo=False, m3u_path=str(m3u))

        assert result.nfo_written == 0
        assert not (media_dir / "영상.nfo").exists()
        assert m3u.exists()
