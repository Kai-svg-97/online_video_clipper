"""라이브러리 DB 하루 한 번 백업 — 도메인 규칙(`domain.library.backup`)의 실행부.

**라이브 DB 파일을 그냥 복사하면 안 된다.** WAL 모드라 `-wal`·`-shm` 사이드카에
아직 본체로 넘어가지 않은 내용이 남아 있고, 그 상태의 `.db` 하나만 떼어 오면
어제까지의 DB가 된다(운이 나쁘면 손상된다). 그래서 클라우드 동기화 스냅샷과 같은
방식을 쓴다 — `VACUUM INTO`로 정합 단일 파일을 만들고, 지원하지 않는 SQLite면
`conn.backup`으로 폴백한다.

**실패해도 앱이 멈추지 않는다.** 백업은 부가 기능이고, 디스크가 꽉 찼다고 라이브러리를
못 쓰게 만들 이유가 없다. 실패는 로그로만 남긴다.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import date
from pathlib import Path

from domain.library.backup import KEEP_COUNT, backup_name, needs_backup, prune

logger = logging.getLogger(__name__)


class DbBackup:
    """하루 한 번 DB 사본을 남기고 오래된 것을 지운다.

    **배경 스레드에서 부른다** — 큰 라이브러리는 복사에 몇 초가 걸리는데, 그만큼
    시작이 멈춰 보이면 안 된다(CLAUDE.md 의 시작 성능 규칙).
    """

    def __init__(self, db_path: Path, backup_dir: Path, keep: int = KEEP_COUNT) -> None:
        self._db_path = Path(db_path)
        self._backup_dir = Path(backup_dir)
        self._keep = keep

    # ── 조회 ──────────────────────────────────────────────────────

    def existing(self) -> list[str]:
        """백업 폴더에 있는 파일 이름들(폴더가 없으면 빈 목록)."""
        try:
            if not self._backup_dir.is_dir():
                return []
            return [p.name for p in self._backup_dir.iterdir() if p.is_file()]
        except OSError:
            logger.exception("백업 폴더를 읽지 못함: %s", self._backup_dir)
            return []

    def latest(self) -> Path | None:
        """가장 최근 백업(없으면 None) — 설정 화면이 '마지막 백업'을 보여준다."""
        from domain.library.backup import is_backup_name  # noqa: PLC0415

        names = sorted(n for n in self.existing() if is_backup_name(n))
        return self._backup_dir / names[-1] if names else None

    # ── 실행 ──────────────────────────────────────────────────────

    def run_daily(self, today: date | None = None) -> Path | None:
        """오늘치가 없으면 만들고 오래된 것을 지운다. 만든 경로(안 만들었으면 None).

        예외를 밖으로 내지 않는다 — 시작 경로에서 부르므로 여기서 터지면 앱이 못 뜬다.
        """
        day = today or date.today()
        try:
            if not self._db_path.exists():
                logger.debug("백업할 DB가 아직 없음: %s", self._db_path)
                return None
            if not needs_backup(self.existing(), day):
                logger.debug("오늘치 백업이 이미 있음 — 건너뜀")
                self._prune()
                return None

            self._backup_dir.mkdir(parents=True, exist_ok=True)
            dest = self._backup_dir / backup_name(day)
            # 만들다 죽으면 반쪽짜리가 '오늘치'로 남아 내일까지 다시 시도하지 않는다.
            # 임시 이름으로 만든 뒤 마지막에 바꿔 단다.
            tmp = dest.with_suffix(".db.part")
            self._copy_consistent(tmp)
            tmp.replace(dest)
            logger.info("DB 백업 생성: %s", dest)
            self._prune()
            return dest
        except Exception:
            logger.exception("DB 백업 실패 (무시하고 계속)")
            return None

    # ── 내부 ──────────────────────────────────────────────────────

    def _copy_consistent(self, dest: Path) -> None:
        """WAL 사이드카까지 반영된 단일 파일 사본을 만든다."""
        if dest.exists():
            dest.unlink()
        src = sqlite3.connect(self._db_path)
        try:
            try:
                src.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                src.execute("VACUUM INTO ?", (str(dest),))
            except sqlite3.OperationalError:
                logger.warning("VACUUM INTO 미지원 — conn.backup 폴백")
                dst = sqlite3.connect(dest)
                try:
                    src.backup(dst)
                finally:
                    dst.close()
        finally:
            src.close()

    def _prune(self) -> None:
        for name in prune(self.existing(), self._keep):
            try:
                (self._backup_dir / name).unlink()
                logger.info("오래된 DB 백업 삭제: %s", name)
            except OSError:
                logger.exception("오래된 백업 삭제 실패: %s", name)
