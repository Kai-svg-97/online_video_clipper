"""클라우드 동기화 조립·오케스트레이션 (composition root 인접).

sync 스택(secret store·device·clock·oplog store·applier·snapshot·recorder·provider)을 한 곳에
모아, GUI(sync_vm)·main.py가 얇게 쓰도록 고수준 동작(connect/disconnect/sync_now/sync_media/
status/캡처 repo 래핑)만 노출한다. 실제 OAuth·네트워크는 호출자(QThread)가 백그라운드에서
돌린다.

**캡처 게이팅**: provider가 연결된 상태로 시작했을 때만 repo를 Recording*로 래핑한다
(`make_recording_repos`). 미연결 사용자는 oplog가 쌓이지 않는다. 최초 연결 시 현재 DB를
스냅샷으로 push해 기존 상태를 클라우드에 올린다.
"""

from __future__ import annotations

import logging
from pathlib import Path

from application.sync.commands import (
    CompactHandler,
    ConnectProviderHandler,
    DisconnectProviderHandler,
    PullHandler,
    PushHandler,
)
from application.sync.queries import GetSyncStatusHandler, SyncStatusDTO
from config import settings
from infrastructure.persistence.database import MIGRATION_IDS
from infrastructure.sync.cloud_oplog_store import CloudOplogStore
from infrastructure.sync.device import Device, LamportClock
from infrastructure.sync.file_syncer import FileSyncer
from infrastructure.sync.keyring_secret_store import KeyringSecretStore
from infrastructure.sync.local_oplog_store import LocalOplogStore
from infrastructure.sync.merge_applier import MergeApplier
from infrastructure.sync.recorder import OplogRecorder
from infrastructure.sync.snapshot_store import SnapshotStore
from infrastructure.sync.sync_state import SyncStateStore

logger = logging.getLogger(__name__)

_KEYRING_SERVICE = "OnlineVideoClipper.sync"
_GDRIVE_TOKEN = "gdrive.token"
_ONEDRIVE_TOKENS = "onedrive.tokens"


def _sync_dir() -> Path:
    return Path(settings.DATA_DIR) / "sync"


def build_secret_store() -> KeyringSecretStore:
    return KeyringSecretStore(_KEYRING_SERVICE, _sync_dir() / "secrets.json")


def build_provider(provider_key: str, secret_store, *, client_id: str | None = None,
                   client_secret: str | None = None):
    """provider_key로 구체 provider를 만든다. 알 수 없으면 None."""
    if provider_key == "gdrive":
        from infrastructure.sync.gdrive_provider import GoogleDriveProvider

        return GoogleDriveProvider(secret_store)
    if provider_key == "onedrive":
        from infrastructure.sync.onedrive_provider import OneDriveProvider

        return OneDriveProvider(secret_store, client_id=client_id)
    return None


def pre_db_bootstrap(db_path: Path | None = None) -> bool:
    """DB 열기 전(pre-DB) 스냅샷 부트스트랩. 연결돼 있고 로컬 DB가 없을 때만 동작.

    반환: 스냅샷을 부트스트랩했으면 True. 실패는 삼켜서(로그) 앱 기동을 막지 않는다.
    """
    db_path = Path(db_path) if db_path else Path(settings.DATABASE_PATH)
    try:
        secret = build_secret_store()
        state_store = SyncStateStore(_sync_dir() / "sync_state.json")
        key = state_store.load().provider_key
        if not key:
            return False
        provider = build_provider(key, secret)
        if provider is None:
            return False
        from infrastructure.sync.bootstrap import bootstrap_if_fresh

        snapshot = SnapshotStore(db_path, MIGRATION_IDS)
        return bootstrap_if_fresh(
            provider, snapshot, state_store, db_path,
            backup_dir=Path(settings.BACKUP_DIR),
            tmp_dir=_sync_dir() / "tmp",
        )
    except Exception:
        logger.exception("pre-DB 스냅샷 부트스트랩 실패 — 무시하고 기동")
        return False


