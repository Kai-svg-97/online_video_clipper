"""워치 폴더 실행부 — 폴더를 훑어 주소를 뽑고, 처리한 파일을 옮긴다.

판정 규칙은 전부 `domain/library/watch_folder.py`에 있다. 여기는 그 규칙대로
**파일을 만지는 일**만 한다.

**어떤 실패도 앱을 멈추지 않는다.** 워치 폴더는 편의 기능이고, 사용자가 이상한
파일을 넣거나 권한이 없을 수 있다. 실패는 로그로 남기고 다음 파일로 넘어간다.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

from domain.library.watch_folder import (
    DONE_DIR_NAME,
    MAX_PER_SCAN,
    done_name,
    extract_urls,
    is_settled,
    is_watched,
)

logger = logging.getLogger(__name__)


@dataclass
class ScanResult:
    """한 번 훑은 결과 — 화면이 한 줄로 알리기 위한 최소 정보."""

    urls: list[str] = field(default_factory=list)
    files: int = 0            # 실제로 처리한 파일 수
    skipped_recent: int = 0   # 아직 복사 중일 수 있어 미룬 파일 수


class WatchFolderScanner:
    """지정한 폴더에서 주소를 거둬들인다."""

    def __init__(self, folder: Path | str) -> None:
        self._folder = Path(folder)

    @property
    def folder(self) -> Path:
        return self._folder

    def scan(self, limit: int = MAX_PER_SCAN) -> ScanResult:
        """폴더를 한 번 훑는다. 처리한 파일은 `처리됨/`으로 옮긴다."""
        result = ScanResult()
        if not self._folder.is_dir():
            return result

        done_dir = self._folder / DONE_DIR_NAME
        now = time.time()
        for path in sorted(self._folder.iterdir()):
            if len(result.urls) >= limit:
                break
            if not path.is_file() or not is_watched(path.name):
                continue
            try:
                age = now - path.stat().st_mtime
            except OSError:
                logger.exception("워치 폴더 파일 정보를 읽지 못함: %s", path)
                continue
            if not is_settled(age):
                # 복사 중일 수 있다 — 다음 회차에 담는다(늦는 것은 괜찮다).
                result.skipped_recent += 1
                continue

            urls = self._read_urls(path, limit - len(result.urls))
            if not urls:
                # 주소가 없는 파일은 **옮기지 않는다** — 사용자가 실수로 넣었거나
                # 아직 채우는 중일 수 있고, 말없이 옮기면 사라진 것처럼 보인다.
                logger.info("워치 폴더: 주소를 찾지 못함 — 그대로 둔다: %s", path.name)
                continue

            result.urls.extend(urls)
            if self._move_to_done(path, done_dir):
                result.files += 1

        if result.urls:
            logger.info(
                "워치 폴더: 주소 %d건 수집(파일 %d개%s)",
                len(result.urls), result.files,
                f", {result.skipped_recent}개는 다음에" if result.skipped_recent else "",
            )
        return result

    # ── 내부 ──────────────────────────────────────────────────────

    def _read_urls(self, path: Path, limit: int) -> list[str]:
        try:
            # 브라우저가 만든 파일은 UTF-8이지만 오래된 것은 다를 수 있다.
            # 읽기 자체가 실패하면 아무것도 못 하므로 깨진 글자를 감수하고 읽는다.
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            logger.exception("워치 폴더 파일을 읽지 못함: %s", path)
            return []
        return extract_urls(content, limit=limit)

    def _move_to_done(self, path: Path, done_dir: Path) -> bool:
        """처리한 파일을 옮긴다. 옮기지 못하면 **다시 담지 않도록** False."""
        try:
            done_dir.mkdir(parents=True, exist_ok=True)
            taken = [p.name for p in done_dir.iterdir()]
            path.replace(done_dir / done_name(path.name, taken))
            return True
        except OSError:
            logger.exception(
                "워치 폴더: 처리한 파일을 옮기지 못함 — 다음 회차에 또 읽힐 수 있다: %s",
                path,
            )
            return False
