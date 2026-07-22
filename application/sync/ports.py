"""sync 애플리케이션 포트(추상화).

DDD 의존성 규칙(`gui → application → domain ← infrastructure`)에 따라 application은
infrastructure 구체 클래스를 import 하지 않고 여기 정의된 Protocol에 의존한다.
infrastructure의 어댑터가 구조적 타이핑으로 이를 만족시키고, composition root(`main.py`)가
구체 구현을 주입한다.

이들은 순수 인프라 관심사(blob store, op 로그, OS 비밀)라 도메인 포트(`domain/shared/ports.py`)와
분리해 여기 둔다.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

from domain.sync.value_objects import Op, SnapshotManifest


@dataclass(frozen=True, slots=True)
class RemoteFile:
    """원격 파일 메타. checksum은 provider 네이티브 값(Drive md5 / OneDrive quickXorHash)으로,
    provider 간 교차 비교 불가 — 파일 identity 판정은 우리 manifest.json의 sha256을 쓴다."""

    path: str
    size: int
    modified: str
    remote_id: str = ""
    checksum: str = ""


ProgressCb = Callable[[int, int], None]  # (done_bytes, total_bytes)


class ICloudSyncProvider(Protocol):
    """OneDrive / Google Drive 등 클라우드 blob store 추상화.

    구현체: infrastructure.sync.gdrive_provider / onedrive_provider
    각 기기는 자기 install-id 폴더에만 append 하므로 파일 쓰기 경합이 없다.
    """

    def provider_key(self) -> str: ...           # "gdrive" | "onedrive"
    def is_authenticated(self) -> bool: ...
    def account_name(self) -> str | None: ...
    def ensure_root(self) -> None: ...            # 앱 루트 폴더 보장(멱등)

    def list_files(self, prefix: str = "") -> list[RemoteFile]: ...
    def stat(self, remote_path: str) -> RemoteFile | None: ...
    def upload_file(
        self, local_path: Path, remote_path: str, on_progress: ProgressCb | None = None
    ) -> RemoteFile: ...
    def download_file(
        self, remote_path: str, local_path: Path, on_progress: ProgressCb | None = None
    ) -> None: ...
    def delete_file(self, remote_path: str) -> None: ...
    def read_text(self, remote_path: str) -> str | None: ...   # manifest 등 소형
    def write_text(self, remote_path: str, content: str) -> None: ...


class IOplogStore(Protocol):
    """op 로그 세그먼트(append-only)의 로컬/원격 저장 추상화.

    구현체: infrastructure.sync.local_oplog_store / cloud_oplog_store
    """

    def append(self, ops: list[Op]) -> int: ...              # 새 세그먼트 seq 반환
    def read_since(self, install_id: str, after_seq: int) -> list[Op]: ...
    def list_installs(self) -> dict[str, int]: ...            # {install_id: head_seq}
    def head_seq(self, install_id: str) -> int: ...


class ISnapshotStore(Protocol):
    """DB 스냅샷 export/import + 컴팩션 추상화.

    구현체: infrastructure.sync.snapshot_store
    """

    def export_snapshot(self, dest: Path) -> str: ...         # sha256 반환 (VACUUM INTO)
    def import_snapshot(self, src: Path, backup_dir: Path) -> None: ...  # DB 열기 전 교체
    def local_migration_ids(self) -> frozenset[str]: ...      # 스키마 게이트용
    def read_manifest(self, path: Path) -> SnapshotManifest | None: ...


class ISecretStore(Protocol):
    """OS keyring 등 비밀 저장 추상화 (DB 밖 — pre-DB pull에서 접근 가능해야 함).

    구현체: infrastructure.sync.keyring_secret_store
    """

    def get(self, key: str) -> str | None: ...
    def set(self, key: str, value: str) -> None: ...
    def delete(self, key: str) -> None: ...
