"""미디어 파일 동기화 엔진 통합 테스트 (실제 파일 I/O + fake provider)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from application.sync.ports import RemoteFile
from domain.sync.value_objects import FileEntry
from infrastructure.sync.file_syncer import (
    FileSyncer,
    MediaSyncProgress,
    load_local_manifest,
    scan_media_dirs,
)


class FakeCloudProvider:
    """temp 디렉터리 기반 ICloudSyncProvider 테스트 더블 (진행률 콜백 지원)."""

    def __init__(self, root: Path) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)

    def provider_key(self) -> str:
        return "fake"

    def is_authenticated(self) -> bool:
        return True

    def account_name(self) -> str | None:
        return "tester@example.com"

    def ensure_root(self) -> None:
        self._root.mkdir(parents=True, exist_ok=True)

    def _abs(self, remote_path: str) -> Path:
        return self._root / remote_path

    def list_files(self, prefix: str = "") -> list[RemoteFile]:
        out: list[RemoteFile] = []
        for p in self._root.rglob("*"):
            if p.is_file():
                rel = p.relative_to(self._root).as_posix()
                if rel.startswith(prefix):
                    out.append(RemoteFile(path=rel, size=p.stat().st_size, modified=""))
        return out

    def stat(self, remote_path: str) -> RemoteFile | None:
        p = self._abs(remote_path)
        if not p.is_file():
            return None
        return RemoteFile(path=remote_path, size=p.stat().st_size, modified="")

    def upload_file(self, local_path, remote_path, on_progress=None) -> RemoteFile:
        dest = self._abs(remote_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(local_path, dest)
        size = dest.stat().st_size
        if on_progress is not None:
            on_progress(size, size)
        return RemoteFile(path=remote_path, size=size, modified="")

    def download_file(self, remote_path, local_path, on_progress=None) -> None:
        src = self._abs(remote_path)
        shutil.copyfile(src, local_path)
        if on_progress is not None:
            size = Path(local_path).stat().st_size
            on_progress(size, size)

    def delete_file(self, remote_path: str) -> None:
        self._abs(remote_path).unlink(missing_ok=True)

    def read_text(self, remote_path: str) -> str | None:
        p = self._abs(remote_path)
        return p.read_text(encoding="utf-8") if p.is_file() else None

    def write_text(self, remote_path: str, content: str) -> None:
        dest = self._abs(remote_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")


def _write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


class Machine:
    """한 기기의 DATA_DIR 레이아웃 + FileSyncer 묶음."""

    def __init__(self, tmp_path: Path, name: str, provider: FakeCloudProvider) -> None:
        self.data_dir = tmp_path / name
        self.downloads = self.data_dir / "downloads"
        self.thumbnails = self.data_dir / "thumbnails"
        self.state_dir = self.data_dir / "sync"
        self.downloads.mkdir(parents=True, exist_ok=True)
        self.thumbnails.mkdir(parents=True, exist_ok=True)
        self.syncer = FileSyncer(
            provider,
            data_dir=self.data_dir,
            dirs=[self.downloads, self.thumbnails],
            state_dir=self.state_dir,
        )

    def sync(self, **kw):
        return self.syncer.sync(**kw)


@pytest.fixture()
def provider(tmp_path):
    return FakeCloudProvider(tmp_path / "cloud")


class TestScanMediaDirs:
    def test_rel_paths_and_skip_outside(self, tmp_path):
        data = tmp_path / "data"
        dl = data / "downloads"
        _write(dl / "a.mp4", b"hello")
        # DATA_DIR 밖 디렉터리는 스캔 대상이라도 rel 계산 실패로 제외돼야 한다.
        outside = tmp_path / "elsewhere"
        _write(outside / "b.mp4", b"world")
        m = scan_media_dirs(data, [dl, outside])
        assert set(m) == {"downloads/a.mp4"}
        assert m["downloads/a.mp4"].sha256

    def test_skips_part_files(self, tmp_path):
        data = tmp_path / "data"
        dl = data / "downloads"
        _write(dl / "a.mp4", b"x")
        _write(dl / "a.mp4.part", b"partial")
        m = scan_media_dirs(data, [dl])
        assert set(m) == {"downloads/a.mp4"}

    def test_sha_reused_when_size_mtime_match(self, tmp_path):
        data = tmp_path / "data"
        dl = data / "downloads"
        f = dl / "a.mp4"
        _write(f, b"hello")
        first = scan_media_dirs(data, [dl])
        rel = "downloads/a.mp4"
        # prev 에 잘못된 sha 를 심어두고 size+mtime 이 같으면 그 값을 재사용하는지 확인.
        stale = {rel: FileEntry(rel, first[rel].size, first[rel].mtime, "STALE")}
        again = scan_media_dirs(data, [dl], prev=stale)
        assert again[rel].sha256 == "STALE"

    def test_sha_recomputed_when_content_changes(self, tmp_path):
        data = tmp_path / "data"
        dl = data / "downloads"
        f = dl / "a.mp4"
        _write(f, b"hello")
        first = scan_media_dirs(data, [dl])
        rel = "downloads/a.mp4"
        # 내용 변경 + mtime 갱신
        import os
        _write(f, b"changed-content-longer")
        os.utime(f, (first[rel].mtime + 10, first[rel].mtime + 10))
        again = scan_media_dirs(data, [dl], prev=first)
        assert again[rel].sha256 != first[rel].sha256


class TestFileSyncerRoundTrip:
    def test_upload_then_other_machine_downloads(self, tmp_path, provider):
        a = Machine(tmp_path, "A", provider)
        b = Machine(tmp_path, "B", provider)

        _write(a.downloads / "song.mp4", b"video-bytes")
        _write(a.thumbnails / "song.jpg", b"thumb-bytes")

        rep_a = a.sync()
        assert rep_a.uploaded == 2
        assert rep_a.downloaded == 0
        assert rep_a.errors == 0

        rep_b = b.sync()
        assert rep_b.downloaded == 2
        assert (b.downloads / "song.mp4").read_bytes() == b"video-bytes"
        assert (b.thumbnails / "song.jpg").read_bytes() == b"thumb-bytes"

    def test_idempotent_second_sync_transfers_nothing(self, tmp_path, provider):
        a = Machine(tmp_path, "A", provider)
        _write(a.downloads / "song.mp4", b"video-bytes")
        a.sync()
        rep2 = a.sync()
        assert rep2.uploaded == 0 and rep2.downloaded == 0

    def test_bidirectional_union(self, tmp_path, provider):
        a = Machine(tmp_path, "A", provider)
        b = Machine(tmp_path, "B", provider)
        _write(a.downloads / "from_a.mp4", b"aaa")
        _write(b.downloads / "from_b.mp4", b"bbb")

        a.sync()          # a → 원격
        b.sync()          # b 업로드 + a 것 다운로드
        a.sync()          # a 가 b 것 다운로드

        assert (a.downloads / "from_b.mp4").read_bytes() == b"bbb"
        assert (b.downloads / "from_a.mp4").read_bytes() == b"aaa"

    def test_no_leftover_part_file(self, tmp_path, provider):
        a = Machine(tmp_path, "A", provider)
        b = Machine(tmp_path, "B", provider)
        _write(a.downloads / "song.mp4", b"video-bytes")
        a.sync()
        b.sync()
        parts = list(b.downloads.rglob("*.part"))
        assert parts == []

    def test_progress_callback_reaches_100pct(self, tmp_path, provider):
        a = Machine(tmp_path, "A", provider)
        _write(a.downloads / "a.mp4", b"12345")
        _write(a.downloads / "b.mp4", b"67890")
        seen: list[MediaSyncProgress] = []
        rep = a.sync(on_progress=seen.append)
        assert rep.uploaded == 2
        last = seen[-1]
        assert last.files_done == last.files_total == 2
        assert last.bytes_done == last.bytes_total

    def test_cancellation_stops_early(self, tmp_path, provider):
        a = Machine(tmp_path, "A", provider)
        for i in range(3):
            _write(a.downloads / f"f{i}.mp4", bytes([i]) * 4)
        rep = a.sync(should_cancel=lambda: True)  # 즉시 취소
        assert rep.cancelled is True
        assert rep.uploaded == 0

    def test_local_manifest_persisted(self, tmp_path, provider):
        a = Machine(tmp_path, "A", provider)
        _write(a.downloads / "song.mp4", b"video-bytes")
        a.sync()
        man = load_local_manifest(a.state_dir / "media_manifest.json")
        assert "downloads/song.mp4" in man


class TestConflict:
    def test_same_path_different_content_newer_wins(self, tmp_path, provider):
        import os
        a = Machine(tmp_path, "A", provider)
        b = Machine(tmp_path, "B", provider)
        # 두 기기가 같은 rel_path 를 서로 다른 내용으로 만든다.
        fa = a.downloads / "clash.mp4"
        fb = b.downloads / "clash.mp4"
        _write(fa, b"A-version")
        _write(fb, b"B-version-newer")
        # B 를 더 최신 mtime 으로 만든다.
        os.utime(fa, (1000, 1000))
        os.utime(fb, (2000, 2000))

        a.sync()          # 원격에 A-version
        b.sync()          # 충돌: B 가 더 최신 → 업로드(원격 덮어씀)
        a.sync()          # A 가 원격(B-version) 다운로드

        assert (a.downloads / "clash.mp4").read_bytes() == b"B-version-newer"