class SyncService:
    """런타임 sync 스택. db가 열린 뒤 조립한다."""

    def __init__(self, db, *, data_dir=None, provider=None, secret_store=None) -> None:
        self._db = db
        self._data_dir = Path(data_dir) if data_dir else Path(settings.DATA_DIR)
        self._sdir = self._data_dir / "sync"
        self._secret = secret_store or KeyringSecretStore(
            _KEYRING_SERVICE, self._sdir / "secrets.json"
        )
        self._device = Device(self._secret)
        self._install = self._device.install_id()
        self._clock = LamportClock(self._secret)
        self._local = LocalOplogStore(self._sdir / "pending", self._install)
        self._state_store = SyncStateStore(self._sdir / "sync_state.json")
        self._snapshot = SnapshotStore(db._path, MIGRATION_IDS)
        self._applier = MergeApplier(db, self._clock)
        self._recorder = OplogRecorder(
            db, self._local, self._clock, self._install, schema_ids=frozenset(MIGRATION_IDS)
        )
        # provider 주입(테스트) 또는 저장된 provider_key로 복원.
        self._provider = provider or build_provider(
            self._state_store.load().provider_key, self._secret
        )

    # -- 상태 -----------------------------------------------------------
    @property
    def install_id(self) -> str:
        return self._install

    @property
    def recorder(self) -> OplogRecorder:
        return self._recorder

    def is_connected(self) -> bool:
        try:
            return self._provider is not None and self._provider.is_authenticated()
        except Exception:
            logger.exception("동기화 연결 확인 실패")
            return False

    def status(self) -> SyncStatusDTO:
        return GetSyncStatusHandler(self._state_store, self._provider).handle()

    # -- 캡처 repo 래핑 --------------------------------------------------
    def make_recording_repos(self, db) -> dict | None:
        """연결돼 있으면 캡처 repo dict를 반환, 아니면 None(래핑 안 함).

        키: video/song/clip/download/playlist/folder. main.py가 이걸로 repo를 교체한다.
        """
        if not self.is_connected():
            return None
        from infrastructure.sync.recording_repository import (
            RecordingClipRepository,
            RecordingDownloadRepository,
            RecordingPlaylistFolderRepository,
            RecordingPlaylistRepository,
            RecordingSongRepository,
            RecordingVideoRepository,
        )

        return {
            "video": RecordingVideoRepository(db, self._recorder),
            "song": RecordingSongRepository(db, self._recorder),
            "clip": RecordingClipRepository(db, self._recorder),
            "download": RecordingDownloadRepository(db, self._recorder),
            "playlist": RecordingPlaylistRepository(db, self._recorder),
            "folder": RecordingPlaylistFolderRepository(db, self._recorder),
        }

    # -- 동기화 실행 -----------------------------------------------------
    def sync_now(self) -> tuple[int, int]:
        """push 후 pull. 미연결이면 (0,0)."""
        if not self.is_connected():
            return (0, 0)
        cloud = CloudOplogStore(self._provider)
        pushed = PushHandler(self._install, self._local, cloud, self._state_store).handle()
        pulled = PullHandler(
            self._install, cloud, self._applier, self._state_store, frozenset(MIGRATION_IDS)
        ).handle()
        return pushed, pulled

    def sync_media(self, on_progress=None, should_cancel=None):
        """미디어/썸네일 파일 동기화. 미연결이면 None."""
        if not self.is_connected():
            return None
        syncer = FileSyncer(
            self._provider, self._data_dir,
            [Path(settings.DOWNLOAD_DIR), Path(settings.THUMBNAIL_DIR)],
            self._sdir,
        )
        return syncer.sync(on_progress, should_cancel)

    def compact(self, gc: bool = False):
        """현재 DB를 스냅샷으로 발행(+선택 GC)."""
        if not self.is_connected():
            return None
        return CompactHandler(
            self._install, self._snapshot, self._provider, self._state_store,
            tmp_dir=self._sdir / "tmp", gc=gc,
        ).handle()

    # -- 연결/해제 -------------------------------------------------------
    def connect_gdrive(self, client_id: str, client_secret: str) -> bool:
        from infrastructure.sync.gdrive_provider import GoogleDriveProvider

        provider = GoogleDriveProvider(self._secret)
        if not provider.connect_run_flow(client_id, client_secret):
            return False
        return self._finish_connect(provider, "gdrive")

    def connect_onedrive(self, client_id: str) -> bool:
        from infrastructure.sync.onedrive_provider import OneDriveProvider

        if self._secret:
            self._secret.set("onedrive.client_id", client_id)
        provider = OneDriveProvider(self._secret, client_id=client_id)
        if not provider.connect_interactive():
            return False
        return self._finish_connect(provider, "onedrive")

    def _finish_connect(self, provider, provider_key: str) -> bool:
        self._provider = provider
        ConnectProviderHandler(self._state_store).handle(provider_key)
        # 최초 연결: 현재 DB 상태를 스냅샷으로 올려 다른 기기가 부트스트랩할 수 있게 한다.
        try:
            self.compact()
        except Exception:
            logger.exception("연결 직후 스냅샷 발행 실패(동기화는 계속 가능)")
        return True

    def disconnect(self) -> None:
        if self._provider is not None:
            try:
                self._provider.disconnect()
            except Exception:
                logger.exception("provider disconnect 실패")
        DisconnectProviderHandler(
            self._state_store, self._secret, (_GDRIVE_TOKEN, _ONEDRIVE_TOKENS)
        ).handle()
        self._provider = None
