"""미디어/썸네일 파일 동기화 엔진 (ICloudSyncProvider 위에서 동작).

oplog 는 **메타데이터만** 다룬다. 실제 다운로드 파일·썸네일 바이트는 이 서브시스템이
provider 를 통해 별도로 왕복시킨다.

설계 요점:
- **파일 identity = sha256** (`domain.sync.value_objects.FileEntry`). provider 네이티브
  체크섬(Drive md5 / OneDrive quickXorHash)은 교차 비교 불가라 쓰지 않는다.
- rel_path 는 **DATA_DIR 기준 상대경로(POSIX)** — DB의 file_path 규약과 동일하므로,
  다운로드하면 DB가 가리키는 위치(`resolve_media_path`)에 바로 놓인다. DATA_DIR 밖의
  파일(사용자가 재배치)은 이식 불가라 스캔에서 제외된다.
- 재해시 회피: 이전 스캔 매니페스트를 캐시로 두고 size+mtime 이 같으면 sha256 재사용.
- 원자적 확정: 다운로드는 `<name>.part` 에 받은 뒤 `os.replace` 로 교체.
- 계획은 순수 함수(`domain.sync.services.plan_file_sync`)라 이 엔진은 실행만 담당한다.
- **삭제 전파 안 함**(계획 참고). 백그라운드/수동 실행 전제라 협조적 취소(should_cancel)
  와 진행률 콜백(on_progress)만 노출한다 — QThread 배선은 GUI(Phase 5)가 감싼다.

원격 레이아웃: `media/manifest.json`(진실원천 sha256 목록) + `media/files/<rel_path>`(바이트).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

from domain.sync.services import FileSyncAction, FileSyncItem, plan_file_sync
from domain.sync.value_objects import FileEntry

logger = logging.getLogger(__name__)

_REMOTE_MANIFEST = "media/manifest.json"
_REMOTE_FILES = "media/files"
_PART_SUFFIX = ".part"


@dataclass(frozen=True, slots=True)
class MediaSyncProgress:
    files_done: int
    files_total: int
    bytes_done: int
    bytes_total: int
    current: str  # 현재 전송 중인 rel_path


ProgressCb = Callable[[MediaSyncProgress], None]
CancelCb = Callable[[], bool]


@dataclass
class MediaSyncReport:
    uploaded: int = 0
    downloaded: int = 0
    errors: int = 0
    error_paths: list[str] = field(default_factory=list)
    cancelled: bool = False


# ---------------------------------------------------------------------------
# 로컬 스캔 & 매니페스트 직렬화
# ---------------------------------------------------------------------------


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def scan_media_dirs(
    data_dir: Path,
    dirs: Iterable[Path],
    prev: dict[str, FileEntry] | None = None,
) -> dict[str, FileEntry]:
    """dirs 아래 모든 파일을 walk 해 rel_path→FileEntry 매니페스트를 만든다.

    - rel_path 는 data_dir 기준 상대경로. data_dir 밖의 파일은 이식 불가라 건너뛴다.
    - `.part` 임시 파일은 제외한다.
    - prev(이전 스캔)에 size+mtime 이 일치하는 항목이 있으면 sha256 을 재사용해 재해시를 피한다.
    """
    data_dir = Path(data_dir)
    prev = prev or {}
    out: dict[str, FileEntry] = {}
    for d in dirs:
        d = Path(d)
        if not d.is_dir():
            continue
        for p in d.rglob("*"):
            if not p.is_file() or p.name.endswith(_PART_SUFFIX):
                continue
            try:
                rel = p.relative_to(data_dir).as_posix()
            except ValueError:
                continue  # DATA_DIR 밖 — 이식 불가(DB도 절대경로로 저장)
            try:
                st = p.stat()
            except OSError:
                logger.exception("파일 stat 실패, 건너뜀: %s", p)
                continue
            size = st.st_size
            mtime = int(st.st_mtime)
            pe = prev.get(rel)
            if pe is not None and pe.size == size and pe.mtime == mtime and pe.sha256:
                sha = pe.sha256
            else:
                sha = _sha256(p)
            out[rel] = FileEntry(rel_path=rel, size=size, mtime=mtime, sha256=sha)
    return out


def manifest_to_json(manifest: dict[str, FileEntry]) -> str:
    return json.dumps(
        {rel: e.to_dict() for rel, e in sorted(manifest.items())},
        ensure_ascii=False,
    )


def manifest_from_json(text: str | None) -> dict[str, FileEntry]:
    if not text:
        return {}
    try:
        raw = json.loads(text)
    except Exception:
        logger.exception("미디어 매니페스트 파싱 실패 — 빈 매니페스트로 처리")
        return {}
    return {rel: FileEntry.from_dict(rel, d) for rel, d in raw.items()}


def load_local_manifest(path: Path) -> dict[str, FileEntry]:
    p = Path(path)
    if not p.exists():
        return {}
    return manifest_from_json(p.read_text(encoding="utf-8"))


def save_local_manifest(path: Path, manifest: dict[str, FileEntry]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(manifest_to_json(manifest), encoding="utf-8")
    tmp.replace(p)


# ---------------------------------------------------------------------------
# 동기화 엔진
# ---------------------------------------------------------------------------


class FileSyncer:
    """미디어/썸네일 파일을 provider 와 왕복시키는 엔진.

    provider 는 ICloudSyncProvider(구조적). data_dir/dirs/state_dir 은 테스트에서
    주입 가능하도록 명시 인자로 받는다(운영에서는 config.settings 값을 넘긴다).
    """

    def __init__(
        self,
        provider,
        data_dir: Path,
        dirs: Iterable[Path],
        state_dir: Path,
        prefer: str = "newer",
    ) -> None:
        self._p = provider
        self._data_dir = Path(data_dir)
        self._dirs = [Path(d) for d in dirs]
        self._local_manifest_path = Path(state_dir) / "media_manifest.json"
        self._prefer = prefer

    # -- 원격 매니페스트 -------------------------------------------------
    def _read_remote_manifest(self) -> dict[str, FileEntry]:
        return manifest_from_json(self._p.read_text(_REMOTE_MANIFEST))

    def _write_remote_manifest(self, manifest: dict[str, FileEntry]) -> None:
        self._p.write_text(_REMOTE_MANIFEST, manifest_to_json(manifest))

    @staticmethod
    def _remote_file_path(rel_path: str) -> str:
        return f"{_REMOTE_FILES}/{rel_path}"

    # -- 실행 ------------------------------------------------------------
    def sync(
        self,
        on_progress: ProgressCb | None = None,
        should_cancel: CancelCb | None = None,
    ) -> MediaSyncReport:
        """한 차례 양방향 파일 동기화를 수행하고 결과를 반환한다."""
        self._p.ensure_root()

        prev_local = load_local_manifest(self._local_manifest_path)
        local = scan_media_dirs(self._data_dir, self._dirs, prev_local)
        remote = self._read_remote_manifest()
        plan = plan_file_sync(local, remote, self._prefer)

        report = MediaSyncReport()
        total_files = len(plan)
        total_bytes = sum(i.size for i in plan)
        done_files = 0
        done_bytes = 0
        uploaded_rels: dict[str, FileEntry] = {}

        for item in plan:
            if should_cancel is not None and should_cancel():
                report.cancelled = True
                break

            def per_file_cb(cur: int, _tot: int, _base=done_bytes, _rel=item.rel_path) -> None:
                if on_progress is not None:
                    on_progress(
                        MediaSyncProgress(
                            files_done=done_files,
                            files_total=total_files,
                            bytes_done=_base + cur,
                            bytes_total=total_bytes,
                            current=_rel,
                        )
                    )

            try:
                if item.action == FileSyncAction.UPLOAD:
                    self._do_upload(item, local[item.rel_path], per_file_cb)
                    uploaded_rels[item.rel_path] = local[item.rel_path]
                    report.uploaded += 1
                else:
                    entry = self._do_download(item, remote[item.rel_path], per_file_cb)
                    local[item.rel_path] = entry
                    report.downloaded += 1
            except Exception:
                logger.exception("파일 전송 실패: %s (%s)", item.rel_path, item.action.value)
                report.errors += 1
                report.error_paths.append(item.rel_path)

            done_files += 1
            done_bytes += item.size
            if on_progress is not None:
                on_progress(
                    MediaSyncProgress(
                        files_done=done_files,
                        files_total=total_files,
                        bytes_done=done_bytes,
                        bytes_total=total_bytes,
                        current=item.rel_path,
                    )
                )

        # 원격 매니페스트 갱신: 다른 기기의 동시 추가를 잃지 않도록 read-merge-write.
        if uploaded_rels:
            fresh = self._read_remote_manifest()
            fresh.update(uploaded_rels)
            self._write_remote_manifest(fresh)

        save_local_manifest(self._local_manifest_path, local)
        return report

    # -- 개별 전송 -------------------------------------------------------
    def _do_upload(self, item: FileSyncItem, entry: FileEntry, cb) -> None:
        abs_local = self._data_dir / item.rel_path
        self._p.upload_file(abs_local, self._remote_file_path(item.rel_path), cb)

    def _do_download(self, item: FileSyncItem, remote_entry: FileEntry, cb) -> FileEntry:
        """원격 파일을 `.part` 로 받은 뒤 원자적으로 확정하고, 로컬 FileEntry 를 반환한다."""
        abs_final = self._data_dir / item.rel_path
        abs_final.parent.mkdir(parents=True, exist_ok=True)
        part = abs_final.with_name(abs_final.name + _PART_SUFFIX)
        try:
            self._p.download_file(self._remote_file_path(item.rel_path), part, cb)
            os.replace(part, abs_final)
        except Exception:
            part.unlink(missing_ok=True)
            raise
        st = abs_final.stat()
        # 내용은 원격과 동일하므로 sha256 은 원격 값을 신뢰(재해시 회피). 로컬 mtime 은
        # 방금 쓴 값이라 다음 스캔의 size+mtime 캐시가 이 sha256 을 그대로 재사용한다.
        return FileEntry(
            rel_path=item.rel_path,
            size=st.st_size,
            mtime=int(st.st_mtime),
            sha256=remote_entry.sha256,
        )
