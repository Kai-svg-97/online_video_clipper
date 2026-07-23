"""로컬 폴더 기반 클라우드 provider (ICloudSyncProvider 구현).

지정한 **로컬 디렉터리**를 원격 저장소로 취급한다. OneDrive/Google Drive 데스크톱 앱이
동기화하는 폴더(예: `C:/Users/<me>/OneDrive/ovc-sync`)를 가리키면, 실제 클라우드 왕복은 OS
동기화 클라이언트가 처리하고 이 앱은 파일만 읽고 쓴다 — **OAuth·API 키가 필요 없다.**

가장 견고하고 설정이 쉬운 sync 경로라 기본 옵션으로 제공한다(gdrive/onedrive API provider는
직접 연동을 원하는 사용자용). 각 기기는 자기 install-id 폴더에만 append하므로 두 기기가 같은
폴더를 공유해도 파일 쓰기 경합이 없다(oplog CRDT 설계 그대로).

쓰기는 tmp→os.replace로 원자적으로 확정해 OS 동기화 클라이언트가 부분 파일을 올리지 않게 한다.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from application.sync.ports import ProgressCb, RemoteFile

logger = logging.getLogger(__name__)

_CHUNK = 1024 * 1024  # 1MB — 진행률 콜백 단위


class FolderProvider:
    """ICloudSyncProvider를 구조적으로 만족(로컬 디렉터리 백엔드)."""

    def __init__(self, root: Path | str) -> None:
        self._root = Path(root)

    # -- 신원 -----------------------------------------------------------
    def provider_key(self) -> str:
        return "folder"

    def is_authenticated(self) -> bool:
        # 루트가 존재하거나 생성 가능하면 '인증됨'으로 본다(자격증명 개념 없음).
        try:
            self._root.mkdir(parents=True, exist_ok=True)
            return self._root.is_dir()
        except OSError:
            logger.exception("동기화 폴더 접근 불가: %s", self._root)
            return False

    def account_name(self) -> str | None:
        return str(self._root)

    def ensure_root(self) -> None:
        self._root.mkdir(parents=True, exist_ok=True)

    # -- 경로 -----------------------------------------------------------
    def _abs(self, remote_path: str) -> Path:
        return self._root / remote_path

    # -- 목록/조회 ------------------------------------------------------
    def list_files(self, prefix: str = "") -> list[RemoteFile]:
        out: list[RemoteFile] = []
        if not self._root.is_dir():
            return out
        for p in self._root.rglob("*"):
            if p.is_file():
                rel = p.relative_to(self._root).as_posix()
                if rel.startswith(prefix):
                    st = p.stat()
                    out.append(RemoteFile(path=rel, size=st.st_size,
                                          modified=str(int(st.st_mtime))))
        return out

    def stat(self, remote_path: str) -> RemoteFile | None:
        p = self._abs(remote_path)
        if not p.is_file():
            return None
        st = p.stat()
        return RemoteFile(path=remote_path, size=st.st_size, modified=str(int(st.st_mtime)))

    # -- 업로드/다운로드 (원자적, 진행률) --------------------------------
    def upload_file(
        self, local_path: Path, remote_path: str, on_progress: ProgressCb | None = None
    ) -> RemoteFile:
        dest = self._abs(remote_path)
        self._copy(Path(local_path), dest, on_progress)
        st = dest.stat()
        return RemoteFile(path=remote_path, size=st.st_size, modified=str(int(st.st_mtime)))

    def download_file(
        self, remote_path: str, local_path: Path, on_progress: ProgressCb | None = None
    ) -> None:
        self._copy(self._abs(remote_path), Path(local_path), on_progress)

    @staticmethod
    def _copy(src: Path, dest: Path, on_progress: ProgressCb | None) -> None:
        """src→dest를 청크 복사한다. tmp→os.replace로 원자적 확정(부분 파일 방지)."""
        dest.parent.mkdir(parents=True, exist_ok=True)
        total = src.stat().st_size
        tmp = dest.with_name(dest.name + ".ovctmp")
        done = 0
        try:
            with open(src, "rb") as fsrc, open(tmp, "wb") as fdst:
                while True:
                    chunk = fsrc.read(_CHUNK)
                    if not chunk:
                        break
                    fdst.write(chunk)
                    done += len(chunk)
                    if on_progress is not None:
                        on_progress(done, total)
            os.replace(tmp, dest)
        except Exception:
            tmp.unlink(missing_ok=True)
            raise

    # -- 삭제/텍스트 ----------------------------------------------------
    def delete_file(self, remote_path: str) -> None:
        self._abs(remote_path).unlink(missing_ok=True)

    def read_text(self, remote_path: str) -> str | None:
        p = self._abs(remote_path)
        try:
            return p.read_text(encoding="utf-8") if p.is_file() else None
        except OSError:
            logger.exception("동기화 파일 읽기 실패: %s", remote_path)
            return None

    def write_text(self, remote_path: str, content: str) -> None:
        dest = self._abs(remote_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".ovctmp")
        tmp.write_text(content, encoding="utf-8")
        os.replace(tmp, dest)
