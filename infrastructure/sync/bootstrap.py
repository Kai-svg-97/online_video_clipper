"""스냅샷 부트스트랩 (pre-DB).

신규/빈 install 은 클라우드 스냅샷을 받아 **DB를 열기 전에** 로컬 DB로 교체한다. 그래야
시작 pull 이 op 를 적용할 기반 DB 를 갖는다. 자격증명·install_id·lamport 가 DB 밖(keyring)에
있는 이유도 이 pre-DB 접근 때문이다.

**안전 규칙**: 로컬 DB 파일이 이미 존재하면(기존 설치) 부트스트랩하지 않는다 — 스냅샷 교체는
로컬 DB 를 통째로 덮으므로 미병합 로컬 상태를 잃을 수 있다. 기존 설치가 뒤처진 경우는 증분
pull 로 따라잡는다(휴면 install 이 GC 된 세그먼트를 놓치는 경계는 열린 결정 — 그래서 컴팩션
GC 는 기본 비활성).
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

from domain.sync.services import SyncSchemaError
from domain.sync.value_objects import SnapshotManifest

logger = logging.getLogger(__name__)

_SNAPSHOT_DB = "snapshot/library.db"
_SNAPSHOT_MANIFEST = "snapshot/snapshot.json"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def bootstrap_if_fresh(
    provider,
    snapshot_store,
    state_store,
    db_path: Path,
    backup_dir: Path,
    tmp_dir: Path,
) -> bool:
    """신규 install 이면 스냅샷을 받아 DB 로 교체하고 consumed=covered 로 세팅한다.

    반환: 스냅샷을 실제로 부트스트랩했으면 True. (기존 DB 존재/스냅샷 없음/미인증이면 False)
    """
    db_path = Path(db_path)
    if db_path.exists():
        return False  # 기존 설치 — 증분 pull 에 맡긴다.

    try:
        if not provider.is_authenticated():
            return False
        txt = provider.read_text(_SNAPSHOT_MANIFEST)
    except Exception:
        logger.exception("스냅샷 매니페스트 조회 실패 — 부트스트랩 생략")
        return False
    if not txt:
        return False  # 아직 아무도 컴팩션하지 않음 — 빈 DB 로 시작 후 증분 pull.

    manifest = SnapshotManifest.from_dict(json.loads(txt))
    tmp = Path(tmp_dir) / "snapshot_download.db"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    provider.download_file(_SNAPSHOT_DB, tmp)

    actual = _sha256(tmp)
    if manifest.db_sha256 and actual != manifest.db_sha256:
        tmp.unlink(missing_ok=True)
        raise SyncSchemaError(
            f"스냅샷 sha256 불일치 — 손상/불완전 다운로드: {actual} != {manifest.db_sha256}"
        )

    # integrity_check + 스키마 게이트 + (기존 DB 없으므로 백업 없이) os.replace 로 교체.
    snapshot_store.import_snapshot(tmp, backup_dir)

    state = state_store.load()
    state.consumed = dict(manifest.covered)
    state_store.save(state)
    logger.info("스냅샷 부트스트랩 완료: covered=%s", manifest.covered)
    return True
