"""DB 열기와 리포지토리 조립.

## 임포트가 무거운 것은 의도다

이 모듈은 SQLite 리포지토리 구현들을 **모듈 수준에서** 임포트한다. 예전 `main()`은
같은 임포트를 함수 안에 넣어(`# 4. 무거운 임포트 — 스플래시가 보이는 동안 수행`)
스플래시가 먼저 뜨게 했는데, 그 의도는 그대로 지켜진다 — `main()`이 **스플래시를
띄운 뒤에** 이 모듈을 임포트하기 때문이다. 함수 안에 130줄짜리 임포트 블록을 두는
대신 "무거운 것은 이 모듈 뒤에 있다"는 경계 하나로 표현한 셈이다.

따라서 **`main.py` 상단에서 이 모듈을 임포트하면 안 된다** — 시작 체감 성능이
그만큼 나빠진다(프로젝트가 명시적으로 최적화한 항목이다).
"""

from __future__ import annotations

import logging

from infrastructure.persistence.database import Database
from infrastructure.persistence.sqlite_album_repository import SqliteAlbumRepository
from infrastructure.persistence.sqlite_channel_repository import SqliteChannelRepository
from infrastructure.persistence.sqlite_clip_repository import SqliteClipRepository
from infrastructure.persistence.sqlite_download_repository import SqliteDownloadRepository
from infrastructure.persistence.sqlite_playlist_repository import (
    SqlitePlaylistFolderRepository,
    SqlitePlaylistRepository,
)
from infrastructure.persistence.sqlite_song_repository import SqliteSongRepository
from infrastructure.persistence.sqlite_subtitle_repository import SqliteSubtitleRepository
from infrastructure.persistence.sqlite_video_repository import SqliteVideoRepository

from bootstrap.context import Repositories

logger = logging.getLogger(__name__)


def bootstrap_cloud_snapshot() -> bool:
    """신규 기기면 클라우드 스냅샷에서 로컬 DB를 받아 온다. **DB를 열기 전에** 부른다.

    스냅샷 import는 DB 파일을 통째로 교체하므로, 이미 열린 연결이 있으면 안 된다.
    기존 DB가 있는 기기는 손대지 않고 증분 pull에 맡긴다(교체하면 아직 push하지
    못한 로컬 변경이 사라진다).
    """
    from infrastructure.sync.sync_service import pre_db_bootstrap

    if pre_db_bootstrap():
        logger.info("클라우드 스냅샷에서 로컬 DB 부트스트랩 완료")
        return True
    return False


def open_database() -> Database:
    """DB를 열고 스키마·마이그레이션을 적용한다."""
    db = Database()
    db.initialize()
    return db


def build_repositories(db: Database, sync_service: object | None = None) -> Repositories:
    """리포지토리를 만든다 — 동기화가 연결돼 있으면 캡처 데코레이터로 감싼다.

    `sync_service`가 연결 상태면 `Recording*` 리포지토리로 교체해 변경을 oplog에
    적재한다. 미연결이면 아무것도 감싸지 않으므로 앱 동작이 예전과 완전히 같다
    (oplog도 쌓이지 않는다).

    **`album`은 감싸지 않는다** — 앨범 캐시는 노래 정보에서 파생되는 데이터라
    동기화 대상이 아니고, 다시 조회하면 복구된다.
    """
    repos = Repositories(
        video=SqliteVideoRepository(db),
        download=SqliteDownloadRepository(db),
        clip=SqliteClipRepository(db),
        channel=SqliteChannelRepository(db),
        playlist=SqlitePlaylistRepository(db),
        folder=SqlitePlaylistFolderRepository(db),
        song=SqliteSongRepository(db),
        album=SqliteAlbumRepository(db),
        subtitle=SqliteSubtitleRepository(db),
    )
    if sync_service is None:
        return repos

    recording = sync_service.make_recording_repos(db)
    if recording is None:
        return repos

    logger.info("클라우드 동기화 연결됨 — 변경 캡처 활성화")
    from dataclasses import replace

    return replace(
        repos,
        video=recording["video"],
        song=recording["song"],
        clip=recording["clip"],
        download=recording["download"],
        playlist=recording["playlist"],
        folder=recording["folder"],
    )
