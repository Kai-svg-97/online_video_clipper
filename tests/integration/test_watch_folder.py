"""워치 폴더 실행 — 진짜 파일로.

위험한 쪽은 "못 담는 것"이 아니라 **반쯤 담는 것**과 **두 번 담는 것**이다.
복사 중인 파일을 읽으면 주소가 잘리고, 처리한 파일을 안 옮기면 다음 회차에 또 담긴다.
"""

from __future__ import annotations

import os
import time

import pytest

from domain.library.watch_folder import DONE_DIR_NAME, SETTLE_SECONDS
from infrastructure.watch.folder_scanner import WatchFolderScanner


@pytest.fixture
def folder(tmp_path):
    d = tmp_path / "인박스"
    d.mkdir()
    return d


def _drop(folder, name: str, content: str, *, age: float = SETTLE_SECONDS + 1):
    """파일을 떨군다. `age`만큼 오래된 것으로 만든다(복사가 끝난 상태)."""
    path = folder / name
    path.write_text(content, encoding="utf-8")
    old = time.time() - age
    os.utime(path, (old, old))
    return path


class TestCollecting:
    def test_주소를_거둬들인다(self, folder):
        _drop(folder, "links.txt", "https://youtu.be/aaa\nhttps://youtu.be/bbb")

        result = WatchFolderScanner(folder).scan()

        assert result.urls == ["https://youtu.be/aaa", "https://youtu.be/bbb"]
        assert result.files == 1

    def test_윈도우_링크_파일도_읽는다(self, folder):
        """링크를 폴더로 끌면 이 형식이 생긴다."""
        _drop(folder, "영상.url",
              "[InternetShortcut]\nURL=https://youtu.be/ccc\nIconIndex=0\n")

        assert WatchFolderScanner(folder).scan().urls == ["https://youtu.be/ccc"]

    def test_여러_파일을_한_번에(self, folder):
        _drop(folder, "a.txt", "https://youtu.be/aaa")
        _drop(folder, "b.txt", "https://youtu.be/bbb")

        result = WatchFolderScanner(folder).scan()

        assert len(result.urls) == 2
        assert result.files == 2

    def test_다른_파일은_건드리지_않는다(self, folder):
        photo = _drop(folder, "사진.jpg", "이건 사진")

        result = WatchFolderScanner(folder).scan()

        assert result.urls == []
        assert photo.exists()

    def test_폴더가_없으면_조용히_빈_결과(self, tmp_path):
        assert WatchFolderScanner(tmp_path / "없는폴더").scan().urls == []


class TestNoDoubleProcessing:
    def test_처리한_파일은_옮겨진다(self, folder):
        path = _drop(folder, "links.txt", "https://youtu.be/aaa")

        WatchFolderScanner(folder).scan()

        assert not path.exists()
        assert (folder / DONE_DIR_NAME / "links.txt").exists()

    def test_두_번_훑어도_한_번만_담는다(self, folder):
        """옮기지 않으면 회차마다 같은 주소가 쌓인다."""
        _drop(folder, "links.txt", "https://youtu.be/aaa")
        scanner = WatchFolderScanner(folder)

        first = scanner.scan()
        second = scanner.scan()

        assert len(first.urls) == 1
        assert second.urls == []

    def test_같은_이름을_다시_떨궈도_덮어쓰지_않는다(self, folder):
        """덮어쓰면 사용자가 되돌릴 수 없다."""
        scanner = WatchFolderScanner(folder)
        _drop(folder, "links.txt", "https://youtu.be/aaa")
        scanner.scan()
        _drop(folder, "links.txt", "https://youtu.be/bbb")
        scanner.scan()

        done = {p.name for p in (folder / DONE_DIR_NAME).iterdir()}
        assert done == {"links.txt", "links (2).txt"}

    def test_처리됨_폴더는_다시_훑지_않는다(self, folder):
        scanner = WatchFolderScanner(folder)
        _drop(folder, "links.txt", "https://youtu.be/aaa")
        scanner.scan()

        assert scanner.scan().urls == []


class TestPartialFiles:
    def test_방금_만들어진_파일은_미룬다(self, folder):
        """복사 중에 읽으면 주소가 잘린 채 들어온다."""
        _drop(folder, "links.txt", "https://youtu.be/aaa", age=0)

        result = WatchFolderScanner(folder).scan()

        assert result.urls == []
        assert result.skipped_recent == 1
        assert (folder / "links.txt").exists()      # 옮기지도 않는다

    def test_조용해지면_다음_회차에_담는다(self, folder):
        path = _drop(folder, "links.txt", "https://youtu.be/aaa", age=0)
        scanner = WatchFolderScanner(folder)
        assert scanner.scan().urls == []

        old = time.time() - (SETTLE_SECONDS + 1)
        os.utime(path, (old, old))

        assert scanner.scan().urls == ["https://youtu.be/aaa"]


class TestNoUrls:
    def test_주소가_없는_파일은_그대로_둔다(self, folder):
        """말없이 옮기면 사용자에게는 파일이 사라진 것으로 보인다."""
        path = _drop(folder, "메모.txt", "여기엔 주소가 없습니다")

        result = WatchFolderScanner(folder).scan()

        assert result.urls == []
        assert result.files == 0
        assert path.exists()


class TestLimit:
    def test_한_번에_담는_수를_제한한다(self, folder):
        """각 건이 네트워크 조회를 한 번씩 한다."""
        _drop(folder, "many.txt",
              "\n".join(f"https://youtu.be/{i:011d}" for i in range(50)))

        assert len(WatchFolderScanner(folder).scan(limit=10).urls) == 10
