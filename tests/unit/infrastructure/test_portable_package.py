"""포터블 라이브러리 패키지(zip) 읽기/쓰기 — 순수 파일 I/O, SQLite 없이 검증한다."""
from __future__ import annotations

import json
import zipfile
from pathlib import Path
from uuid import uuid4

import pytest

from infrastructure.transfer.portable_package import (
    ZipLibraryPackageReader,
    ZipLibraryPackageWriter,
)


@pytest.fixture(autouse=True)
def isolated_thumbnail_dir(tmp_path, monkeypatch):
    """실사용 THUMBNAIL_DIR을 건드리지 않는다."""
    import config.settings as settings

    thumb_dir = tmp_path / "thumbnails"
    thumb_dir.mkdir()
    monkeypatch.setattr(settings, "THUMBNAIL_DIR", thumb_dir)
    return thumb_dir


def _manifest() -> dict:
    return {"format_version": 1, "app_version": "1.15.0", "video_count": 1}


def test_write_then_read_round_trips_manifest_and_data(tmp_path: Path) -> None:
    writer = ZipLibraryPackageWriter()
    reader = ZipLibraryPackageReader()
    dest = tmp_path / "out.ovcpkg"
    data = {
        "categories": [{"id": "c1", "name": "Music", "parent_id": None}],
        "videos": [
            {"id": "v1", "url": "https://youtu.be/x", "title": "제목", "thumbnail_path": ""},
        ],
    }
    writer.write(str(dest), _manifest(), data)

    manifest, read_back = reader.read(str(dest))

    assert manifest["format_version"] == 1
    assert read_back["categories"] == data["categories"]
    assert read_back["videos"][0]["title"] == "제목"


def test_thumbnail_file_is_included_and_thumbnail_rel_is_set(
    tmp_path: Path, isolated_thumbnail_dir: Path
) -> None:
    thumb_file = isolated_thumbnail_dir / "abc.jpg"
    thumb_file.write_bytes(b"\xff\xd8\xff\xe0fake-jpeg")

    writer = ZipLibraryPackageWriter()
    reader = ZipLibraryPackageReader()
    dest = tmp_path / "out.ovcpkg"
    video_id = str(uuid4())
    data = {
        "categories": [],
        "videos": [{"id": video_id, "url": "https://youtu.be/x", "title": "t",
                     "thumbnail_path": "abc.jpg"}],
    }
    writer.write(str(dest), _manifest(), data)

    _manifest_out, read_back = reader.read(str(dest))
    rel = read_back["videos"][0]["thumbnail_rel"]
    assert rel

    with zipfile.ZipFile(dest) as zf:
        assert f"thumbnails/{rel}" in zf.namelist()


def test_missing_thumbnail_file_is_skipped_without_error(
    tmp_path: Path, isolated_thumbnail_dir: Path
) -> None:
    writer = ZipLibraryPackageWriter()
    reader = ZipLibraryPackageReader()
    dest = tmp_path / "out.ovcpkg"
    data = {
        "categories": [],
        "videos": [{"id": "v1", "url": "https://youtu.be/x", "title": "t",
                     "thumbnail_path": "does_not_exist.jpg"}],
    }
    writer.write(str(dest), _manifest(), data)

    _manifest_out, read_back = reader.read(str(dest))
    assert read_back["videos"][0].get("thumbnail_rel", "") == ""


def test_no_thumbnail_path_produces_no_thumbnail_rel(tmp_path: Path) -> None:
    writer = ZipLibraryPackageWriter()
    reader = ZipLibraryPackageReader()
    dest = tmp_path / "out.ovcpkg"
    data = {"categories": [], "videos": [{"id": "v1", "url": "u", "title": "t"}]}
    writer.write(str(dest), _manifest(), data)

    _m, read_back = reader.read(str(dest))
    assert read_back["videos"][0].get("thumbnail_rel", "") == ""


def test_import_thumbnail_copies_into_local_thumbnail_dir(
    tmp_path: Path, isolated_thumbnail_dir: Path
) -> None:
    thumb_file = isolated_thumbnail_dir / "abc.jpg"
    thumb_file.write_bytes(b"\xff\xd8\xff\xe0fake-jpeg")
    writer = ZipLibraryPackageWriter()
    dest = tmp_path / "out.ovcpkg"
    data = {"categories": [], "videos": [{"id": "v1", "url": "u", "title": "t",
                                            "thumbnail_path": "abc.jpg"}]}
    writer.write(str(dest), _manifest(), data)
    _m, read_back = writer_read_back(dest)
    thumbnail_rel = read_back["videos"][0]["thumbnail_rel"]

    reader = ZipLibraryPackageReader()
    new_video_id = uuid4()
    rel = reader.import_thumbnail(str(dest), thumbnail_rel, new_video_id)

    assert rel is not None
    imported_path = isolated_thumbnail_dir / rel
    assert imported_path.exists()
    assert imported_path.read_bytes() == b"\xff\xd8\xff\xe0fake-jpeg"
    # 원본 확장자(.jpg)를 유지한다
    assert imported_path.suffix == ".jpg"


def test_import_thumbnail_missing_entry_returns_none(
    tmp_path: Path, isolated_thumbnail_dir: Path
) -> None:
    writer = ZipLibraryPackageWriter()
    dest = tmp_path / "out.ovcpkg"
    data = {"categories": [], "videos": []}
    writer.write(str(dest), _manifest(), data)

    reader = ZipLibraryPackageReader()
    assert reader.import_thumbnail(str(dest), "no-such-file.jpg", uuid4()) is None


def writer_read_back(dest: Path) -> tuple[dict, dict]:
    with zipfile.ZipFile(dest) as zf:
        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        data = json.loads(zf.read("data.json").decode("utf-8"))
    return manifest, data
